"""Agent executors — the one place in this package that calls a model.

Everything else in :mod:`services.blueprint` is deterministic by design (§116).
This module is the seam where interpretation happens: it builds a prompt from
the Blueprint, calls Claude, and returns an :class:`AgentResult`. It does not
decide whether that result is allowed in — :func:`apply_agent_result` does,
and it refuses writes outside the agent's §30 boundary regardless of what the
model asked for.

Three things make this thin rather than clever:

**Context is capability-scoped (§101).** :func:`context_for` hands an agent only
the sections its capability declares readable, plus the ones it writes — an
agent that cannot see a section cannot invent references into it.

The mechanism is enforced, but *the registry does not yet use it*: every entry
in ``AGENT_REGISTRY`` currently declares ``reads = {"*"}``, so in practice each
agent still sees the whole Blueprint. Narrowing those sets is a live decision
about the agent roster, not a code change here — see
``test_narrowing_reads_actually_restricts_context`` for proof the restriction
bites once a capability declares one.

**Output is schema-constrained (§29).** The model replies through
``output_config.format``, so the envelope is machine-checked before we see it.
The Blueprint's own JSON Schema cannot be used here — structured outputs reject
``pattern`` and numeric constraints, and the contract has 17 of the former (the
§12 ID regexes). So each proposal's ``body`` travels as a JSON **string**,
parsed here and then validated against the real contract by
:class:`BlueprintService`. The model is constrained twice, by two different
mechanisms, and the strict one is the one that owns the Blueprint.

**Repair happens before anything is committed.** If a proposal fails contract
validation the error is fed back for one more attempt (§73's generate → verify
→ repair, at proposal level). Nothing has been written, so this is not the
post-generation repair chain wearing a new hat — a rejected proposal that never
becomes an artifact is the system working.

The model callable is injected, so every test in this package runs without a
network call.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from services.blueprint.agent_contract import (
    AgentResult,
    ArtifactProposal,
    ChangeRequest,
    capability_for,
)
from services.blueprint.orchestrator import DAG, TaskSpec
from services.blueprint.service import ARTIFACT_SECTIONS, BlueprintService

#: Per the claude-api reference: use Claude Opus 5 unless the caller asks
#: otherwise. Note this deliberately differs from `services.llm_client`'s
#: FORGE_ONESHOT_MODEL default, which is still pinned to an older Sonnet.
DEFAULT_MODEL = "claude-opus-5"

#: `max_tokens` caps thinking *and* response text together on Opus 5, where
#: adaptive thinking is on by default.
#:
#: 16000 was not enough. Measured: `data_model` at high effort returned 15,500
#: output tokens — 97% of that ceiling — and `page_contracts`, which emits a
#: contract per page, blew through it entirely. Truncation is a nasty failure
#: here because it costs a full extra call: the reply stops mid-JSON, fails to
#: parse, and burns a repair attempt. Cheap insurance; unused headroom is free.
DEFAULT_MAX_TOKENS = 32000

#: Above this the SDK refuses a non-streaming request it estimates could run
#: past ~10 minutes, so anything at or above the default streams.
STREAM_ABOVE = 16000


@dataclass(frozen=True)
class Usage:
    """What one model call consumed.

    Cache fields matter: reads bill at ~0.1x input and writes at ~1.25x, so a
    total that ignores them is wrong in both directions.
    """

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def as_ledger_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_tokens,
            "cache_creation_input_tokens": self.cache_write_tokens,
        }


@dataclass(frozen=True)
class ModelReply:
    """A reply plus what it cost to get.

    Clients may return a bare ``str`` instead — the executor accepts both, so
    a test fake stays a one-liner. Only real clients need to report usage.
    """

    text: str
    usage: Usage | None = None


class ModelRefused(RuntimeError):
    """The model declined the request (§ `stop_reason: "refusal"`)."""


# ---------------------------------------------------------------------------
# §29 — the structured output envelope
# ---------------------------------------------------------------------------

#: Structured outputs require ``additionalProperties: false`` on every object
#: and reject ``pattern`` / numeric constraints, so a free-form artifact body
#: cannot be expressed here. Bodies travel as JSON strings and are parsed on
#: arrival; the Blueprint contract is what actually validates their shape.
PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["proposals", "confidence", "assumptions", "issues", "change_requests"],
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "natural_key", "body"],
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Blueprint section this artifact belongs in.",
                    },
                    "natural_key": {
                        "type": "string",
                        "description": (
                            "Stable identity for this artifact — entity name, page "
                            "route, METHOD + path. Re-runs reuse it, so it must not "
                            "encode anything that changes between runs."
                        ),
                    },
                    "body": {
                        "type": "string",
                        "description": "The artifact object, encoded as a JSON string.",
                    },
                },
            },
        },
        "confidence": {
            "type": "number",
            "description": (
                "0..1. Below 0.40 the result is refused rather than applied, so "
                "report honestly instead of defensively."
            ),
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": {"type": "string"}},
        "change_requests": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "reason"],
                "properties": {
                    "section": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Model client
# ---------------------------------------------------------------------------

class ModelClient(Protocol):
    """Anything that can turn (system, user) into a JSON envelope string.

    ``enforces_schema`` says whether the transport can *guarantee* the reply
    matches ``schema``. Anthropic's ``output_config.format`` can; a plain
    JSON-mode endpoint cannot. When it cannot, :func:`build_prompt` inlines the
    schema into the system prompt so the constraint is at least stated — and
    :func:`parse_envelope` plus the repair attempt carry the weight the
    transport doesn't.
    """

    enforces_schema: bool

    def __call__(self, *, system: str, user: str, schema: dict[str, Any]) -> str: ...


#: Below this, a prefix is not worth a cache breakpoint. Opus will not cache a
#: block under ~1024 tokens at all, and a write costs 1.25x what a plain read
#: does — so tagging a short system prompt is a small guaranteed loss in
#: exchange for nothing. Estimated at 4 chars/token, which is close enough to
#: decide a threshold with.
CACHE_MIN_TOKENS = 2048

#: 5-minute TTL. The fan-out it exists for issues its calls seconds apart.
_CACHE_CONTROL = {"type": "ephemeral"}


def _cacheable(system: str) -> Any:
    """Return the system prompt as blocks, cache-tagged when it is big enough.

    The page-authoring agent carries the whole component catalog in its system
    prompt — 8,830 tokens, byte-identical for every page — and the fan-out then
    re-sent it once per page. On a 34-page application that is 300,220 input
    tokens per run spent restating the same catalog, uncached, at full price.

    Tagged as a prefix rather than per-request state: the cache is keyed on the
    block's content, so the first page in a wave writes it and the other
    thirty-three read it. Retries hit it too — the system prompt does not carry
    the feedback, so a rejected attempt and its retry share this prefix exactly.

    Returned as a string when it is too short to cache, so short-prompt nodes
    keep the plain shape and pay no write premium.
    """
    if len(system) // 4 < CACHE_MIN_TOKENS:
        return system
    return [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]


@dataclass
class AnthropicModel:
    """The real client. Uses the official SDK — see the claude-api reference.

    Deliberately omits ``temperature`` / ``top_p`` / ``top_k``: they are removed
    on Opus 5 and return a 400. Steering is done through the prompt and
    ``effort``.
    """

    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    effort: str = "high"
    #: output_config.format is a hard constraint, not a request.
    enforces_schema: bool = True
    _client: Any = None

    #: Brotli is excluded deliberately. `anthropic` >= 1.x vendors `httpx2`,
    #: whose BrotliDecoder calls `brotli.Decompressor.process(data,
    #: output_buffer_limit=...)`, and the `brotli` package's `process()` takes
    #: no keyword arguments. Any brotli-compressed response then fails to
    #: decode and surfaces as a bare `APIConnectionError` — a network-shaped
    #: error for a decoder bug, which is a genuinely misleading failure.
    #: Asking for gzip sidesteps it; drop this once brotli/httpx2 agree.
    accept_encoding: str = "gzip"

    def _anthropic(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                default_headers={"accept-encoding": self.accept_encoding}
            )
        return self._client

    def __post_init__(self) -> None:
        # Higher effort thinks more, and thinking counts against max_tokens.
        # At 16k an xhigh run hits the ceiling and returns truncated output —
        # measured, not theoretical: a sweep at xhigh came back with exactly
        # 16,000 output tokens and a Blueprint that failed validation.
        if self.max_tokens == DEFAULT_MAX_TOKENS and self.effort in ("xhigh", "max"):
            self.max_tokens = 64000

    def __call__(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=_cacheable(system),
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        client = self._anthropic()
        if self.max_tokens > STREAM_ABOVE:
            # The SDK refuses a non-streaming request it estimates could exceed
            # ~10 minutes, which any large max_tokens does. Stream and take the
            # accumulated message — same object, no event handling needed.
            with client.messages.stream(**kwargs) as stream:
                response = stream.get_final_message()
        else:
            response = client.messages.create(**kwargs)
        # Check before reading content: a refusal returns HTTP 200 with an
        # empty or partial content list, and indexing it blindly raises.
        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            raise ModelRefused(
                f"model declined this task"
                f"{f' ({detail.category})' if detail else ''}"
            )
        text = next(b.text for b in response.content if b.type == "text")
        u = response.usage
        return ModelReply(text=text, usage=Usage(
            model=self.model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        ))



@dataclass
class OpenAICompatibleModel:
    """Any OpenAI-compatible endpoint — Kimi/Moonshot, DeepSeek, Together, vLLM.

    Kimi is reached through Moonshot's OpenAI-compatible API, so the `openai`
    client works against it with a ``base_url`` swap::

        kimi = OpenAICompatibleModel(
            model="kimi-k2-0711-preview",          # confirm the current id in
            base_url="https://api.moonshot.ai/v1", # Moonshot's own docs
            api_key_env="MOONSHOT_API_KEY",
        )

    ``enforces_schema`` is False on purpose. JSON mode makes the reply *valid
    JSON*; it does not make it match our envelope. The schema therefore goes
    into the prompt, and a reply that ignores it fails in
    :func:`parse_envelope` — costing a repair attempt rather than corrupting
    anything, because nothing is committed until the Blueprint contract has
    also validated it.
    """

    model: str
    base_url: str
    api_key_env: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float | None = None
    enforces_schema: bool = False
    _client: Any = None

    def _openai(self) -> Any:
        if self._client is None:
            import os

            from openai import OpenAI

            key = os.environ.get(self.api_key_env)
            if not key:
                raise RuntimeError(
                    f"{self.api_key_env} is not set; cannot reach {self.base_url}"
                )
            self._client = OpenAI(api_key=key, base_url=self.base_url)
        return self._client

    def __call__(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        kwargs: dict[str, Any] = {}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        response = self._openai().chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise ModelRefused(f"{self.model} declined this task")
        u = response.usage
        return ModelReply(
            text=choice.message.content or "",
            usage=Usage(
                model=self.model,
                input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                output_tokens=getattr(u, "completion_tokens", 0) or 0,
            ),
        )



# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderSpec:
    """One OpenAI-compatible endpoint.

    ``enforces_schema`` is the only field that changes behaviour, and it is set
    conservatively: True only where strict ``json_schema`` support is
    documented and mature. Everywhere else the schema is stated in the prompt
    and :func:`parse_envelope` is the backstop. Flip it to True once you have
    verified a provider honours ``response_format`` with a schema — the check
    is one call that either works or 400s.
    """

    base_url: str
    api_key_env: str | None
    enforces_schema: bool = False
    note: str = ""


#: Endpoints, not models — each hosts many. Pick the model at call time.
#:
#: These URLs come from provider documentation and are **not verified from this
#: machine**; they move. Treat the table as where to look, and correct it in
#: place — it is one dict, and nothing else in the package reads these values.
PROVIDERS: dict[str, ProviderSpec] = {
    # Frontier / first-party
    "openai": ProviderSpec("https://api.openai.com/v1", "OPENAI_API_KEY",
                           enforces_schema=True, note="strict json_schema"),
    "gemini_openai": ProviderSpec(
        "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY",
        note="compatibility shim — prefer GeminiModel for full feature access"),
    "mistral": ProviderSpec("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "xai": ProviderSpec("https://api.x.ai/v1", "XAI_API_KEY", note="Grok"),

    # Chinese labs
    "moonshot": ProviderSpec("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY",
                             note="Kimi; .cn host for mainland accounts"),
    "deepseek": ProviderSpec("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "qwen": ProviderSpec("https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                         "DASHSCOPE_API_KEY", note="Alibaba DashScope"),
    "zhipu": ProviderSpec("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY",
                          note="GLM"),

    # Inference hosts — many open models each
    "groq": ProviderSpec("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "together": ProviderSpec("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "fireworks": ProviderSpec("https://api.fireworks.ai/inference/v1",
                              "FIREWORKS_API_KEY"),
    "cerebras": ProviderSpec("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "perplexity": ProviderSpec("https://api.perplexity.ai", "PERPLEXITY_API_KEY"),
    "openrouter": ProviderSpec("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                               note="aggregator — most models behind one endpoint"),

    # Self-hosted — no key
    "ollama": ProviderSpec("http://localhost:11434/v1", None),
    "vllm": ProviderSpec("http://localhost:8000/v1", None),
    "lmstudio": ProviderSpec("http://localhost:1234/v1", None),
}


class UnknownProvider(KeyError):
    pass


def provider(name: str, model: str, **overrides: Any) -> "OpenAICompatibleModel":
    """Build a client for a registered provider.

        kimi   = provider("moonshot", "kimi-k2-0711-preview")
        local  = provider("ollama", "qwen2.5-coder:32b")
        gpt    = provider("openai", "gpt-5")
    """
    try:
        spec = PROVIDERS[name]
    except KeyError as exc:
        raise UnknownProvider(
            f"{name!r} is not a registered provider; known: "
            f"{', '.join(sorted(PROVIDERS))}"
        ) from exc
    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": spec.base_url,
        "api_key_env": spec.api_key_env,
        "enforces_schema": spec.enforces_schema,
    }
    kwargs.update(overrides)
    return OpenAICompatibleModel(**kwargs)



def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip keywords Gemini's schema dialect does not accept.

    Gemini takes an OpenAPI-flavoured subset: it spells the key
    ``additional_properties``, so JSON Schema's ``additionalProperties`` is
    unrecognised and must come out. (It *does* accept ``pattern``, unlike
    Anthropic's structured outputs — irrelevant for this envelope, which has
    none, but worth knowing if you ever narrow it.)
    """
    if isinstance(schema, dict):
        return {
            k: _gemini_schema(v)
            for k, v in schema.items()
            if k != "additionalProperties"
        }
    if isinstance(schema, list):
        return [_gemini_schema(v) for v in schema]
    return schema


@dataclass
class GeminiModel:
    """Native Gemini via ``google-genai`` — not the OpenAI shim.

    Worth the separate client because ``response_schema`` is enforced
    server-side, so this keeps the strong guarantee the shim may not carry::

        gemini = GeminiModel(model="gemini-2.5-pro")

    Set ``vertexai=True`` with ``project``/``location`` to go through Vertex AI
    instead of the Gemini Developer API (credentials then come from ADC rather
    than an API key).
    """

    model: str = "gemini-2.5-pro"
    api_key_env: str = "GEMINI_API_KEY"
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float | None = None
    vertexai: bool = False
    project: str | None = None
    location: str | None = None
    #: response_schema is enforced by the service, so no prompt inlining.
    enforces_schema: bool = True
    _client: Any = None

    def _genai(self) -> Any:
        if self._client is None:
            import os

            from google import genai

            if self.vertexai:
                self._client = genai.Client(
                    vertexai=True, project=self.project, location=self.location
                )
            else:
                key = os.environ.get(self.api_key_env)
                if not key:
                    raise RuntimeError(f"{self.api_key_env} is not set")
                self._client = genai.Client(api_key=key)
        return self._client

    def __call__(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        from google.genai import types

        response = self._genai().models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=self.max_tokens,
                response_mime_type="application/json",
                response_schema=_gemini_schema(schema),
                **({"temperature": self.temperature}
                   if self.temperature is not None else {}),
            ),
        )
        text = response.text
        if not text:
            # A blocked or empty candidate returns no text; surface it the same
            # way a refusal is surfaced elsewhere rather than returning "".
            raise ModelRefused(f"{self.model} returned no content")
        m = getattr(response, "usage_metadata", None)
        return ModelReply(text=text, usage=Usage(
            model=self.model,
            input_tokens=getattr(m, "prompt_token_count", 0) or 0,
            output_tokens=getattr(m, "candidates_token_count", 0) or 0,
            cache_read_tokens=getattr(m, "cached_content_token_count", 0) or 0,
        ))


@dataclass
class ModelRouter:
    """Per-node model assignment (§27 agents are not interchangeable).

    Some stages reward a frontier model — data modelling and page contracts set
    up everything downstream. Others are mechanical enough for a cheaper or
    faster one. Route accordingly::

        router = ModelRouter(
            default=AnthropicModel(),
            by_node={"testing": kimi, "business_rules": kimi},
        )

    Whether a given split is *better* is an empirical question, and you can now
    answer it: assign, regenerate the fleet, and read the scoreboard diff.
    """

    default: ModelClient
    by_node: dict[str, ModelClient] = field(default_factory=dict)
    by_agent: dict[str, ModelClient] = field(default_factory=dict)

    def for_task(self, node: str, agent: str) -> ModelClient:
        return self.by_node.get(node) or self.by_agent.get(agent) or self.default

    def assignments(self) -> dict[str, str]:
        """What actually runs where — for logging a run's provenance."""
        out: dict[str, str] = {}
        for node, spec in DAG.items():
            client = self.for_task(node, spec.agent)
            out[node] = getattr(client, "model", client.__class__.__name__)
        return out


# ---------------------------------------------------------------------------
# §101 — capability-scoped context
# ---------------------------------------------------------------------------

def context_for(doc: dict, agent: str) -> dict:
    """The Blueprint slice this agent is permitted to see.

    An agent that cannot see a section cannot invent references into it, which
    removes a class of defect rather than detecting it later.
    """
    cap = capability_for(agent)
    always = {"application", "product", "schemaVersion", "version", "state"}
    readable = set(always)

    if "*" in cap.reads:
        readable |= set(ARTIFACT_SECTIONS) | {
            "data", "navigation", "designSystem", "uiRegistry", "security",
            "runtime", "database", "deployment", "codeMap",
        }
    else:
        readable |= cap.reads

    # Whatever it writes, it must also see — otherwise it cannot update.
    owned = {section.split(".")[0] for section in cap.writes}
    readable |= owned

    return {
        k: (v if k in owned else _without_provenance(v))
        for k, v in doc.items() if k in readable
    }


#: Where an artifact came from, not what it says. `evidence` cites the turn a
#: requirement was derived from (§12) and `syncNote` records a reconciliation
#: (§76). The agent that owns a section needs both to update them; every other
#: agent is handed them as dead weight — `evidence` alone is 27% of the
#: requirements section, restated in full to eight agents that only ever read
#: the statement.
#:
#: Dropping them for consumers is §30 as much as cost: an agent that cannot see
#: another section's provenance cannot cite it, and a fabricated citation is
#: harder to catch than a missing one.
PROVENANCE_FIELDS = frozenset({"evidence", "syncNote"})


def _without_provenance(value: Any) -> Any:
    """Strip provenance from a section an agent reads but does not own."""
    if isinstance(value, list):
        return [_without_provenance(item) for item in value]
    if isinstance(value, dict):
        return {
            k: _without_provenance(v)
            for k, v in value.items() if k not in PROVENANCE_FIELDS
        }
    return value


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM = """You are the {agent} agent in an application-engineering pipeline.

You do not write files and you do not edit the application. You propose \
artifacts for the Living Blueprint — the single definition the application is \
generated from — and a deterministic service decides whether to accept them.

Your boundary is fixed. You may write ONLY these Blueprint sections:
{writes}

If the work needs a change outside that list, do not make it. Return a \
change_request naming the section and the reason, and Smith will route it to \
the agent that owns it. A proposal outside your boundary is rejected outright, \
so it costs you the whole turn.

Rules that decide whether your output is usable:

- natural_key is an artifact's stable identity across runs — an entity's name, \
a page's route, an endpoint's METHOD and path. The same artifact must produce \
the same key next time, or it will be duplicated instead of updated. Never put \
a timestamp, a counter, or anything run-specific in it.
- Do not invent IDs. Leave `id` out of every body; identity is assigned for you.
- body is a JSON string containing one artifact object.
- Reference existing artifacts by the IDs shown in the Blueprint you were \
given. To reference something you are proposing in this same turn — a \
relationship between two entities you are creating right now — cite it by its \
`natural_key` or its `name`; identity is assigned after you reply and the \
reference is resolved for you. If something you need does not exist and you \
are not creating it, say so in `issues` rather than naming an ID you hope \
exists.
- confidence is read, not decoration: below 0.40 the result is refused and \
nothing is written. Report what you actually believe.
- Put your reasoning in `assumptions`, never inside an artifact. Artifact \
fields hold data; a field asking for identifiers wants identifiers, not an \
explanation of why you chose them.

{task}"""

NODE_TASKS: dict[str, str] = {
    "design_system": (
        "Establish this application's design language — the decisions every "
        "page then inherits rather than re-litigates: visual personality, "
        "colour roles, type scale, spacing and radius, elevation, how "
        "navigation is approached, how dense the information should be, and "
        "the accessibility and interaction conventions that hold everywhere.\n\n"
        "Decide from the domain and who uses it. A recruiter working a "
        "pipeline all day and a customer buying once a year want different "
        "densities and different levels of visual quiet. Say why each choice "
        "follows from the product, not from taste."
    ),
    "patterns": (
        "Author one pattern template for each distinct `pattern` value used by "
        "the pages in this Blueprint — no more. A template is the structure of "
        "that kind of page, not any particular page: it uses placeholders where "
        "a page's own entity, columns, actions and widgets belong, and the "
        "planner fills them in deterministically for every page that shares the "
        "pattern.\n\n"
        "Compose only from the component catalog below. Composition is "
        "positional `children` — there are no named slots. Where a component "
        "declares a childContract, honour it exactly.\n\n"
        "Do not include application chrome (AppShell, sidebar, top bar): that "
        "belongs to the layout, and a template describes the page body.\n\n"
        "Make it good. Each template is authored once and every page of that "
        "pattern inherits it, so structure, hierarchy and rhythm are worth the "
        "effort here in a way they never are per page."
    ),
    "requirements": (
        "Extract the application's requirements from the description. Each is one "
        "testable statement of something a user can do, with the evidence it came "
        "from. Do not design the solution."
    ),
    "application_model": (
        "Establish the product frame: objectives, personas, the domain vocabulary "
        "the generated app should use in its labels, and the capabilities it must "
        "offer."
    ),
    "data_model": (
        "Model the entities behind the requirements: fields with real types, which "
        "field is the human-readable label, and which fields hold sensitive data. "
        "Mark `sensitive: true` on anything personal or financial — downstream "
        "agents rely on that flag and cannot see this section to second-guess it. "
        "Declare every association as a relationship rather than leaving a bare "
        "foreign-key column to be inferred: the relationship is what later stages "
        "read to wire pages, endpoints and joins. Add constraints for uniqueness "
        "and checks the columns cannot express on their own."
    ),
    "ux_architecture": (
        "Organise the application into modules and a navigation tree. Every list "
        "and dashboard page must be reachable from navigation."
    ),
    "page_contracts": (
        "Write a Page Contract per page: its purpose in business terms, the roles "
        "it serves, the tasks users come to it for, its pattern, its primary "
        "entity, and the states it must handle. Declare empty and error states up "
        "front — a page that discovers them later ships broken.\n\n"
        "A page earns its route when it has a different job, a different primary "
        "entity, or a different audience. A different filter over the same list "
        "is not a page — it is a view. Put it in `views` with a key, a label and "
        "the filter that narrows the list, and the page it belongs to renders it "
        "as a saved view the user can switch to.\n\n"
        "So one Jobs page carries views for assigned-to-me, unassigned, overdue "
        "and ready-for-collection, rather than five routes over one list. Judge "
        "it by what a user would call the thing: if they would say \"the jobs "
        "page, filtered\", it is a view; if they would name it as its own place "
        "to go, it is a page.\n\n"
        "Fewer, richer pages are the goal. Every page costs its own design pass, "
        "and a navigation with twenty-nine entries is harder to use than one with "
        "twenty."
    ),
    "apis": (
        "Define the endpoints the pages and workflows need. Every state-changing "
        "endpoint carries a permission; a POST/PUT/PATCH/DELETE without one is a "
        "hole."
    ),
    "workflows": (
        "Define the business processes. A manually-triggered workflow must name "
        "the page that launches it, and any step that mutates an entity must name "
        "a real one."
    ),
    "business_rules": (
        "State the rules that constrain the application, each as a sentence a "
        "domain expert would recognise, and name the artifacts each governs."
    ),
    "security": (
        "Define roles and the permissions that guard entities and endpoints."
    ),
    "testing": (
        "Write the tests that verify the requirements. Every approved requirement "
        "needs at least one."
    ),
}


#: Fields never shown to an agent, because it cannot fill them correctly and
#: offering them invites a guess.
#:
#: ``id``        — identity is assigned by the deterministic layer (§12/§116).
#: ``decisions`` — a ``DEC-`` reference list. **No agent writes the decisions
#:                 section**, so those ids never exist; every agent shown this
#:                 field has instead written its design rationale into it as
#:                 prose, which fails validation. Rationale belongs in the §29
#:                 envelope's ``assumptions``, and the prompt says so.
WITHHELD_FIELDS = frozenset({"id", "decisions"})


def writable_shapes(agent: str) -> dict[str, Any]:
    """The contract slice describing what this agent is allowed to produce.

    Without this an agent knows *which* sections it may write but not what an
    artifact in them looks like — and guesses. The first live run guessed
    ``engine: "postgresql"`` where the contract says the literal ``"postgres"``,
    which the Blueprint then (correctly) refused. Handing over the target shape
    turns that class of rejection into a non-event.
    """
    import json as _json

    from services.blueprint.service import CONTRACT_PATH

    contract = _json.loads(CONTRACT_PATH.read_text("utf-8"))
    props = contract.get("properties", {})
    out: dict[str, Any] = {}
    for section in sorted(capability_for(agent).writes):
        top = section.split(".")[0]
        node = props.get(top)
        if node is None:
            continue
        for part in section.split(".")[1:]:
            node = (node.get("properties") or {}).get(part, node)
        # An artifact list: describe one item, not the array wrapper.
        shape = node.get("items", node)
        # Identity is assigned, not authored (§12/§116). Showing `id` as a
        # required property while the prompt says to omit it is a direct
        # contradiction — the first live run flagged it as an issue, correctly.
        if isinstance(shape, dict) and "properties" in shape:
            shape = dict(shape)
            shape["properties"] = {
                k: v for k, v in shape["properties"].items()
                if k not in WITHHELD_FIELDS
            }
            if "required" in shape:
                shape["required"] = [
                    r for r in shape["required"] if r not in WITHHELD_FIELDS
                ]
        out[section] = shape
    return out


#: Mirrors PLACEHOLDERS / RepeatSource in the Zod contract. Stated to the agent
#: so it does not have to infer the vocabulary from the JSON Schema.
PLACEHOLDER_VOCABULARY = (
    "$page.name", "$page.purpose", "$entity.name", "$entity.plural",
    "$titleField", "$subtitleField", "$summaryFields", "$formFields", "$columns",
    "$savedViews",
)
REPEAT_SOURCES = (
    "actions", "primaryActions", "widgets", "relatedCollections", "columns",
    "formFields", "states", "views",
)


CATALOG_ADDENDUM = """

## The components you may use

This is the whole vocabulary — the live component registry, not a summary of \
one. A `type` that is not on this list does not exist and the template will be \
rejected. Reuse before invention (§38): there is no `role-form` component, \
there is `Form` carrying an entity's fields, and the planner derives that.

Composition is positional `children`; there are no named slots. `(children)` \
marks a container. A `[children are exactly: …]` note is a hard contract on \
both the count and the order.

Placeholders are the holes the planner fills, and the set is closed — anything \
else fails. Available: {placeholders}. Inside a `repeat`, use `$item.label`, \
`$item.value`, `$item.id` — and over `relatedCollections`, `$item.columns` \
for that collection's own columns. A node may carry `repeat: "<name>"` \
to emit once per element; available lists: {repeats}. Strings in \
`{{{{…}}}}` are runtime data bindings and pass through untouched.

Author templates for exactly these patterns, which are the ones this app's \
pages use — and each template must fit **every** page listed under it, not \
the most typical one. A page with NO PRIMARY ENTITY cannot use `$entity.*`, \
`$titleField`, `$columns` or `$formFields` as a bare value; if any page in a \
group lacks an entity, build that template from `$page.name` and `$page.\
purpose` instead. A `repeat` is always safe — over an empty list it simply \
emits nothing, so an optional strip costs a page nothing.

{page_facts}
{catalog}
"""


SHAPE_ADDENDUM = """

Artifacts you write must match these shapes exactly — the Blueprint validates \
against them and refuses anything that does not fit. Note literal values and \
enums in particular; a near-miss like "postgresql" where the contract says \
"postgres" is rejected outright. Omit `id`; it is assigned for you.

```json
{shapes}
```"""


SCHEMA_ADDENDUM = """

Your reply must be a single JSON object matching this schema exactly. Emit no \
prose, no markdown fence, no commentary — the object and nothing else:

```json
{schema}
```"""


def build_prompt(
    doc: dict, node: str, *, inline_schema: bool = False, inline_shapes: bool = True,
    subject: str = "", feedback: str = "",
) -> tuple[str, str]:
    """Build (system, user) for a node.

    ``inline_schema`` is set when the transport cannot enforce the envelope, so
    the schema is stated in the prompt instead. It is a weaker guarantee — a
    statement rather than a constraint — which is why the validation below it
    is unchanged either way.
    """
    spec = DAG[node]
    cap = capability_for(spec.agent)
    system = SYSTEM.format(
        agent=spec.agent,
        writes="\n".join(f"  - {s}" for s in sorted(cap.writes)) or "  (none)",
        task=NODE_TASKS.get(node, f"Produce the {node} artifacts this stage owns."),
    )
    if inline_shapes:
        shapes = writable_shapes(spec.agent)
        if shapes:
            system += SHAPE_ADDENDUM.format(
                shapes=json.dumps(shapes, indent=2)[:12000]
            )
    if spec.agent == "a2ui_pages":
        from services.blueprint.page_planner import (
            catalog_digest, load_catalog, page_brief,
        )

        system += CATALOG_ADDENDUM.format(
            catalog=catalog_digest(load_catalog()),
            patterns="(authoring this page in full, not from a pattern)",
            page_facts="",
            placeholders=", ".join(PLACEHOLDER_VOCABULARY),
            repeats=", ".join(REPEAT_SOURCES),
        )
        brief = page_brief(doc, subject) if subject else {}
        user = (
            "Design this page in full. You are given the page's contract, the "
            "requirements it exists to satisfy, the entity behind it and the "
            "field roles already derived from that entity — use `derived` "
            "rather than reconstructing columns or form fields by eye, or use "
            "the placeholders and they will be filled in for you.\n\n"
            "Return one `pageLayouts` artifact whose `page` is "
            f"{subject!r}.\n\n```json\n"
            + json.dumps(brief, indent=2, sort_keys=True)
            + "\n```"
        )
        if feedback:
            user += (
                "\n\nYour previous attempt was rejected against the component "
                "catalog:\n\n" + feedback +
                "\n\nFix exactly those. Every prop value must be one the "
                "component's schema accepts — check the enums in the catalog "
                "above rather than choosing a plausible-sounding value."
            )
        return system, user

    if node == "page_contracts":
        # The answer space is the slot list, not "whatever pages you think of".
        # Three paragraphs of prose telling this agent that a filter belongs in
        # `views` — with the /jobs example written out — still produced
        # /jobs/mine, /jobs/unassigned, /jobs/overdue, /jobs/awaiting-decision,
        # /jobs/ready-for-collection and /jobs/awaiting-extra-work. The
        # instruction was arguing with the question: a free list of pages admits
        # a filtered page as a good answer. Slots remove the room instead.
        from services.blueprint.page_planner import (
            page_slot_prompt, page_slots,
        )

        user = (
            page_slot_prompt(doc) + "\n\n```json\n"
            + json.dumps(page_slots(doc), indent=2) + "\n```\n\n"
            "Here is the Blueprint the features were derived from.\n\n```json\n"
            + json.dumps(context_for(doc, spec.agent), indent=2, sort_keys=True)
            + "\n```"
        )
        if feedback:
            user += "\n\nYour previous attempt was rejected:\n\n" + feedback
        return system, user

    if spec.agent == "a2ui_patterns":
        # The catalog is the whole point of this agent: it authors structure
        # against what exists, not against what it remembers existing. The
        # digest keeps the prompt affordable; validation still runs against the
        # complete schemas.
        from services.blueprint.page_planner import (
            catalog_digest, load_catalog, pattern_page_facts, patterns_in_use,
        )

        system += CATALOG_ADDENDUM.format(
            catalog=catalog_digest(load_catalog()),
            patterns=", ".join(patterns_in_use(doc)) or "(none declared)",
            page_facts=pattern_page_facts(doc) or "(no pages declare a pattern)",
            placeholders=", ".join(PLACEHOLDER_VOCABULARY),
            repeats=", ".join(REPEAT_SOURCES),
        )
    if inline_schema:
        system += SCHEMA_ADDENDUM.format(
            schema=json.dumps(PROPOSAL_SCHEMA, indent=2)
        )
    user = (
        "Here is the Blueprint as it stands. Propose the artifacts your stage "
        "owns.\n\n```json\n"
        + json.dumps(context_for(doc, spec.agent), indent=2, sort_keys=True)
        + "\n```"
    )
    return system, user


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class MalformedEnvelope(ValueError):
    """The model's reply did not parse as the §29 envelope."""


def parse_envelope(raw: str, *, task_id: str, agent: str) -> AgentResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedEnvelope(f"reply was not JSON: {exc}") from exc

    proposals: list[ArtifactProposal] = []
    for i, p in enumerate(data.get("proposals") or []):
        body_raw = p.get("body")
        try:
            body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
        except json.JSONDecodeError as exc:
            raise MalformedEnvelope(f"proposal {i} body was not JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise MalformedEnvelope(f"proposal {i} body was not an object")
        # Identity is the deterministic layer's to assign (§12/§116).
        body.pop("id", None)
        proposals.append(ArtifactProposal(
            section=p.get("section", ""),
            natural_key=p.get("natural_key", ""),
            body=body,
        ))

    return AgentResult(
        task_id=task_id,
        agent=agent,
        proposals=proposals,
        confidence=float(data.get("confidence", 0.0)),
        assumptions=list(data.get("assumptions") or []),
        issues=list(data.get("issues") or []),
        change_requests=[
            ChangeRequest(section=c.get("section", ""), reason=c.get("reason", ""))
            for c in (data.get("change_requests") or [])
        ],
    )


# ---------------------------------------------------------------------------
# The executor
# ---------------------------------------------------------------------------

@dataclass
class RunUsage:
    """Per-node spend for one run.

    Costs come from :mod:`services.build_usage`, which holds real prices for
    Anthropic models only. Anything else is reported under ``unpriced`` with
    its tokens intact and its dollar figure withheld — a fabricated total is
    worse than an honest gap, especially when the point of mixing providers is
    to compare what they cost.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, node: str, agent: str, usage: Usage,
               elapsed_s: float, project: str = "") -> None:
        from services.build_usage import estimate_cost_usd, is_priced

        priced = is_priced(usage.model)
        self.entries.append({
            "node": node,
            "agent": agent,
            "model": usage.model,
            "priced": priced,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "cost_usd": (
                estimate_cost_usd(usage.model, usage.as_ledger_dict())
                if priced else None
            ),
            "elapsed_s": round(elapsed_s, 2),
        })
        # Also append to the platform-wide ledger so a Blueprint run shows up
        # alongside everything else rather than in its own silo.
        try:
            from services.build_usage import record_usage

            record_usage(
                project=project or "blueprint",
                agent=f"{node}:{agent}",
                model=usage.model,
                usage=usage.as_ledger_dict(),
                duration_ms=int(elapsed_s * 1000),
                kind="blueprint",
            )
        except Exception:  # ledger is best-effort; never fail a run over it
            pass

    @property
    def total_cost_usd(self) -> float:
        """Priced spend only. Read alongside :attr:`unpriced`."""
        return round(sum(e["cost_usd"] or 0.0 for e in self.entries), 4)

    @property
    def total_tokens(self) -> int:
        return sum(e["input_tokens"] + e["output_tokens"] for e in self.entries)

    @property
    def unpriced(self) -> list[str]:
        return sorted({e["model"] for e in self.entries if not e["priced"]})

    def summary(self) -> dict[str, Any]:
        return {
            "nodes": len(self.entries),
            "tokens": self.total_tokens,
            "cost_usd": self.total_cost_usd,
            "unpriced_models": self.unpriced,
            "elapsed_s": round(sum(e["elapsed_s"] for e in self.entries), 1),
        }

    def render(self) -> str:
        head = f"{'node':<20}{'model':<24}{'in':>9}{'out':>8}{'cost':>10}{'secs':>8}"
        lines = [head, "-" * len(head)]
        for e in self.entries:
            cost = "—" if e["cost_usd"] is None else f"${e['cost_usd']:.4f}"
            lines.append(
                f"{e['node']:<20}{e['model'][:23]:<24}"
                f"{e['input_tokens']:>9,}{e['output_tokens']:>8,}{cost:>10}"
                f"{e['elapsed_s']:>8.1f}"
            )
        lines.append("-" * len(head))
        lines.append(
            f"{'TOTAL':<20}{'':<24}{'':>9}{self.total_tokens:>8,}"
            f"{'$' + format(self.total_cost_usd, '.4f'):>10}"
        )
        if self.unpriced:
            lines.append(f"  cost excludes unpriced models: {', '.join(self.unpriced)}")
        return "\n".join(lines)


#: §27 — agents are not interchangeable, and neither is how hard they should
#: think. Effort buys thinking tokens, thinking bills as output at $25/M, and
#: output is 56% of a run's cost. Spending `high` on a node that fills in a
#: constrained shape buys nothing the schema was not already going to enforce.
#:
#: Left at `high` deliberately: every node whose output the rest of the run is
#: derived *from*. A worse data model or a worse page contract is not a cheaper
#: run, it is a worse application plus a cheaper run — and the cost of
#: re-deriving it dwarfs what the effort saved.
#:
#: `page_layouts` is the largest single line item — 34 of roughly 47 calls —
#: and is left high on purpose. Lowering it is the biggest saving available and
#: also the one most likely to show up as worse UI, so it wants an A/B against
#: the scoreboard rather than an assumption.
EFFORT_BY_NODE: dict[str, str] = {
    # Structure over work already decided; the shape is tightly constrained.
    "ux_architecture": "medium",
    "design_system": "medium",
    "page_designs": "medium",
    "patterns": "medium",
    # Tests are enumerated from what the Blueprint already claims, not invented.
    "testing": "medium",
    # A short list of named third parties.
    "integrations": "low",
}


def tiered_router(
    default_effort: str = "high", model: str = DEFAULT_MODEL,
) -> "ModelRouter":
    """A router that varies effort per node and nothing else.

    Same model everywhere: this isolates the effort question, so a regression
    can be attributed to thinking budget rather than to a model swap.
    """
    return ModelRouter(
        default=AnthropicModel(model=model, effort=default_effort),
        by_node={
            node: AnthropicModel(model=model, effort=effort)
            for node, effort in EFFORT_BY_NODE.items()
        },
    )


def make_executor(
    svc: BlueprintService,
    model: ModelClient | ModelRouter,
    *,
    repair_attempts: int = 1,
    usage: RunUsage | None = None,
) -> Callable[[TaskSpec], AgentResult]:
    """Build the callable :func:`services.blueprint.orchestrator.run` expects.

    ``repair_attempts`` retries a malformed envelope with the parser's own error
    appended to the prompt. This is pre-commit repair: nothing has been written
    to the Blueprint, so a rejected proposal simply never becomes an artifact.
    """

    def executor(spec: TaskSpec) -> AgentResult:
        client = (
            model.for_task(spec.node, spec.agent)
            if isinstance(model, ModelRouter)
            else model
        )
        system, user = build_prompt(
            svc.doc, spec.node,
            inline_schema=not getattr(client, "enforces_schema", True),
            subject=spec.subject, feedback=spec.feedback,
        )
        last: Exception | None = None

        for attempt in range(repair_attempts + 1):
            prompt = user
            if attempt and last:
                prompt = (
                    f"{user}\n\nYour previous reply was rejected: {last}\n"
                    "Return a corrected envelope. Do not explain the mistake."
                )
            t0 = time.monotonic()
            raw = client(system=system, user=prompt, schema=PROPOSAL_SCHEMA)
            elapsed = time.monotonic() - t0

            # Clients may return a bare str (test fakes) or a ModelReply.
            if isinstance(raw, ModelReply):
                text, reply_usage = raw.text, raw.usage
            else:
                text, reply_usage = raw, None
            if usage is not None and reply_usage is not None:
                usage.record(
                    node=spec.node, agent=spec.agent, usage=reply_usage,
                    elapsed_s=elapsed,
                    project=str(svc.doc.get("application", {}).get("id", "")),
                )

            try:
                return parse_envelope(text, task_id=spec.task_id, agent=spec.agent)
            except MalformedEnvelope as exc:
                last = exc

        raise MalformedEnvelope(f"{spec.node}: {last}")

    return executor

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
import logging
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from services.blueprint.agent_contract import (
    AgentResult,
    ArtifactProposal,
    ChangeRequest,
    capability_for,
)
from services.blueprint import references
from services.blueprint.orchestrator import DAG, TaskSpec
from services.blueprint.references import addendum as reference_addendum
from services.blueprint.service import ARTIFACT_SECTIONS, BlueprintService

#: Per the claude-api reference: use Claude Opus 5 unless the caller asks
#: otherwise. Note this deliberately differs from `services.llm_client`'s
#: FORGE_ONESHOT_MODEL default, which is still pinned to an older Sonnet.
logger = logging.getLogger(__name__)

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
                        "description": (
                            "The artifact object, encoded as a JSON string. Omit "
                            "`id`: identity is `natural_key` above, and the "
                            "allocator mints the id from it. An `id` written here "
                            "is claimed verbatim, so a guessed one either takes an "
                            "identity that belongs to another artifact or fails the "
                            "Blueprint contract — a module proposed as "
                            "\"ENTITY-002\" cost a run every node downstream of "
                            "ux_architecture."
                        ),
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

    #: Whether this transport can carry an image at all. Read with `getattr`
    #: and a False default, so a client written before references existed is
    #: never handed one it would reject.
    accepts_images: bool

    def __call__(self, *, system: str, user: str, schema: dict[str, Any],
                 image: str | Path | None = None,
                 images: Sequence[str | Path] = ()) -> str: ...


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


#: What a montage may be. Anthropic accepts these; anything else is a file
#: someone pointed at by mistake, and a 400 from the API is a worse way to
#: find that out than a refusal here.
IMAGE_MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}


def image_block(path: str | Path) -> dict[str, Any]:
    """A design montage as a cache-tagged image block.

    A2UI authors against the component catalog and nothing visual, which is
    why generated apps come back structurally right and looking like nothing:
    no register, no density, no colour temperature. A montage is the missing
    input, and it is identical for every page in a thirty-page fan-out — the
    strongest cache candidate in the pipeline, more so than the catalog.

    Cached and placed first so the prefix is stable: the per-page brief varies
    and must follow it, or the image is re-billed on every call.
    """
    import base64

    p = Path(path)
    media = IMAGE_MEDIA_TYPES.get(p.suffix.lower())
    if media is None:
        raise ValueError(
            f"{p.name}: not an image Anthropic accepts "
            f"({', '.join(sorted(IMAGE_MEDIA_TYPES))})"
        )
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media,
                   "data": base64.standard_b64encode(p.read_bytes()).decode()},
        "cache_control": _CACHE_CONTROL,
    }


def image_blocks(paths: Sequence[str | Path]) -> list[dict[str, Any]]:
    """Several references as one cache-tagged prefix.

    Only the last block carries ``cache_control``. A breakpoint marks a prefix
    boundary, not a block: everything ahead of it is cached by being ahead of
    it, so tagging each image spends four of the request's breakpoints to buy
    exactly what one buys. Anthropic allows four in total, and the catalog and
    system prompt want them.
    """
    if not paths:
        return []
    blocks = [image_block(p) for p in paths]
    for block in blocks[:-1]:
        block.pop("cache_control", None)
    return blocks


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
    #: The only transport here that carries images. The OpenAI-compatible and
    #: Gemini clients take (system, user, schema) and would reject the keyword.
    accepts_images: bool = True
    _client: Any = None

    #: Brotli is excluded deliberately. `anthropic` >= 1.x vendors `httpx2`,
    #: whose BrotliDecoder calls `brotli.Decompressor.process(data,
    #: output_buffer_limit=...)`, and the `brotli` package's `process()` takes
    #: no keyword arguments. Any brotli-compressed response then fails to
    #: decode and surfaces as a bare `APIConnectionError` — a network-shaped
    #: error for a decoder bug, which is a genuinely misleading failure.
    #: Asking for gzip sidesteps it; drop this once brotli/httpx2 agree.
    accept_encoding: str = "gzip"

    #: Called with each readable line of the model's reasoning, as it is
    #: produced. None means nobody is watching — every batch run, every test.
    #:
    #: The stream below was already open: `max_tokens` is above STREAM_ABOVE
    #: for every tuned node, so each call has always been a live event stream
    #: whose events were discarded in favour of the accumulated message.
    #: Forwarding the thinking costs nothing but reading them.
    reasoning: Any = None

    def _anthropic(self) -> Any:
        if self._client is None:
            import anthropic
            import httpx

            # AN UNBOUNDED WAIT IS NOT PATIENCE, IT IS A HANG. Three runs died
            # here: a connection stayed ESTABLISHED, delivered 67KB (or 124KB,
            # or nothing), and then went silent forever. No timeout was set
            # anywhere, so there was nothing to end it and nothing to retry —
            # and a stalled run and a slow one look identical from outside.
            #
            # `read` is httpx's TIME BETWEEN CHUNKS, not total elapsed, which
            # is what makes it safe on a stream: a 64k-token generation keeps
            # arriving and never trips it, while a dead socket trips in five
            # minutes and the SDK retries. A total-elapsed cap would kill the
            # long generations we depend on — page_layouts subjects measured
            # 115-138s each, legitimately.
            self._client = anthropic.Anthropic(
                default_headers={"accept-encoding": self.accept_encoding},
                timeout=httpx.Timeout(connect=15.0, read=300.0,
                                      write=60.0, pool=15.0),
                max_retries=3,
            )
        return self._client

    def __post_init__(self) -> None:
        # Higher effort thinks more, and thinking counts against max_tokens.
        # At 16k an xhigh run hits the ceiling and returns truncated output —
        # measured, not theoretical: a sweep at xhigh came back with exactly
        # 16,000 output tokens and a Blueprint that failed validation.
        if self.max_tokens == DEFAULT_MAX_TOKENS and self.effort in ("xhigh", "max"):
            self.max_tokens = 64000

    def _stream_reasoning(self, stream: Any) -> Any:
        """Drain the stream, forwarding thinking as it lands.

        A composition runs for around a minute and said nothing until it
        finished, so a long one and a stuck one looked identical — the same
        complaint as the unreported runs and the empty editor panels.

        Iterating consumes the same events `get_final_message` accumulates, so
        it is still the SDK's assembled message that comes back; nothing here
        rebuilds a reply out of deltas.
        """
        from services.llm_client import ReasoningSink

        sink = ReasoningSink(self.reasoning)
        try:
            for event in stream:
                delta = getattr(event, "delta", None)
                if getattr(delta, "type", None) == "thinking_delta":
                    sink.feed(str(getattr(delta, "thinking", "") or ""))
        finally:
            # The tail is usually the conclusion. Flushed even if the stream
            # raises, so a failed call still shows how far it got.
            sink.close()
        return stream.get_final_message()

    def __call__(self, *, system: str, user: str, schema: dict[str, Any],
                 image: str | Path | None = None,
                 images: Sequence[str | Path] = ()) -> str:
        # `image` is the single-montage spelling this started as; `images` is
        # the reference set. Both resolve to the same block list, and the
        # images lead the text because they are the stable half of the prefix.
        shown = list(images) or ([image] if image else [])
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=_cacheable(system),
            messages=[{"role": "user", "content": (
                [*image_blocks(shown), {"type": "text", "text": user}]
                if shown else user)}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        client = self._anthropic()
        if self.max_tokens > STREAM_ABOVE:
            # The SDK refuses a non-streaming request it estimates could exceed
            # ~10 minutes, which any large max_tokens does. Stream and take the
            # accumulated message.
            with client.messages.stream(**kwargs) as stream:
                if self.reasoning is None:
                    response = stream.get_final_message()
                else:
                    response = self._stream_reasoning(stream)
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
            "data", "navigation", "designSystem", "security",
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
{reply_rules}
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

#: The reply contract, per node. Everything but `data_model` proposes artifact
#: envelopes; `data_model` states entities and the envelopes are built in code.
#: A prompt that carried both would contradict itself, so this is a slot rather
#: than an addendum.
ENVELOPE_RULES = """
- natural_key is an artifact's stable identity across runs — an entity's name, \
a page's route, an endpoint's METHOD and path. The same artifact must produce \
the same key next time, or it will be duplicated instead of updated. Never put \
a timestamp, a counter, or anything run-specific in it.
- Do not invent IDs. Leave `id` out of every body; identity is assigned for you.
- body is a JSON string containing one artifact object."""

DATA_MODEL_REPLY_RULES = """
- Return `entities`: one entry per entity. No `proposals`, no \
`natural_key`, no `body` — the name IS the identity and the rest is built for \
you after you reply.
- Each entry is {{name, table, fields, description?, labelField?}} — `name` \
PascalCase singular, `table` snake_case plural, `labelField` naming the field \
a human reads to tell one record from another. Each field is {{name, type, \
required?, primaryKey?, unique?, sensitive?, enumValues?, \
description?}}.
- State a flag only when it is true. `"sensitive": false` on forty fields is \
forty facts nobody asked for, and this reply has a budget.
- A field has NO `references` key — the schema does not accept one. State \
every foreign key in `relationships`, by entity name. `references` is typed \
`^ENTITY-\\d{{3,}}$` in the Blueprint and an empty string matches nothing, so \
`"references": ""` failed validation for the whole reply and cost real runs \
seven errors at a time. It is unrepresentable here now rather than merely \
discouraged, because a pattern is advice a decoder does not enforce.
- Do not invent IDs. Identity is assigned for you from the entity's name, so \
two modules naming the same entity update one record rather than duplicating \
it — which makes a near-miss spelling the one thing that creates a duplicate."""

NODE_TASKS: dict[str, str] = {
    "figma_intelligence": (
        "Read a connected Figma design and record what it is evidence for.\n\n"
        "You are not designing the application and you are not authoring "
        "pages \u2014 composition happens later, against this design. Your "
        "output is requirements, each citing the frame that evidences it.\n\n"
        "A design is strong evidence of *what the application does* and weak "
        "evidence of *how it behaves*. Frames named for entities and actions "
        "tell you the capabilities exist. They do not tell you the rules, the "
        "permissions, the side effects or the failure paths \u2014 and a "
        "design drawn to be shown is usually missing the screens a working "
        "system needs at all. Propose what the design supports, at the "
        "confidence the design supports it, and leave the rest to be asked."
    ),
    "design_system": (
        "Establish this application's design language — the decisions every "
        "page then inherits rather than re-litigates: visual personality, "
        "colour roles, type scale, spacing and radius, elevation, how "
        "navigation is approached, how dense the information should be, and "
        "the accessibility and interaction conventions that hold everywhere.\n\n"
        "Colour comes from one of three places and they have an order. If the "
        "description names colours, use those — the user has already decided. "
        "Otherwise, if you were shown a reference, read the palette off it: "
        "that is what it was attached for, and inventing a scheme beside a "
        "picture of the one they want is the whole of what they were trying "
        "to avoid. Only with neither should you choose from the domain by "
        "colour theory rather than defaulting to blue.\n\n"
        "Whichever it is, pick a hue the domain earns — a workshop is not a "
        "clinic is not a reading app — then build the rest as a considered "
        "scheme around it: an accent that is a true complement or a near-triad "
        "rather than a second blue, subtle and hover variants derived from the "
        "primary's own hue, and status colours that stay distinguishable for "
        "the 8% of men with a red-green deficiency. Say in "
        "`visualPersonality` which of the three this came from and why, so a "
        "later change can argue with it.\n\n"
        "Decide from the domain and who uses it. A recruiter working a "
        "pipeline all day and a customer buying once a year want different "
        "densities and different levels of visual quiet. Say why each choice "
        "follows from the product, not from taste."
    ),
    "requirements": (
        "Extract the application's requirements from the description. Each is one "
        "testable statement of something a user can do, with the evidence it came "
        "from. Do not design the solution."
    ),
    "application_model": (
        "FIRST, THE LANGUAGE. If the request says what language the INTERFACE "
        "is in, set `locale` before anything else — a brief opening \"an "
        "Arabic-first noticeboard, the interface must be in Arabic\" is asking "
        "for `ar`, and leaving the default silently ships an English "
        "application to somebody who asked twice for a different one.\n\n"
        "Then the product frame: objectives, personas, the domain vocabulary "
        "the generated app should use in its labels, and the capabilities it must "
        "offer.\n\n"
        "On `locale` — set it when the request says what language the INTERFACE is in — "
        "\"Arabic-first\", \"the UI should be in French\", a brief written "
        "throughout in another language. A BCP-47 tag: `ar`, `ar-PS`, `fr`. "
        "Everything a reader sees is then authored in it, and the document is "
        "laid out right-to-left where the script calls for it.\n\n"
        "Where the request does not say, leave it. A country, a currency or a "
        "market is not a language: an application for a Cairo hospital may well "
        "be run in English, and choosing Arabic because the domain sounds Arabic "
        "would rewrite an interface nobody asked to change. The default is "
        "English, and defaulting is the right answer far more often than not."
    ),
    "data_model": (
        "Model the entities behind the requirements: fields with real types, which "
        "field is the human-readable label, and which fields hold sensitive data. "
        "Mark `sensitive: true` on anything personal or financial — downstream "
        "agents rely on that flag and cannot see this section to second-guess it. "
        "Declare every association with `references` on the field, naming the "
        "entity it points at. Not the description: `jobId: uuid` explained in "
        "English as \"Job the part was consumed on\" is a relationship no "
        "later stage can read. The page planner could not tell a row only ever "
        "written while looking at a job from a top-level record, and gave both "
        "a full list, detail and create page. Add constraints for uniqueness "
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
        "When a page only means something once something has happened, say so "
        "in `requires`. An approval screen is not a page you can look at; it "
        "is a page you can look at once something has been submitted, and "
        "against a fresh application it renders its empty state and every "
        "reviewer of it sees a correct rendering of nothing. Name the entity, "
        "the state a record of it must be in — one of that entity\'s own "
        "`enumValues`, not a state you invent — and, when a workflow is what "
        "puts a record there, name it in `producedBy`. Most pages have no "
        "precondition: a list is a list whether or not anything has happened "
        "yet, and declaring one a page does not have makes it unreviewable "
        "for no reason.\n\n"
        "When a page starts a business process, name it in `dispatches`: the "
        "page that opens the drop-off wizard declares the intake workflow, so "
        "its form can submit into it. Nothing downstream can work this out — "
        "an intake that registers the customer first looks, by its steps, like "
        "a Customer workflow rather than the one /jobs/new starts.\n\n"
        "Say how the pages connect, not just which exist. Each page lists the "
        "pages reachable from it in `navigatesTo`, by id — that is the arrow a "
        "breadcrumb follows and the reason a list page and its detail belong to "
        "one flow rather than sitting in a directory beside each other.\n\n"
        "Mark the page each audience arrives at with `entry: true`. An "
        "application has as many front doors as it has audiences: a survey tool "
        "has a dashboard its author signs in to AND a link a respondent opens "
        "straight into, and the second must never meet a login screen. `access` "
        "already says which audience a page serves, so mark one entry per "
        "distinct access level and no more.\n\n"
        "Use `presentation` when a view belongs over its caller rather than "
        "beside it. A record opened from a row is often a drawer — the reader "
        "keeps the list they were scanning — while `page` is right when the URL "
        "should be shareable. Default to `page`; choose drawer or modal "
        "deliberately.\n\n"
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
        "Define the business processes as workflows built from the workflow node "
        "catalog below. Every step IS one of those nodes: its `type` is a catalog "
        "node, and its `config` carries what that node declares it needs — the "
        "`actionType` and table/values of an action, the `expression` of a "
        "condition, the `assignType` and `assignTarget` of a human task — filled "
        "in with real values (entity tables, `{{variable}}` bindings, role names), "
        "not left for someone else. A step missing a required key is refused. "
        "Connect steps with `next` (a branching node's first target is the "
        "then-branch, its second the else-branch); the workflow's `trigger` is "
        "the start, and an `end` step is the terminal. A manually-triggered "
        "workflow must name the page that launches it, and any step that mutates "
        "an entity must name a real one.\n\n"
        "Conditions and gateway expressions are FEEL, read by the engine's "
        "parser: `=` (never `==`), `and`, `or`, `not`, names without braces "
        "(`caseType = \"Refund\" and refundAmount > 0`), membership as "
        "`stage in [\"A\", \"B\"]` with square brackets, never parentheses. "
        "Values in step "
        "config are templates over what the engine holds: the trigger's "
        "input fields by name (`{{title}}`, never `{{input.title}}`), a step's "
        "output under its key (`{{insert_case.id}}`), a variable a "
        "set_variable step set by its `variableName`; the current time and "
        "actor are the whole-value sentinels `$now`, `$today`, `$user.id`. "
        "There is no `now`, `currentUser`, `vars`, `steps` or `sequence` "
        "root; a template naming one is refused. The expression functions the "
        "engine has are sum, count, min, max, avg, abs, floor, ceiling, round, "
        "contains, starts with, ends with, matches, string, number, date, now, "
        "duration — nothing else (no concat, substring, uuid, upper, format); "
        "a reference number nothing supplies is `$uuid`, a fresh identifier, "
        "written in the insert itself. A db_insert supplies every field the "
        "data model marks required — an input by name, `$now`, `$user.id`, "
        "`$uuid`, or a literal starting state; one that omits a required "
        "field is refused, and a later db_update cannot rescue it.\n\n"
        "Declare `inputs`: what the workflow needs to start. A workflow that "
        "acts on one record declares `{name, kind: \"record\", entity}`; one "
        "that takes what a person types declares `{name, kind: \"field\", "
        "type}` per field. The control that runs the workflow must supply every "
        "required input from its page — the record a detail page shows, the "
        "fields a form collects — and a control that cannot is refused, so an "
        "input left undeclared is a button that fails when pressed."
    ),
    "business_rules": (
        "State the rules that constrain the application, each as a sentence a "
        "domain expert would recognise, and name the artifacts each governs. "
        "A rule's `when` is FEEL, read by the engine's parser: `=` (never "
        "`==`), `and`, `or`, `not`, field names without braces (`status`, "
        "never `record.status`), membership as `stage in [\"A\", \"B\"]` "
        "with square brackets, never parentheses; `null` is a value "
        "(`termEnd != null`). A condition the parser refuses is refused "
        "here, with the parser's reason.\n\n"
        "A rule that changes what a form does is `kind: \"condition_action\"`: "
        "name the `entity` whose form it governs, a `when` condition in FEEL "
        "over that entity's fields (`caseType = \"Refund\"`), and `then` "
        "actions — set_visibility, set_required, set_readonly, set_options, "
        "set_field, show_error — each naming a field the entity has. Such a "
        "rule fires on the form as a person types; a rule with only a "
        "statement constrains people, not forms."
    ),
    "security": (
        "Define roles and the permissions that guard entities and endpoints. "
        "Then say who reaches which rows: an entity whose rows belong to one "
        "user or one workspace needs an ownershipRules entry naming the entity "
        "and the column that scopes it, because that object is what the data "
        "engine turns into a WHERE clause \u2014 a prose rule beside it "
        "documents the policy and enforces nothing. Where authorisation really "
        "is by role and every holder sees every row, write that as a prose rule "
        "so the absence of a scoping object reads as a decision."
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
        out[section] = _inline_refs(shape, contract)
    return out


def _inline_refs(node: Any, contract: dict, _seen: tuple[str, ...] = ()) -> Any:
    """Replace `$ref` with what it points at, so a slice keeps its constraints.

    `writable_shapes` cuts one agent's sections out of the contract and hands
    them over as a standalone schema — but the refs inside still point into the
    whole document, at paths like
    `#/properties/pages/items/properties/data/properties/primaryEntity`, and
    the slice has no `#/properties/pages`. So every ref-typed field arrived at
    the model as a pointer to nothing.

    Measured: `data_model` emitted `references: ""` on three fields of a
    thirty-entity model. The contract requires `^ENTITY-\d{3,}$`, the whole
    document was refused for it, and thirty entities were lost. The agent was
    never told the pattern — the ref that carried it did not resolve, and the
    only thing left was a description reading "Stable ENTITY identifier".
    Prose loses to schema, again: the model call is structured-output
    constrained, so an inlined pattern is not advice, it is unrepresentable.

    Twenty-eight refs across four agents' shapes were in that state.

    CYCLES ARE LEFT ALONE. `TemplateNode` contains itself, and expanding that
    is unbounded. A ref already on the current path stays a ref — one
    unresolvable pointer is a smaller loss than a schema that does not
    terminate.
    """
    if isinstance(node, list):
        return [_inline_refs(x, contract, _seen) for x in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        if ref in _seen:
            return node
        target: Any = contract
        try:
            for part in ref[2:].split("/"):
                target = target[part]
        except (KeyError, TypeError):
            return node                      # a ref we cannot follow, left as-is
        resolved = _inline_refs(target, contract, _seen + (ref,))
        if isinstance(resolved, dict):
            # The local description wins: it was written for this field, and
            # the target's is generic.
            merged = {**resolved, **{k: v for k, v in node.items()
                                     if k != "$ref"}}
            return merged
        return resolved

    return {k: _inline_refs(v, contract, _seen) for k, v in node.items()}


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


WORKFLOW_CATALOG_ADDENDUM = """

## The workflow nodes you may use

This is the whole vocabulary — the workflow node catalog the editor's palette \
offers and the runtime executes, not a summary of one. A step `type` that is \
not on this list does not exist and the workflow will be refused. Each node \
states the configuration it needs; you author that configuration, and a step \
that leaves a required group empty is refused with the group named.

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
    subject: str = "", feedback: str = "", references: Sequence[Path] = (),
    output_dir: Any = None,
) -> tuple[str, str]:
    """Build (system, user) for a node.

    ``inline_schema`` is set when the transport cannot enforce the envelope, so
    the schema is stated in the prompt instead. It is a weaker guarantee — a
    statement rather than a constraint — which is why the validation below it
    is unchanged either way.

    ``references`` are the images the caller is about to attach. They are named
    in the system prompt rather than left to speak for themselves: an image is
    ambiguous about its own status, and the expensive reading — a screenshot of
    the system being replaced taken as a specification of the one being built —
    is the one a model reaches for unprompted.
    """
    spec = DAG[node]
    cap = capability_for(spec.agent)
    system = SYSTEM.format(
        agent=spec.agent,
        writes="\n".join(f"  - {s}" for s in sorted(cap.writes)) or "  (none)",
        reply_rules=(DATA_MODEL_REPLY_RULES if node == "data_model"
                     else ENVELOPE_RULES),
        task=NODE_TASKS.get(node, f"Produce the {node} artifacts this stage owns."),
    )
    if inline_shapes:
        shapes = writable_shapes(spec.agent)
        if shapes:
            system += SHAPE_ADDENDUM.format(
                shapes=json.dumps(shapes, indent=2)[:12000]
            )
    system += reference_addendum(references, node)
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
        # THE DESIGN LANGUAGE GOES IN THE CACHED PREFIX, NOT THE PAGE BRIEF.
        #
        # `designSystem` is 15,923 characters — 66% of a brief — and byte-
        # identical for every page. It sat in the user message AFTER the page
        # id, so it could never be a cache prefix: measured over a 44-page
        # application, ~3,981 tokens re-sent 44 times, ~175,000 input tokens a
        # run, at full price. The system prompt is already cache-tagged and
        # already carries the component catalog, and the design language is the
        # same kind of thing — the vocabulary a page is composed in, not a fact
        # about which page it is.
        #
        # `_cacheable` keys on content, so the first page in the wave writes
        # this prefix and the other forty-three read it. Retries share it too:
        # feedback rides in the user message, which is where per-page content
        # belongs.
        design = brief.pop("designSystem", None)
        if design:
            system += (
                "\n\nTHE DESIGN LANGUAGE, decided once for this application "
                "and inherited by every page. Compose within it rather than "
                "restating or re-deciding it.\n\n```json\n"
                + json.dumps(design, indent=2, sort_keys=True)
                + "\n```"
            )
        user = (
            "Design this page in full. You are given the page's contract, the "
            "requirements it exists to satisfy, the entity behind it and the "
            "field roles already derived from that entity — use `derived` "
            "rather than reconstructing columns or form fields by eye, or use "
            "the placeholders and they will be filled in for you.\n\n"
            "An empty state carries its own call to action: put it in "
            "`EmptyState.action` as {label, navigate} or {label, workflow}, "
            "not as a Button beside it. A sibling button repeats the one in "
            "the page header and shows even when the list has rows — a "
            "generated page ended up with \"Add customer\" twice, once at the "
            "top and once under a populated table.\n\n"
            "Author the states the contract declares — empty and error — as "
            "siblings; they are gated for you, so exactly one renders. Do not "
            "author a loading or skeleton state: data resolves on the server "
            "before the page renders, so nothing is ever in flight and a "
            "spinner would sit under a table that had already loaded.\n\n"
            "A page that lists records may carry one search box: an `Input` "
            "with `type: \"search\"` (its `name` is `q`); it searches the "
            "page's list source, and needs one. A Select whose options come "
            "from a related entity may depend on a sibling Select through "
            "`optionsFrom.dependsOn`; the relationship between their entities "
            "decides, and the dependency is wired for you from it.\n\n"
            "A workflow with `field` inputs is run from a Form whose `fields` "
            "collect them, with the Button as that Form's submit; a workflow "
            "with a `record` input is run from that record's detail page, or "
            "as a row action of a Table (or a control inside a Repeat) over "
            "that entity. A field whose value the control itself decides — an "
            "Approve button is the `decision` — is passed as a constant in the "
            "action's `args` (`\"args\": {\"decision\": \"APPROVED\"}`) instead "
            "of a Form. A Button elsewhere is refused.\n\n"
            "A control that runs a workflow names it by id from `workflows` "
            "below — `FLOW-007`, never its title, never a name you infer "
            "from the page, never a template. If no listed workflow does what "
            "the control needs, the control navigates instead or is left "
            "out; there is no workflow this application runs that is not in "
            "that list.\n\n"
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

    if node == "workflows":
        # The catalog is pulled in for the one task that authors workflows,
        # and for no other: the page agents get the component catalog, this
        # one gets the node catalog. Neither pays for the other's vocabulary.
        from services.catalog import workflow_nodes

        system += WORKFLOW_CATALOG_ADDENDUM.format(catalog=workflow_nodes().digest())
        # THE PAGES THAT HAVE NOWHERE TO SUBMIT, named. This agent already
        # reads `pages` (§101) and authored thirty-five good workflows without
        # noticing that eleven create pages had nothing to call: it was asked
        # for the processes the requirements describe, and it delivered them.
        # Nothing asked whether the pages that exist can do anything.
        #
        # Slots for the same reason `page_contracts` gets them — a sentence
        # saying "cover the create pages" competes with the rest of the
        # prompt, and a list of the specific routes does not.
        from services.blueprint.workflow_slots import (
            workflow_slot_prompt, workflow_slots,
        )

        slots = workflow_slots(doc)
        user = (
            "Here is the Blueprint.\n\n```json\n"
            + json.dumps(context_for(doc, spec.agent), indent=2, sort_keys=True)
            + "\n```"
        )
        if slots:
            user += (
                "\n\n" + workflow_slot_prompt(doc) + "\n\n```json\n"
                + json.dumps(slots, indent=2, ensure_ascii=False) + "\n```"
            )
        if feedback:
            user += "\n\nYour previous attempt was rejected:\n\n" + feedback
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
        # NAME THE FRAME A PAGE IS. `pages[].figmaFrame` has been in the
        # contract and in this agent's writable shape from the beginning and
        # was never once set — `designSources` sat outside what this agent
        # could read, so it was being asked for a node id it had never been
        # shown. With the frames in context the mapping is a judgement it can
        # make and a person can correct, which is what §49 asks for.
        #
        # It decides the composer downstream: a page naming a frame is built
        # from the design pixel-for-pixel, a page naming none is composed by
        # A2UI. A wrong id here is a screen built from the wrong picture, so
        # "leave it out" has to stay the easy and honest answer.
        from services.blueprint.page_planner import specification_frames

        if specification_frames(doc):
            # The slot prompt already says one page per frame and carries each
            # `nodeId`; this is the consequence spelled out, because under a
            # specification a page without one is a screen nobody drew.
            user += (
                "\n\nEVERY page you author must carry `figmaFrame`, set to the "
                "`nodeId` of the slot it answers. A page without one is a screen "
                "nobody drew, and this design is the specification."
            )
        elif doc.get("designSources"):
            # The frames arrive as slots now rather than as a list to be
            # matched against. Asking this agent to NOTICE that one of thirty
            # invented pages happened to be a screen somebody drew was the
            # discretionary step: nothing required it to notice, and a drawn
            # screen quietly composed from components looks exactly like a
            # page nobody drew. A slot carrying its own `nodeId` is answered
            # or it is missing, and missing is visible.
            user += (
                "\n\nA DESIGN IS CONNECTED AS A REFERENCE. Its frames are the "
                "first slots above, each carrying the `figmaFrame` it must be "
                "built from. Every page answering one of those slots must "
                "carry that `nodeId` \u2014 it is how the screen is built from "
                "the drawing rather than composed from components, and it is "
                "the part of this application somebody actually drew.\n\n"
                "Pages answering the entity features OMIT `figmaFrame` "
                "entirely. Those are composed, which is the good outcome and "
                "not a failure \u2014 the design does not show them. Never guess "
                "an id, and never give one frame to two pages."
            )
        if feedback:
            user += "\n\nYour previous attempt was rejected:\n\n" + feedback
        return system, user

    if inline_schema:
        system += SCHEMA_ADDENDUM.format(
            schema=json.dumps(PROPOSAL_SCHEMA, indent=2)
        )
    if spec.agent == "figma_intelligence" and subject:
        # §48 — the design is evidence, and the brief is where that bound is
        # set. The agent sees the screens' vocabulary and the extraction's
        # gaps; it does not see the generated TSX, which is layout noise that
        # would crowd out the labels that actually carry meaning.
        from services.figma.brief import brief_for

        user = (
            "A user connected this Figma design as the visual reference for "
            "the application being built. Propose the requirements it is "
            "evidence for.\n\n"
            "Every requirement must cite the frame it came from, in "
            "`evidence`, as "
            '`{"type": "figma", "source": "<source>", "node": "<nodeId>"}`.\n\n'
            "State only what the design shows. A screen proves that a "
            "capability is reachable; it does not tell you who may use it, "
            "what conditions govern it, what it writes, or what happens when "
            "it is refused. Where the design implies something without "
            "showing it, propose it at the confidence you actually have — the "
            "listed gaps are questions the user will be asked, not holes for "
            "you to fill.\n\n"
            "```json\n"
            + json.dumps(brief_for(doc, subject, output_dir), indent=2, sort_keys=True)
            + "\n```"
        )
        if feedback:
            user += f"\n\nYour previous attempt was rejected:\n\n{feedback}"
        return system, user

    user = (
        "Here is the Blueprint as it stands. Propose the artifacts your stage "
        "owns.\n\n```json\n"
        + json.dumps(context_for(doc, spec.agent), indent=2, sort_keys=True)
        + "\n```"
    )
    # EVERY BRANCH ABOVE CARRIES THE REJECTION; THIS ONE DROPPED IT. The
    # specialised branches return early having appended `feedback`, so the
    # nodes with no branch of their own — data_model, business_rules, apis,
    # security, requirements — retried with a byte-identical prompt and failed
    # the same way twice. `orchestrator._run_one` already says why that is
    # useless: "a retry that is not told what went wrong is just the same
    # request again."
    #
    # It costs a node. `references` carries `pattern: ^ENTITY-\d{3,}$`, but
    # structured-output decoding constrains types, enums, `required` and
    # `additionalProperties` — NOT regex. A pattern is advice the model
    # usually follows and occasionally does not, and one `references: ""`
    # fails the whole contract. Told what was rejected, the author fixes its
    # own field; told nothing, it re-emits it.
    if spec.agent == "solution_architecture":
        # THE DESIGN DRAWS THE NAVIGATION. Its sidebar is the same subtree on
        # every screen, and `store.connect` records what it says. This agent
        # is the one author of `navigation.tree`, and it could not see a
        # design at all — so every Figma application got the generic rail with
        # the drawn one rendered inside each page. §48: the design decides what
        # exists; this agent decides how it is reached — and reproduces it.
        #
        # PLACED AFTER THE GENERIC PROMPT IS BUILT. It first sat among the
        # per-agent hooks above, where `user` does not exist yet, and raised
        # UnboundLocalError on every ux_architecture call — the one run that
        # was meant to prove the design's rail could become the shell.
        from services.figma.chrome import describe as _describe_chrome
        from services.figma.chrome import describe_drawn as _describe_drawn

        drawn = [(src.get("id"), src.get("chrome"))
                 for src in doc.get("designSources") or [] if src.get("chrome")]

        def _rail_text(chrome: dict) -> str:
            side = chrome.get("sidebar") or {}
            if side.get("drawn"):
                # THE RAIL AS DRAWN, FOR THE ARCHITECT TO READ. Entry by entry
                # with what each carries; which is the brand, which a status
                # card, which a heading and which a destination is this
                # agent's reading, not a threshold's.
                return (_describe_drawn(side["drawn"])
                        + "\n\nRead it: the brand is the entry at the top that names "
                          "the product (a logo beside a name); a filled block of "
                          "dates or states is status, not navigation; a short "
                          "unactioned label introducing a run of entries is a group "
                          "heading; an entry drawn as icon + label is a destination, and what "
                          "is written underneath it — a caption, a badge count — belongs "
                          "to that entry and is never a heading. Say nothing about "
                          "entries you leave out; do not invent any.")
            return _describe_chrome(side)

        if drawn:
            user += (
                "\n\nA CONNECTED DESIGN DRAWS THE NAVIGATION. Its sidebar is "
                "identical on every screen, and this is what it draws, in the "
                "order the designer drew it:\n\n"
                + "\n\n".join(f"[{sid}]\n" + _rail_text(chrome) for sid, chrome in drawn)
                + "\n\nREPRODUCE IT. `navigation.style` is `sidebar`. "
                "`navigation.tree` has one node per group heading, in that "
                "order, with the group's destinations as its `children`, each "
                "bound to the page whose route it names — use the `pages` "
                "above. Do not add destinations the design does not draw, and "
                "do not drop the ones it does; a drawn destination with no "
                "matching page is still a node, without a `page`, so its "
                "absence is visible rather than silent."
            )

    if feedback:
        user += "\n\nYour previous attempt was rejected:\n\n" + feedback
    return system, user


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

#: What `data_model` replies with instead of proposals.
#:
#: Every other agent answers in the §29 envelope, where `body` is the artifact
#: encoded as a JSON STRING — so every quote inside every field is escaped and
#: `{"name":"x"}` travels as `"{\"name\":\"x\"}"`. Measured on a real
#: 21-entity model: 47,715 characters as envelopes against 17,301 in the shape
#: below, losing nothing. The Palestinian Legislative Council reply truncated
#: at 45,183 — a 21-entity model already exceeds the ceiling as envelopes, and
#: that domain needs about thirty. It was never going to fit, at any effort.
#:
#: The envelope is how an artifact is STORED and identified. There is no reason
#: the model should spend tokens writing one, so this node states entities and
#: `expand_data_model` builds the proposals in code — the same proposals, so
#: everything downstream is untouched.
#:
#: Taken from the legacy pipeline's planner, which emitted
#: `entities: {Name: {fields: {...}}}` and never met this wall.
DATA_MODEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entities", "confidence", "assumptions", "issues",
                 "change_requests"],
    "properties": {
        # A LIST, not a map keyed by name. Structured outputs reject
        # `additionalProperties: true`, so an open-keyed object is not
        # expressible: `output_config.format.schema: For 'object' type,
        # 'additionalProperties: true' is not supported`. Almost none of the
        # saving was in the keying anyway — it is the per-entity envelope and
        # the JSON-in-JSON escaping. Measured on the same 21-entity model:
        # 47,715 chars as envelopes, 20,223 here.
        # MIRRORS THE CONTRACT, key for key. The first version invented a
        # shape — `label` on a field, `constraints` on an entity, no `table` —
        # and `data.entities` is `additionalProperties: false` with `table`
        # required, so every proposal was rejected on apply. The node reported
        # done, the section stayed empty, and the run ended at 5/18 with
        # nothing written and no error. A reply schema that does not match the
        # contract it feeds is the same defect as a reader pointed one
        # directory from its writer.
        "entities": {
            "type": "array",
            "description": (
                "Every entity the application stores. `name` IS its identity "
                "across runs, so use the terminology verbatim — two modules "
                "naming the same entity update one record, and a near-miss "
                "spelling is what creates a duplicate."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "table", "fields"],
                "properties": {
                    "name": {"type": "string",
                             "description": "PascalCase singular — Member."},
                    "table": {"type": "string",
                              "description": "snake_case plural — members."},
                    "description": {"type": "string"},
                    "labelField": {
                        "type": "string",
                        "description": (
                            "The field a human reads to tell one record from "
                            "another. Names a field below."
                        ),
                    },
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "type"],
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "description": {"type": "string"},
                                "required": {"type": "boolean"},
                                "primaryKey": {"type": "boolean"},
                                "unique": {"type": "boolean"},
                                "sensitive": {
                                    "type": "boolean",
                                    "description": (
                                        "Personal or financial. Downstream "
                                        "agents cannot see this section to "
                                        "second-guess it."
                                    ),
                                },
                                "enumValues": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
        # THE CHANNELS ITS CAPABILITY ALREADY GRANTED. `data_model` may write
        # data.entities, data.relationships, data.constraints and database;
        # this schema carried `entities` alone, so three of its four sections
        # had nowhere to go. The agent said so itself, twice, in its own
        # change_requests: "Response schema for this agent has no channel for
        # relationship artifacts; needs to be addable before foreign keys such
        # as StockMovement->Item ... can be declared with cardinality."
        #
        # It is not a small loss. Without relationships the projection has no
        # foreign keys to emit, and an agent that knows it cannot express what
        # it owns reports low confidence for it — which is how an EMR build
        # came to block at 0.10 on a model it was perfectly able to describe.
        #
        # BY NAME, NOT BY ID. `DATA_MODEL_REPLY_RULES` forbids inventing ids
        # and the contract types these as `^ENTITY-\d{3,}$`, so the reply cites
        # the entity's name and `resolve_batch_references` closes the gap at
        # commit time — the same route every other agent's cross-references
        # take.
        "relationships": {
            "type": "array",
            "default": [],
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from", "to", "kind"],
                "properties": {
                    "from": {"type": "string",
                             "description": "The NAME of the owning entity, as spelled in `entities`."},
                    "to": {"type": "string",
                           "description": "The NAME of the referenced entity."},
                    "kind": {"type": "string",
                             "enum": ["one_to_one", "one_to_many", "many_to_many"]},
                    "fromField": {"type": "string"},
                    "toField": {"type": "string"},
                    "onDelete": {"type": "string",
                                 "enum": ["cascade", "restrict", "set_null"]},
                },
            },
        },
        "constraints": {
            "type": "array",
            "default": [],
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["entity", "kind", "expression"],
                "properties": {
                    "entity": {"type": "string",
                               "description": "The NAME of the entity this constrains."},
                    "kind": {"type": "string",
                             "enum": ["check", "unique", "index", "foreign_key"]},
                    "expression": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "confidence": {"type": "number"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": {"type": "string"}},
        "change_requests": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "reason"],
                "properties": {"section": {"type": "string"},
                               "reason": {"type": "string"}},
            },
        },
    },
}

#: The reply shape each node is held to. Absent means the §29 envelope.
SCHEMA_BY_NODE: dict[str, dict[str, Any]] = {"data_model": DATA_MODEL_SCHEMA}


def expand_data_model(data: dict) -> list["ArtifactProposal"]:
    """The compact `entities` object as the proposals the pipeline expects.

    Rebuilds exactly what the model used to write by hand, so `svc.upsert`,
    the allocator, `natural_key` identity and re-run idempotency all see what
    they see today. A field given as a bare string is its type.
    """
    out: list[ArtifactProposal] = []
    for spec in (data.get("entities") or []):
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "").strip()
        if not name:
            continue
        body = {k: v for k, v in spec.items() if v not in (None, [], "")}
        body["name"] = name
        body["fields"] = [f for f in (spec.get("fields") or [])
                          if isinstance(f, dict) and f.get("name")]
        out.append(ArtifactProposal(
            section="data.entities", natural_key=name, body=body,
        ))

    # A CHANNEL NOBODY DRAINS IS STILL NO CHANNEL. Accepting `relationships`
    # and `constraints` in the reply schema without expanding them here would
    # let the agent state the foreign keys and then drop them silently — the
    # exact shape of failure this pair of changes exists to end.
    #
    # `from`/`to`/`entity` carry entity NAMES; `resolve_batch_references`
    # turns them into the ENTITY ids the contract requires, at commit, in the
    # same pass that allocates the entities themselves. That ordering is why
    # the agent can reference an entity it is proposing in the same reply.
    for rel in (data.get("relationships") or []):
        if not isinstance(rel, dict):
            continue
        src, dst = str(rel.get("from") or "").strip(), str(rel.get("to") or "").strip()
        if not (src and dst):
            continue
        body = {k: v for k, v in rel.items() if v not in (None, "", [])}
        out.append(ArtifactProposal(
            section="data.relationships",
            natural_key=f"{src}->{dst}:{rel.get('kind') or ''}",
            body=body,
        ))

    for con in (data.get("constraints") or []):
        if not isinstance(con, dict):
            continue
        entity = str(con.get("entity") or "").strip()
        expression = str(con.get("expression") or "").strip()
        if not (entity and expression):
            continue
        body = {k: v for k, v in con.items() if v not in (None, "", [])}
        out.append(ArtifactProposal(
            section="data.constraints",
            natural_key=f"{entity}:{con.get('kind') or ''}:{expression}",
            body=body,
        ))
    return out


class MalformedEnvelope(ValueError):
    """The model's reply did not parse as the §29 envelope."""


def parse_envelope(raw: str, *, task_id: str, agent: str,
                   node: str = "") -> AgentResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedEnvelope(f"reply was not JSON: {exc}") from exc

    proposals: list[ArtifactProposal] = []
    if node in SCHEMA_BY_NODE and node == "data_model":
        proposals = expand_data_model(data)
        if not proposals:
            # A reply that parsed but named nothing is not a data model. Said
            # here rather than committed as an empty section, which is how a
            # missing `data.entities` looked like a stall for three runs.
            raise MalformedEnvelope("data_model: reply declared no entities")
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
    # Tables, columns and indexes over a data model that is already decided —
    # the entity IS the table, and `data_model` did the thinking. Measured at
    # 224s a call at `high`, against 65s for ux_architecture and 102s for
    # design_system, both of which were tuned when they were written.
    #
    # `security`, `workflows` and `business_rules` are NOT tuned with it, and
    # deliberately: test_effort_is_tiered_per_node_and_the_load_bearing_nodes_
    # stay_high protects them because everything downstream derives from what
    # they decide. That objection was right about `data_model` too — the fix
    # there was the reply's shape, not its reasoning.
    "database": "medium",
    # Tests are enumerated from what the Blueprint already claims, not invented.
    "testing": "medium",
    # A short list of named third parties.
    "integrations": "low",
}


#: Nodes that have been MEASURED at the ceiling, and what to give them.
#:
#: `max_tokens` caps thinking and answer together, so a node can truncate
#: without its answer being large — `data_model` emits ~10,400 tokens of JSON
#: after ~18,600 of reasoning. Truncation is the expensive failure: the reply
#: stops mid-JSON, fails to parse, burns a repair attempt, and on a fanning
#: node costs a page. Unused headroom is free; a truncated reply is not.
#:
#: From data/build-usage.jsonl, output tokens per call over one night:
#:
#:     data_model       32,000 reached 16 times   (mostly pre-compact-reply)
#:     page_contracts   32,000 reached  1 time
#:     database         32,000 reached  1 time
#:     security         32,000 reached  1 time
#:     workflows        32,000 reached  1 time
#:
#: Everything else peaked at 65% or below and is left alone: a ceiling nobody
#: approaches is not insurance, it is just a bigger number to be wrong about.
#:
#: 64000 is the value `__post_init__` already uses for xhigh/max effort, so
#: this is the established headroom rather than a new one. These nodes are
#: above STREAM_ABOVE either way, so they were already streaming.
MAX_TOKENS_BY_NODE: dict[str, int] = {
    "data_model": 64000,
    "page_contracts": 64000,
    "database": 64000,
    "security": 64000,
    "workflows": 64000,
}


def tiered_router(
    default_effort: str = "high", model: str = DEFAULT_MODEL,
    *, reasoning: Any = None,
) -> "ModelRouter":
    """A router that varies effort per node and nothing else.

    Same model everywhere: this isolates the effort question, so a regression
    can be attributed to thinking budget rather than to a model swap.
    """
    tuned = set(EFFORT_BY_NODE) | set(MAX_TOKENS_BY_NODE)
    return ModelRouter(
        default=AnthropicModel(model=model, effort=default_effort,
                               reasoning=reasoning),
        by_node={
            node: AnthropicModel(
                model=model,
                effort=EFFORT_BY_NODE.get(node, default_effort),
                max_tokens=MAX_TOKENS_BY_NODE.get(node, DEFAULT_MAX_TOKENS),
                reasoning=reasoning,
            )
            for node in tuned
        },
    )


def _as_template(node: Any) -> Any:
    """An A2UI tree as a TemplateNode — which carries no ids.

    TemplateNode is type, props, children, repeat, visibleIf, and strict. A
    template has no identity of its own: `plan_page` calls `assign_node_ids`
    after instantiating it, so ids arriving here would be overwritten anyway.
    Fifteen of them arrived and the whole artifact was rejected.

    A2UI's ids are composition-time references — how it points at a child —
    and `translate` has already resolved them into a nested tree by the time
    this runs. They have done their work. Dropped here rather than in
    `translate`, which also feeds the path that writes schema files directly,
    where a node id becomes a React key.
    """
    if isinstance(node, list):
        return [_as_template(n) for n in node]
    if not isinstance(node, dict):
        return node
    # Only a node's own id, and a node is what has a `type`. Recursing blindly
    # also stripped `props.id`, where `id` is an ordinary prop value — a Table
    # keyed by a column called id would have lost it.
    if "type" not in node:
        return node
    return {k: (_as_template(v) if k == "children" else v)
            for k, v in node.items() if k != "id"}


def make_executor(
    svc: BlueprintService,
    model: ModelClient | ModelRouter,
    *,
    repair_attempts: int = 1,
    usage: RunUsage | None = None,
    reasoning: Any = None,
) -> Callable[[TaskSpec], AgentResult]:
    """Build the callable :func:`services.blueprint.orchestrator.run` expects.

    ``repair_attempts`` retries a malformed envelope with the parser's own error
    appended to the prompt. This is pre-commit repair: nothing has been written
    to the Blueprint, so a rejected proposal simply never becomes an artifact.

    ``reasoning`` is where the work reports itself while it happens. It reaches
    A2UI here as well as the model clients on the router: for a page A2UI owns,
    no model call of ours is made at all, so the router's sink would leave the
    longest stretch of a compose turn silent.
    """

    def _compose_via_a2ui(spec: TaskSpec) -> AgentResult | None:
        """§34 — A2UI composes the page; the agent is what runs if it declines.

        Returns None rather than raising when A2UI does not own this page, so
        the caller falls through to the authoring agent. An unreachable server
        must cost the composition, never the page: this node fans out 34 times
        on a real app, and a run that finished 28 of 32 pages is the reason
        per-subject tolerance exists.
        """
        from services.a2ui_authority import (
            compose_page_via_a2ui, registry_from_blueprint,
        )
        from services.a2ui_ui_composition import shared_context

        page = next((p for p in svc.doc.get("pages") or []
                     if p.get("id") == spec.subject), None)
        if not page or not page.get("route"):
            return None

        # THE PAGE THAT WAS DRAWN IS THE THING THAT WAS DRAWN. A page carrying
        # `figmaFrame` is built from that frame's design context; a page
        # carrying none falls straight through to A2UI below. Both produce a
        # tree of the same catalog components into the same `pageLayouts`
        # section, so nothing downstream needs to know which happened — the
        # projection, the floors and the funnel all read one shape.
        #
        # Deliberately mixed: a design of eight screens against a data model
        # implying thirty pages should ship thirty pages, eight of them
        # pixel-accurate. Falling through is the normal case, not a failure.
        from services.blueprint import figma_layout
        from services.llm_client import tell

        # THE APP ROOT, NOT THE PROJECT ROOT. Assets are written to
        # `<root>/public/figma/` and the generated app serves `public/` from
        # `<project>/app`, so passing the project directory put every SVG one
        # level above the tree that references them.
        drawn = None
        try:
            drawn = figma_layout.compose(
                svc, page, app_root=Path(svc.output_dir) / "app")
        except Exception as exc:  # noqa: BLE001 — a design must never cost the page
            # THIS BRANCH SAT OUTSIDE THE TRY BELOW AND A NameError FROM IT
            # KILLED THE SUBJECT OUTRIGHT: the page was not composed by Figma,
            # was never offered to A2UI, and vanished from `pageLayouts`
            # entirely. Falling through is the whole contract of this seam.
            logger.warning("[figma] %s: %s", spec.subject, exc)
        if drawn is not None:
            tell(reasoning, f"Building {page.get('route')} from its Figma frame.",
                 "step", spec.node)
            return AgentResult(
                task_id=spec.task_id,
                agent=spec.agent,
                proposals=[ArtifactProposal(
                    section="pageLayouts",
                    natural_key=spec.subject,
                    body={"page": spec.subject,
                          "root": _as_template(drawn["root"]),
                          "composedBy": "figma",
                          "dataSources": drawn["dataSources"],
                          # THE FRAME'S SIZE TRAVELS WITH THE TREE. `compose`
                          # returns it and `FigmaCanvas` scales by it, but
                          # nothing between them carried it: a projected app
                          # had no `_figmaCanvas`, so a 3902px frame rendered
                          # cropped instead of scaled. Absent for a frame with
                          # no recorded size, which composes flowed anyway.
                          **({"canvas": drawn["canvas"]} if drawn.get("canvas") else {}),
                          "rationale": (
                              f"built from Figma frame "
                              f"{page.get('figmaFrame')} (§48)"),
                          "requirements": list(page.get("requirements") or [])},
                )],
                confidence=0.95,
            )
        try:
            out = compose_page_via_a2ui(
                svc.output_dir, page["route"], page.get("pattern") or "",
                shared_context=shared_context(svc.doc),
                page_id=spec.subject,
                registry=registry_from_blueprint(svc.doc),
                presentation=page.get("presentation") or "page",
                progress=reasoning,
                # The retry's whole point. `spec.feedback` carries the
                # validator's message from the attempt that was refused, and
                # this path re-composed with A2UI before the authoring agent
                # could read it — so on a page A2UI owns, the correction
                # reached nobody.
                feedback=spec.feedback or "",
            )
        except Exception as exc:  # noqa: BLE001 — composition, never the build
            logger.warning("[a2ui] %s: %s", spec.subject, exc)
            return None
        if not out.get("applied") or not out.get("root"):
            reason = str(out.get("reason") or "").strip()
            logger.info("[a2ui] %s declined (%s) — authoring agent runs",
                        spec.subject, reason)
            # THE NEXT AUTHOR SHOULD KNOW WHY THE LAST ONE WAS REFUSED. This
            # reason was logged and dropped, so the LLM page author picked the
            # page up with no idea what the floor had just rejected and was
            # free to walk into the same wall. `feedback` exists for exactly
            # this — its own comment says a retry told nothing reproduces the
            # identical mistake — and nothing was filling it here.
            if reason:
                spec.feedback = (
                    f"{spec.feedback}\n\n" if spec.feedback else ""
                ) + (
                    f"A2UI composed this page and it was refused: {reason}. "
                    f"Compose it yourself, and do not reproduce that fault."
                )
            return None
        return AgentResult(
            task_id=spec.task_id,
            agent=spec.agent,
            proposals=[ArtifactProposal(
                section="pageLayouts",
                natural_key=spec.subject,
                body={"page": spec.subject, "root": _as_template(out["root"]),
                      # WHO DESIGNED THIS SCREEN. A2UI and the LLM page author
                      # emit the same shape, so a page composed well and a page
                      # nobody could compose properly were indistinguishable in
                      # the Blueprint — answerable only from run logs, which
                      # age out. Recorded where it is known rather than
                      # inferred later from what a tree looks like.
                      "composedBy": "a2ui",
                      # CARRIED, NOT RE-DERIVED. The binder rewrote every
                      # pointer into a {{name}} and emitted the source behind
                      # it in the same pass; it is the only place the tree and
                      # its fetches are known together. Dropping them here made
                      # the projection rebuild the set by matching binding
                      # names against entity names, which silently discarded
                      # six of seven on a real page — four aggregate counts and
                      # two extra lists — and shipped the tree that read them.
                      "dataSources": list(out.get("schema", {})
                                          .get("dataSources") or []),
                      "rationale": "composed by A2UI (§34)",
                      "requirements": list(page.get("requirements") or [])},
            )],
            confidence=0.95,
        )

    def executor(spec: TaskSpec) -> AgentResult:
        if spec.agent == "a2ui_pages" and spec.subject:
            composed = _compose_via_a2ui(spec)
            if composed is not None:
                return composed
        client = (
            model.for_task(spec.node, spec.agent)
            if isinstance(model, ModelRouter)
            else model
        )
        # §5 — an application can be described by showing as well as by
        # telling. Resolved per call rather than threaded through `run`,
        # because the references belong to the application and `svc` is the
        # application: nothing between here and the orchestrator has to learn
        # about images for one to arrive.
        shown = (
            references.paths(svc.output_dir)
            if spec.node in references.SEES_REFERENCES
            and getattr(client, "accepts_images", False)
            else []
        )
        system, user = build_prompt(
            svc.doc, spec.node,
            inline_schema=not getattr(client, "enforces_schema", True),
            subject=spec.subject, feedback=spec.feedback, references=shown,
            output_dir=svc.output_dir,
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
            reply_schema = SCHEMA_BY_NODE.get(spec.node, PROPOSAL_SCHEMA)
            raw = (
                client(system=system, user=prompt, schema=reply_schema,
                       images=shown)
                if shown else
                client(system=system, user=prompt, schema=reply_schema)
            )
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
                return parse_envelope(text, task_id=spec.task_id,
                                      agent=spec.agent, node=spec.node)
            except MalformedEnvelope as exc:
                last = exc

        raise MalformedEnvelope(f"{spec.node}: {last}")

    return executor

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
import os
import re
import threading
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
from services.blueprint.verification import PALETTE_ROLES
from services.blueprint.service import ARTIFACT_SECTIONS, BlueprintService

logger = logging.getLogger(__name__)

#: WHO RUNS ON WHAT — two decisions, not one (user's call, 2026-09-10).
#:
#: The §27 specialists and the observer run on Sonnet 5: each fills a tightly
#: constrained shape from a slice of the Blueprint, the observer only reads and
#: judges, and Sonnet 5 is $2/$10 against Opus 5's $5/$25. Smith stays on
#: Opus 5: it interprets the user's words into the product definition, and
#: everything the specialists do elaborates what it decided — a misread there
#: is the expensive mistake, not a page composed twice.
#:
#: Both are read once, at import, from the environment, so a run can be
#: pointed elsewhere without a code change — `FORGE_AGENT_MODEL` for the
#: specialists and the observer, `FORGE_SMITH_MODEL` for Smith. Any current
#: model id works with the request shape `AnthropicModel` sends; pre-4.6 ids
#: reject `output_config.effort` with a 400.
#:
#: The per-node effort and max_tokens tables below were measured on Opus 5.
#: Sonnet 5 uses a new tokenizer (roughly 30% more tokens for the same text)
#: and adaptive thinking counts against `max_tokens` the same way, so the
#: knees may sit elsewhere — the scoreboard is how to find out, not a guess.
#: Note this deliberately differs from `services.llm_client`'s
#: FORGE_ONESHOT_MODEL default, which is still pinned to an older Sonnet.
AGENT_MODEL = os.environ.get("FORGE_AGENT_MODEL", "").strip() or "claude-sonnet-5"
SMITH_MODEL = os.environ.get("FORGE_SMITH_MODEL", "").strip() or "claude-opus-5"

#: What `AnthropicModel()` and `tiered_router()` run on when not told: the
#: specialists' model. Kept under its old name because the router, the
#: office and the tests all read it.
DEFAULT_MODEL = AGENT_MODEL

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
    #: Why the model stopped — `end_turn`, `max_tokens`, … A reply cut off at
    #: the output cap is not a malformed reply, and a reader that cannot tell
    #: the two apart reports "was not JSON" for a plan that was simply longer
    #: than the budget. None when the transport does not say.
    stop_reason: str | None = None


class ModelRefused(RuntimeError):
    """The model declined the request (§ `stop_reason: "refusal"`)."""


class NoAnswer(RuntimeError):
    """The model stopped without writing any answer at all.

    MEASURED ON UAT, and reported there as `StopIteration: ` — an empty
    message on a failed node, twice, with every node after it skipped.
    `page_contracts` for a 23-entity application spent its whole output budget
    reasoning and returned a message holding thinking and no text block, and
    `next(b.text for b in ...)` raised on the empty generator. The run said
    nothing a person could act on, and the retry asked the same question with
    the same budget and got the same nothing.

    Carries the usage so the spend is still recorded: a call that consumed
    32,000 output tokens is the most expensive kind to lose track of.
    """

    def __init__(self, message: str, usage: "Usage | None" = None,
                 stop_reason: str | None = None) -> None:
        super().__init__(message)
        self.usage = usage
        self.stop_reason = stop_reason


class BuildCannotStart(RuntimeError):
    """The API refused a one-token call before the build spent anything."""


#: The message the API gives an account with no balance. A 400, so it does
#: not carry a class of its own in the SDK.
_NO_CREDIT = ("credit balance", "billing", "purchase credits")


def api_outage(exc: BaseException) -> str | None:
    """What kind of API outage an exception is, or None when it is not one.

    ``"credit"`` — the account cannot pay (no balance, a bad or revoked key):
    nothing will succeed until a person acts, and every call made meanwhile
    is a call that fails. ``"transient"`` — the API is busy or the network
    dropped (429, 5xx, 529, a timeout): the same call a little later is
    likely to land. Neither says anything about what the author wrote, and
    neither is worth an attempt: HippieKit's second measured rebuild
    (2026-09-22) FAILED a page for "Your credit balance is too low", and a
    build that hits that mid-run used to fail one subject per remaining call.
    Read from the SDK's exception classes where they exist, and from the
    message where they do not (a 400 is a 400)."""
    text = str(exc).lower()
    if any(word in text for word in _NO_CREDIT):
        return "credit"
    try:
        import anthropic
    except ImportError:  # pragma: no cover — the SDK is a dependency
        anthropic = None  # type: ignore[assignment]
    if anthropic is not None:
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return "credit"
        if isinstance(exc, (anthropic.RateLimitError, anthropic.InternalServerError,
                            anthropic.APIConnectionError)):
            return "transient"
        if isinstance(exc, anthropic.APIStatusError) and int(getattr(exc, "status_code", 0) or 0) >= 500:
            return "transient"
    # Without a class to go on, only the API's own message shape counts —
    # "Error code: 529 - {...}" — never a free word like "timeout", which a
    # composer, a gateway or a test fake may say for reasons of their own.
    if re.search(r"error code: (429|5\d\d)\b", text):
        return "transient"
    return None


def preflight(client: Any) -> None:
    """One token's worth of proof that the API will answer. Raises
    :class:`BuildCannotStart` for an account that cannot pay; a busy API is
    let through. A client with no ``preflight`` of its own is trusted.

    NOT CALLED BY THE RUN ITSELF. A run's first model call is its preflight:
    a request the API refuses for a low balance is not billed, and the
    scheduler pauses the run on it with nothing sent since (see the
    orchestrator's `pause`). Wired into `run` it reached the real API from a
    test suite whose fakes never would have. For a caller that wants the
    answer before it starts anything — a UI about to show a progress bar —
    this is the call."""
    check = getattr(client, "preflight", None)
    if check is None:
        return
    try:
        check()
    except BuildCannotStart:
        raise
    except Exception as exc:  # noqa: BLE001 — classified, not swallowed
        if api_outage(exc) == "credit":
            raise BuildCannotStart(f"the API refused before the build began: {exc}") from exc
        # Transient, or something a 1-token call cannot tell: the build goes
        # ahead and each call speaks for itself.


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
            "description": (
                "§30 — what you return INSTEAD of reaching outside your own "
                "section. `section` names the section at fault "
                "(\"data.entities\", \"workflows\"), `reason` says why in "
                "one sentence.\n\n"
                "TO ASK FOR SOMETHING TO BE RETIRED, set `retire` to its id. "
                "That is acted on: the run retires it and every stage after "
                "you sees it gone. Asked to author the fields of a "
                "CalculatorSession on an application whose requirements say "
                "nothing is stored, this is how you say so — "
                "{section: \"data.entities\", reason: \"REQ-003 says nothing "
                "is stored; this models screen state as a table\", retire: "
                "\"ENTITY-001\"} — instead of authoring columns for a table "
                "that should not exist. Without the id it is recorded and "
                "read by a person, which is slower and often too late."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "reason"],
                "properties": {
                    "section": {"type": "string"},
                    "reason": {"type": "string"},
                    "retire": {
                        "type": "string",
                        "description": ("The id of the artifact that should not "
                                        "exist — ENTITY-001, FLOW-002, PAGE-003."),
                    },
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

#: Where a user message stops being the same for every subject of a fan-out.
#:
#: ONLY THE SYSTEM PROMPT WAS CACHED, AND IT WAS THE SMALL HALF. HippieKit's
#: measured build (2026-09-21) sent 3.2M input tokens at full price. page_details
#: alone sent 882k over 27 calls and read 63k back from the cache: every call
#: re-sent the same page set and Blueprint slice, AFTER the subject's own
#: pages, so no two calls shared a prefix past the system prompt. A fan-out
#: prompt now puts what every subject shares first and its own part after
#: this line; the client caches up to it. Plain text on purpose — a client that
#: does not cache reads a heading, not a token.
CACHE_BREAK = "\n\n## This call\n\n"


#: The event a fan-out's first call sets once its cached prefix is readable —
#: per worker thread, because the call it belongs to runs on one (see the
#: orchestrator's `_call_warm`).
_LEADING = threading.local()


class leading_prefix:
    """While a call runs, the event to set at its first streamed event."""

    def __init__(self, event: Any) -> None:
        self.event = event

    def __enter__(self) -> None:
        _LEADING.event = self.event

    def __exit__(self, *exc: Any) -> None:
        _LEADING.event = None


def _prefix_readable() -> None:
    """A cache entry can be read once the response writing it streams."""
    event = getattr(_LEADING, "event", None)
    if event is not None:
        event.set()


def _user_blocks(user: str) -> Any:
    """The user message, with what every subject shares cache-tagged when it
    is big enough to be worth a breakpoint (see :data:`CACHE_BREAK`)."""
    head, sep, tail = user.partition(CACHE_BREAK)
    if not sep or len(head) // 4 < CACHE_MIN_TOKENS:
        return user
    return [{"type": "text", "text": head, "cache_control": _CACHE_CONTROL},
            {"type": "text", "text": sep.lstrip("\n") + tail}]


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


def _content(shown: Sequence[str | Path], user: str) -> Any:
    """Images first (the stable half of the prefix), then the user text."""
    text = _user_blocks(user)
    if not shown:
        return text
    return [*image_blocks(shown), *(text if isinstance(text, list) else [{"type": "text", "text": text}])]


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

            # WHICH httpx THE SDK SPEAKS IS THE SDK'S CHOICE, NOT OURS. Newer
            # anthropic releases vendor `httpx2` and reject an `httpx.Timeout`
            # outright ("this SDK uses httpx2. Use httpx2.Timeout") — a rebuild
            # that pulls the newer SDK then fails EVERY agent node at construction
            # time, before a single token is requested.
            #
            # Asking "is httpx2 importable" was the wrong question: the package
            # outlives the SDK that pulled it in. This machine had anthropic
            # 0.125 (httpx) beside a leftover httpx2, so every call built an
            # httpx2.Timeout for an httpx client and died inside the SDK as a
            # bare APIConnectionError ("'Timeout' object cannot be interpreted
            # as an integer") — a network-shaped error for a type mismatch,
            # the same disguise the brotli bug wore. The SDK re-exports the
            # Timeout it speaks as `anthropic.Timeout` on 0.x and 1.x alike.
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
                timeout=anthropic.Timeout(connect=15.0, read=300.0,
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

    #: A reply that is still only thinking after this much of its budget is not
    #: going to write an answer. Measured: a Calculator's single page burned
    #: all 64,000 tokens reasoning at `high` (12m38s), then all 64,000 again at
    #: `medium` (23m36s in total) — two full budgets to learn the same thing
    #: twice. Stopping at the mark costs the same lesson at half the price,
    #: and the retry below gets going sooner.
    THINKING_ONLY_SHARE = 0.55

    def _drain(self, stream: Any) -> Any:
        """Consume the stream, forwarding thinking, and give up on a reply
        that is all reasoning before its budget is gone.

        Iterating consumes the same events `get_final_message` accumulates, so
        it is still the SDK's assembled message that comes back; nothing here
        rebuilds a reply out of deltas.
        """
        from services.llm_client import ReasoningSink

        sink = ReasoningSink(self.reasoning) if self.reasoning is not None else None
        ceiling = int(self.max_tokens * self.THINKING_ONLY_SHARE)
        thinking_chars, answered = 0, False
        try:
            for event in stream:
                _prefix_readable()
                kind = getattr(event, "type", "")
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", None)
                if dtype == "thinking_delta":
                    text = str(getattr(delta, "thinking", "") or "")
                    thinking_chars += len(text)
                    if sink is not None:
                        sink.feed(text)
                elif dtype == "text_delta" or (
                        kind == "content_block_start"
                        and getattr(getattr(event, "content_block", None), "type", "") == "text"):
                    answered = True
                # ~4 characters to the token is the rule of thumb everything
                # else here uses; it only has to be right to the nearest
                # thousand for this to be worth doing.
                if not answered and thinking_chars // 4 > ceiling:
                    raise NoAnswer(
                        f"the model was still reasoning after {thinking_chars // 4:,} of its "
                        f"{self.max_tokens:,} output tokens and had not begun an answer, so the "
                        f"call was stopped — this task needs less deliberation, not more budget",
                        stop_reason="thinking_only")
        finally:
            # The tail is usually the conclusion. Flushed even if the stream
            # raises, so a failed call still shows how far it got.
            if sink is not None:
                sink.close()
        return stream.get_final_message()

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
                _prefix_readable()
                delta = getattr(event, "delta", None)
                if getattr(delta, "type", None) == "thinking_delta":
                    sink.feed(str(getattr(delta, "thinking", "") or ""))
        finally:
            # The tail is usually the conclusion. Flushed even if the stream
            # raises, so a failed call still shows how far it got.
            sink.close()
        return stream.get_final_message()

    def preflight(self) -> None:
        """The cheapest call the API takes. Raises whatever it raises."""
        self._anthropic().messages.create(
            model=self.model, max_tokens=1,
            messages=[{"role": "user", "content": "ok"}])

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
            messages=[{"role": "user", "content": _content(shown, user)}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        client = self._anthropic()
        # EVERY CALL STREAMS. The SDK refuses a non-streaming request it
        # estimates could exceed ~10 minutes (any large max_tokens), and a
        # fan-out's followers wait for the leader's FIRST streamed event to
        # know its cached prefix is readable (`_prefix_readable`). A call made
        # with `create()` never sends that event, so a node under the old
        # threshold idled its followers for the whole wait bound. The
        # accumulated message is the same either way.
        with client.messages.stream(**kwargs) as stream:
            response = self._drain(stream)
        # Check before reading content: a refusal returns HTTP 200 with an
        # empty or partial content list, and indexing it blindly raises.
        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            raise ModelRefused(
                f"model declined this task"
                f"{f' ({detail.category})' if detail else ''}"
            )
        u = response.usage
        spent = Usage(
            model=self.model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        stop = getattr(response, "stop_reason", None)
        # NO TEXT IS AN OUTCOME WITH A NAME. A reply can hold only thinking —
        # the budget ran out before the answer began — and reading it with a
        # bare `next()` raised StopIteration, which surfaced on UAT as a
        # failed node whose reason was the empty string.
        text = next((b.text for b in response.content
                     if getattr(b, "type", None) == "text"), None)
        if text is None:
            if stop == "max_tokens":
                why = (f"the model spent all {spent.output_tokens:,} output tokens "
                       f"reasoning and wrote no answer — the budget "
                       f"({self.max_tokens:,}) is too small for this task")
            else:
                why = (f"the model stopped ({stop or 'no stop reason'}) without "
                       f"writing an answer")
            raise NoAnswer(why, usage=spent, stop_reason=stop)
        return ModelReply(text=text, usage=spent, stop_reason=stop)



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
            by_node={"business_rules": kimi},
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
        "scheme around it. NAME THE HARMONY you are using and keep to it: "
        "complementary (the accent opposite the primary), split-complementary "
        "(the accent one step either side of opposite), analogous (everything "
        "within 60° — calm, editorial, needs a strong accent to point with) or "
        "triadic. The accent is a true complement or a near-triad, never a "
        "second blue. Subtle and hover variants are the primary's own hue at "
        "another lightness. THE NEUTRALS ARE TINTED: the ground, the surface, "
        "the borders and the secondary text all carry a trace of the primary's "
        "hue (a few points of saturation), never pure grey — that is what makes "
        "a palette read as one thing. Weight it 60/30/10: the ground and "
        "surfaces carry the screen, the primary structures it, the accent is "
        "the ten percent that says where to act. Status colours stay "
        "distinguishable for the 8% of men with a red-green deficiency. Say in "
        "`visualPersonality` which of the three sources this came from, which "
        "harmony it is, and why, so a later change can argue with it.\n\n"
        "THE GROUND CAN BE DARK. A product that lives in the evening, in media, "
        "in a control room, or that wants drama, earns a dark ground with light "
        "ink (`background` deep and tinted, `surface` one step lighter, "
        "`inverse` then LIGHTER than the ground, not darker); a product read "
        "all day at a desk earns a light one. Decide it from the personality, "
        "not from habit, and keep every text pair readable either way.\n\n"
        "A GRADIENT IS PART OF THE PALETTE. Name `gradientStart` and "
        "`gradientEnd`: two stops of the primary's own family — the start is "
        "the primary's hue, the end the same hue turned 20-40° round the wheel "
        "(towards the warmer or cooler neighbour the personality wants), both "
        "deep enough that light text reads on either. It paints the sign-in "
        "panel, a hero band and the one leading card; it is never the accent, "
        "and never two unrelated colours.\n\n"
        "THE PICTURES. Name up to three photographs in `imagery`, one per job "
        "the product needs — `auth` (the sign-in page's brand panel: the "
        "world this product serves, not an office stock shot), `hero` (the "
        "band that leads a dashboard or home) and `empty` (an illustrated "
        "empty state) — each as a `query` a photo search would answer "
        "(\"neighbours sharing garden tools\", \"child receiving a vaccine, "
        "gentle\") and an `alt` a screen reader would say. Leave `url` empty: "
        "the platform finds and credits the picture, and where it cannot, the "
        "gradient stands in. A product that should carry no photography (a "
        "stark tool, a dense back-office) names none and says so.\n\n"
        "Decide from the domain and who uses it. A recruiter working a "
        "pipeline all day and a customer buying once a year want different "
        "densities and different levels of visual quiet. Say why each choice "
        "follows from the product, not from taste.\n\n"
        "EVERY COLOUR HAS A JOB, AND `colors` NAMES EACH ONE by these keys "
        "(add status colours and hover/subtle variants beside them):\n"
        + "\n".join(f"- `{role}`: {job}" for role, job in PALETTE_ROLES.items())
        + "\n"
        "Pages are written against these jobs, so a colour with no job is a "
        "colour no page uses: an accent named without a job was drawn three "
        "times in a whole application while every button stayed the primary. The "
        "accent is scarce on purpose — one element per screen — which is what "
        "makes it read as \"do this\". Choose it dark enough to carry the page's "
        "own light text on a button. The ground is a decision too: a warm "
        "paper, a cool slate, a soft sage — pure `#FFFFFF` only when the "
        "product is stark by intent, never because white is the default. "
        "When the personality you describe is warm, the neutrals are warm.\n\n"
        "THE FRAME IS A DECISION TOO. Name `shell.chrome` — how the navigation "
        "is built: `wide-rail` (a labelled sidebar, for a product with many "
        "destinations worked all day), `icon-rail` (a narrow rail of icons, for "
        "a focused tool), `standard-rail` (a rail that expands on hover), "
        "`floating-rail` (the rail as a raised card, for a lighter, editorial "
        "feel), `right-rail` (navigation after the content), `topbar` (a "
        "single bar across the top, for a few destinations or a consumer "
        "product), `dock` (no rail; a floating dock at the bottom, for a "
        "mobile-first product used on the go). And `shell.auth` — how the "
        "sign-in screen is composed: `split-editorial` (brand panel left, form "
        "right), `split-reversed`, `side-panel` (a narrower brand panel), "
        "`centered-minimal` (the form alone, for a stark tool), `brand-wash` "
        "(the form over the brand gradient, for a consumer product), "
        "`top-anchored` (a compact header and the form, for a dense "
        "back-office). And `shell.tone` — what the navigation is painted "
        "with: `dark` (the inverse surface, for a product worked in low light "
        "or a dense console), `brand` (the primary colour, when the brand "
        "leads), `light` (a card beside the page, for a quiet tool), `tinted` "
        "(the ground washed with the primary, for a warm or consumer "
        "product). Choose all three from the personality and how the product "
        "is used, and make them agree with `navigationApproach`.\n\n"
        "TYPE IS TWO DECISIONS. Name `typography.fontFamilyBase` (the body, a "
        "highly legible face) and `typography.fontFamilyHeading` (page and card "
        "titles — a display serif or a characterful sans when the personality "
        "calls for one; the body face again only when the product is quiet by "
        "intent). Both are Google Fonts families, written as the family name "
        "with a fallback stack: `\"<Family>\", <similar system face>, serif` (or sans-serif). "
        "Choose them for this product's personality — nothing here is a default."
    ),
    "requirements": (
        "Extract the application's requirements from the description. Each is one "
        "testable statement of something a user can do, with the evidence it came "
        "from. Do not design the solution.\n\n"
        "EVIDENCE NAMES ITS SOURCE. A requirement drawn from what the person typed "
        "cites evidence of type `conversation`. A requirement drawn from the text "
        "under SUPPLIED DOCUMENTS cites evidence of type `document`, with `source` "
        "naming the document (\"document 1\") and `message` quoting the sentence it "
        "came from — so the application can say which requirements the uploaded "
        "document produced. A requirement supported by both cites both."
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
        "SOME APPLICATIONS STORE NOTHING, and then this section is empty. A "
        "calculator, a converter, a scratch tool — the values live on the "
        "screen while somebody uses them and are gone when they leave. If the "
        "requirements say nothing is kept, return `entities: []` and say so in "
        "`assumptions`; do not model the screen's own working state as a "
        "table. Asked for a calculator that \"should not store anything in "
        "database\", this named a CalculatorSession with a display value and a "
        "pending operator, and every stage after it spent its time on a table "
        "that should not exist — seven minutes authoring its columns, and a "
        "page judged against a dashboard's floor because it now had an entity "
        "to summarise.\n\n"
        "Otherwise: name the entities behind the requirements and state how "
        "they relate. "
        "For each entity give `name`, `table`, a one-sentence `description` "
        "and `fields: []` — EMPTY. Do not write fields: each entity's fields, "
        "keys, enums, sensitivity and constraints are authored afterwards, one "
        "entity per call, against the set you name here, and any field you "
        "write is dropped. What that pass cannot decide alone is what you "
        "decide now: which entities exist, what each is for, and every "
        "association between them in `relationships` by entity name with its "
        "`kind`, `fromField` and `toField` — `jobId: uuid` explained in "
        "English as \"Job the part was consumed on\" is a relationship no "
        "later stage can read, and the page planner could not tell a row only "
        "ever written while looking at a job from a top-level record.\n\n"
        "THE PERSON BEHIND A LOGIN. When the people who sign in have a record "
        "of their own in this application — a Member, a Customer, a Patient, "
        "a Driver — mark exactly that one entity `account: true`. Each of its "
        "rows IS a signed-in person: its id is their account's id, it is "
        "created at signup together with their login, and every other record "
        "that points at a person points at it (`patientId`, `authorId`, "
        "`customerId` → that entity). Do not model a separate profile or user "
        "entity beside it, and do not use the platform's own users table; its "
        "login holds the email and password, so it never stores a password. When "
        "only staff sign in and nobody's record is about themselves, mark "
        "none.\n\n"
        "TERMS TWO PEOPLE NEGOTIATE carry the negotiation in their status — "
        "requested, countered, accepted, declined, withdrawn — and, when each "
        "offer should be kept, an Offer entity (who proposed it, the proposed "
        "terms, when) related to the record being agreed."
    ),
    "entity_fields": (
        "Author the fields of ONE entity, the one given below. Its `name` and "
        "`table` are decided and every other entity is named beside it; keep "
        "them exactly as given and return exactly one entry in `entities`, "
        "for this entity. Fields with real types, which field is the "
        "human-readable label (`labelField`), which are required, unique or "
        "the primary key, which take one of a fixed set of `enumValues`, and "
        "which hold sensitive data. Mark `sensitive: true` on anything "
        "personal or financial — downstream agents rely on that flag and "
        "cannot see this section to second-guess it. The foreign keys are "
        "the declared relationships: give each one its column here, named as "
        "the relationship's `fromField`. Beyond what the workflows need, give "
        "the entity what a person LOOKS AT to decide about one of these records "
        "— a listing's category, description, photos and what is included; a "
        "person's display name and area — because a screen can only show what "
        "is stored. The entity marked `account` never has a password or "
        "credential field — the login holds it. A place people are near to each other — where a member "
        "lives, where a listing is collected — is one field of type "
        "`location` ({lat, lng}, kept to about 100 m), never a street address "
        "or separate latitude/longitude columns; it is what lets a page say "
        "\"0.4 mi away\". Add `constraints` for uniqueness and "
        "checks the columns cannot express on their own, for this entity only. "
        "`unique: true` on a field says no two rows of this table may EVER "
        "hold the same value — an email, a code, a slug, a barcode. Ask of "
        "each: could two records legitimately share this value? A reference "
        "to the one side of a one-to-many is shared by definition, and so "
        "are counts, amounts, dates, statuses and names people choose; "
        "\"one per pair\" is a `unique` constraint over both columns, not a "
        "flag on either. "
        "A picture a person uploads is a field of `type: \"image\"`. When the "
        "application finds these records by what they look like or mean — "
        "search by photo, \"find similar\", \"show me ones like this\" — add a "
        "field `{\"name\": \"photoEmbedding\", \"type\": \"vector\", "
        "\"embedding\": {\"of\": \"photo\"}}` whose `of` names the image or "
        "text field it is taken of; the platform computes it, so it is never "
        "required and never asked of a person."
    ),
    "ux_architecture": (
        "Organise the application into modules and a navigation tree. Every list "
        "and dashboard page must be reachable from navigation." + "\n\n"
        "HOW A PHONE GETS AROUND. Set `navigation.mobile`: `tabs` for a "
        "mobile-first product — then mark with `tab: true` the three to five "
        "destinations people open every visit, which become its bottom tab "
        "bar — or `drawer` when phones are occasional and the menu can sit "
        "behind a hamburger. A destination that is a filtered view of a page "
        "(\"My listings\" on the listings page) names that page and the view's "
        "key in `view`, so it is its own address. Give every navigation node an `icon`: the "
        "lucide-react name (kebab-case) that depicts that destination in this "
        "product."
    ),
    "page_contracts": (
        "Decide the page set, feature by feature, from the slots below: fill "
        "a feature completely or decline it completely, and for every page "
        "you keep give its `name`, `route`, a one-sentence `purpose`, its "
        "`pattern`, its `module`, `data.primaryEntity` (the entity the page is "
        "about; omit for a dashboard or a sign-in), `access`, and `figmaFrame` "
        "where a slot carries one. NOTHING ELSE: no tasks, states, views, "
        "actions, users or widgets — the contracts are written afterwards, "
        "one feature per call, against the set you decide here, and anything "
        "beyond the set is dropped. A page earns its route when it has a "
        "different job, a different primary entity, or a different audience; "
        "a different filter over the same list is a view the contract will "
        "declare, not a page.\n\n"
        # THE PATTERN A CALCULATOR HAD TO LIE ABOUT. Every other value in the
        # enum names a way of showing, entering or arranging RECORDS, so a
        # self-contained tool took `dashboard` — the least-bad option for one
        # screen at "/" — and the dashboard floor then demanded three KPI
        # tiles, a chart and a recent-activity surface it had no records for.
        # Every composition was refused, and the page author bolted a chart
        # bound to {{resultHistory}} and a feed bound to {{keystrokeLog}} onto
        # a keypad to get past it. Naming the value in the enum is not enough;
        # the agent has to be told when it is the right one.
        "`tool` is the pattern for a screen that is NOT about the "
        "application's records: a calculator, a converter, a scratch pad, "
        "anything whose values live on the screen while someone works and are "
        "not kept afterwards. Give it no `data.primaryEntity` — there is no "
        "entity, and inventing one to hold a value nobody wants stored is the "
        "mistake this value exists to prevent. Choose it on what the screen is "
        "FOR, never on where it sits: a tool is still a tool at \"/\", and "
        "`dashboard` means a summary of records someone signs in to read.\n\n"
        "SIGNING IN IS NOT YOURS TO DECLARE. `/login` and `/signup` are added "
        "for every application with a sign-in; do not declare them, and do "
        "not declare a public \"register\" or \"create profile\" page for the "
        "entity that is the person behind a login (`account: true`) — that "
        "person's record is created at signup, with their account. A page "
        "where a signed-in person EDITS their own record is still yours."
    ),
    "page_details": (
        "Write the Page Contracts for the pages of ONE feature, the pages given "
        "below. The page set is decided: every page you write already exists, "
        "with its id, route, pattern, module and entity, and you add nothing to "
        "it and remove nothing from it — a page that seems missing is a "
        "`change_request`, not a proposal. Keep each page's id, route, "
        "`figmaFrame`, `module` and `data.primaryEntity` exactly as given.\n\n"
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
        "twenty.\n\n"
        "SAY WHAT EACH PAGE SAYS, in `content`. The tasks say what a reader does "
        "here; the content says what they are shown to do it — the facts they "
        "weigh, in the order they weigh them. Think as the product's best UX "
        "designer: ask what the reader is deciding on this page and what they "
        "would weigh — for a listing, what it is, what comes with it and who "
        "offers it; for a patient's chart, the latest results and what changed; "
        "for a job candidate, experience against the role and where they are in "
        "the process; and what happens if something goes wrong. For each fact "
        "give a `label`, the reader's "
        "question it `answers`, a `prominence` (`lead` for the one thing the "
        "page leads with, `key`, `supporting`, `reassurance` for what sits "
        "beside the main action) and its `source`:\n"
        "- `field`: a field of the page's record (`field`), or of `entity`. If "
        "the entity does not have the field a reader needs — a listing with no "
        "description, no category, nothing about what is included — propose it "
        "in `newField` ({type, description, enumValues for an enum}); it is "
        "added to the data model before any form is written, so the form that "
        "creates the record asks for it.\n"
        "- `related`: the record the page's record points at through its "
        "foreign key `via` (`entity`, and the `field` shown — the owner's name).\n"
        "- `reverse`: the record that points AT the page's record, when the "
        "link is stored on the other side — the row of `entity` whose foreign "
        "key `via` is the page's record, narrowed by `where`, the latest by "
        "`sort` (default createdAt), shown by `field`; or, with `then` {via, "
        "entity, field}, a field of the record that row points at. A member's "
        "current membership tier: Membership `via` memberId, `where` status "
        "active, `then` {via tierId, entity Tier, field name}.\n"
        "- `count` / `total`: rows of `entity` whose foreign key `via` points at "
        "the page's record — or, with `of`, at the record it points at (on an "
        "order page, the customer's past orders: Order rows `via` customerId "
        "`of` customerId) — narrowed by `where`; a "
        "total adds `fn` and a numeric `field`. Leave `via` out to count every "
        "row that matches `where` — an overview's open tickets belong to no "
        "one record. A `where` key may reach through a foreign key of "
        "`entity` as `fk.field` — an order's items that are out of stock: "
        "OrderItem `via` orderId, `where` {\"productId.stock\": 0}.\n"
        "- `distance`: how far the reader is from the record — its `location` "
        "`field`, or through `via` the location of the record it points at "
        "(the provider's area for a listing). Never the coordinates themselves.\n"
        "- `process`: what a rule or a workflow means for the reader, `about` "
        "which — the rule or the workflow's steps, in the reader's terms "
        "(what is checked before approval, what happens after a complaint is "
        "raised).\n"
        "Choose, do not list: a page's content is what the reader weighs, "
        "usually five to ten facts — a record page is not every field of the "
        "record, and the rest stays one click away. "
        "A list page's content is what each row shows (a name and the facts "
        "that let a reader pick one — never an id). A form's content is the "
        "reassurance around it. Only what the application actually keeps or "
        "decides: never invent a figure, a score or a term the description "
        "and the data model do not have, and nothing the business rules forbid."
    ),
    "analytics": (
        "Design the analytics of this application: the KPIs, charts and "
        "breakdowns each page carries, written as `widgets`. Every page and "
        "every entity's fields are already decided; you attach numbers to the "
        "pages whose users need them and to no others.\n\n"
        "Decide page by page, from what the page is for and who uses it. A "
        "dashboard or overview is mostly analytics: lead with three to five "
        "KPIs (`kind: metric`) that answer how things stand, then the charts "
        "that explain them — a trend over time, a breakdown by status or "
        "type, a ranking. A list page may carry a small summary strip (two to "
        "four metrics over the same records). A record page may carry the "
        "record's own history — a customer's orders by month — which the page "
        "narrows to the record. A form, a wizard, a settings page or a tool "
        "carries none. Every widget serves a requirement or a persona's goal; "
        "never add a chart to fill space.\n\n"
        "A DASHBOARD IS RICH, AND EVERYTHING ON IT IS ABOUT THIS APPLICATION. "
        "Its widgets answer the questions its persona brings to it (the page's "
        "purpose and primary tasks say which; the requirements and objectives "
        "say why), in this order: three to five metrics that say how things "
        "stand — each with `timeField` set to its entity's natural date where "
        "one exists, so the page's date range narrows it and it shows its "
        "change against the period before; then at least three charts of at "
        "least two different marks: the trend over time (a `bucket` by week "
        "or month, line or area), the breakdown by the status or type that "
        "matters (donut or bar), the ranking of who or what leads (a "
        "horizontal bar, `sort` and `limit`) — and, where the domain has "
        "them, the stages records move through (funnel), the busy hours "
        "(heatmap), the split by a second dimension (stacked bar). Name in "
        "`requirements` the requirement each widget answers — a widget that "
        "answers none does not belong — and write a `description` a reader "
        "of this product would recognise. Never a generic “total records”: "
        "the count of the thing this product is about, in its own words.\n\n"
        "CHARTS SHOW UP ON EVERY RELEVANT PAGE — the contract refuses a reply "
        "that leaves one bare. Every `dashboard` page carries at least three "
        "`kind: chart` widgets of at least two marks beside its metrics, one "
        "of them over time when the data has a date. Every `entity_list`, "
        "`master_detail` or `approval_inbox` page whose entity has a status "
        "or type (an enum), a date, an amount or a foreign key carries at "
        "least one chart of what it lists: the breakdown by that status or "
        "type, the trend over that date, the total by that amount. A record "
        "page whose entity has dated records pointing at it carries that "
        "history. The page writer draws every widget you declare, so a page "
        "you leave bare stays bare.\n\n"
        "Every widget reads a `query` data source: measures (count, "
        "count_distinct, sum, avg, min, max — each with a `key` that names the "
        "number in each row, and a human `label`) by at most two dimensions "
        "(the axis, then the split). Only columns the entity declares: `sum` "
        "and `avg` over numeric fields, a `bucket` (day/week/month/quarter/"
        "year) only on a date field, a dimension on a field with a small set "
        "of values (an enum, a status, a foreign key), a bucketed date, or a "
        "number grouped into `ranges` — never on a free-text field, an id of "
        "the entity itself, or a raw number with many values. A number "
        "people think of in groups (age, price, score, duration) is a "
        "dimension with `ranges`: ordered bands `{label, from, to}` where "
        "`from` ≤ value < `to` and an open end is left out — age groups are "
        "`[{label: \"Under 18\", to: 18}, {label: \"18–30\", from: 18, to: "
        "31}, …, {label: \"61+\", from: 61}]`; bands do not overlap. A metric "
        "has no dimension; set `timeField` to the entity's natural date so the "
        "page's date filter narrows it. `filter` holds literal equality values "
        "(`status: \"OPEN\"`); whose rows a reader sees is already enforced by "
        "the security rules — do not filter by user.\n\n"
        "Draw each chart by the job its data does, in `chart.mark`: change over "
        "time → line (area when the total matters; bar for few periods); "
        "comparing categories → bar (`horizontal` for long names or a "
        "ranking, with `sort` and a `limit` for top N); part of a whole with "
        "up to six parts → donut; ordered stages a record moves through → "
        "funnel; two measures against each other → scatter (one dimension, two "
        "or three measures); intensity across two categories, such as weekday "
        "by hour → heatmap (two dimensions, one measure); a hierarchy of "
        "shares → treemap, or sunburst when the rings read better; who "
        "connects to whom, such as referrals from one department to another "
        "→ graph (two dimensions — where a link starts and where it ends — "
        "one measure); a number per country → map (one dimension holding "
        "the country's name or ISO code, one measure); a profile over "
        "several axes → radar. A split "
        "dimension on a bar or area may be `stacked`. Never put two measures "
        "of different scale on one chart — that is two widgets.\n\n"
        "`unit` says how the number reads: currency for money, percent only "
        "over an average of a 0–1 ratio column, duration for seconds. `size` "
        "is the share of the row it takes (sm a quarter — metrics; md a half; "
        "lg two thirds; full the whole row), and `order` its position on the "
        "page, metrics first. Give each a one-sentence `description` of what "
        "the reader learns from it."
    ),
    "apis": (
        "Define the endpoints the pages and workflows need. Every state-changing "
        "endpoint carries a permission; a POST/PUT/PATCH/DELETE without one is a "
        "hole."
    ),
    "workflows": (
        # A CALCULATOR GOT FIVE. `Calculate`, `ClearCalculator`, `EnterDigit`,
        # `EnterDecimalPoint`, `SetOperator` — one per key — each a server
        # process posting to an endpoint, against a table the run had already
        # been told should not exist. Authoring their step graphs took 212
        # seconds, declaring them 59 more, and the page then wired its keys to
        # them, so every press was a round trip that wrote to a row nothing
        # ever created.
        #
        # None of it was this agent's mistake: it was asked what processes the
        # requirements describe, and "clear the display" is one. What it was
        # never told is that a process here means the SERVER doing something,
        # and that a screen changing its own values is not that.
        "SOME APPLICATIONS RUN NO SERVER PROCESS AT ALL, and then this section "
        "is empty. A workflow reads or writes the application's records; if "
        "the data model holds no entities, there is nothing for one to act on "
        "and `workflows: []` is the correct and complete answer. A screen that "
        "works something out from what is on it — a calculator's keys, a "
        "converter's fields — does that in the browser through the page's own "
        "`clientState`, and needs no workflow, no endpoint and no table. Do "
        "not declare one per button.\n\n"
        "Declare the business processes as workflows: for each, its `name`, "
        "`purpose`, `trigger`, the page that launches it (`launchedFrom`, "
        "required for a manual trigger) and its `inputs`. DO NOT write "
        "`steps` — leave the key out entirely. Each workflow's step graph is "
        "authored in a separate pass, one workflow per call, against the node "
        "catalog; what that pass needs from you is a complete and correct "
        "contract, because the pages are composed against this declaration "
        "at the same time as the steps are written, and a button wired to a "
        "workflow whose inputs change afterwards is a button that fails.\n\n"
        "Declare `inputs`: what the workflow needs to start. A workflow that "
        "acts on one record declares `{name, kind: \"record\", entity}`; one "
        "that takes what a person types declares `{name, kind: \"field\", "
        "type}` per field. The control that runs the workflow must supply every "
        "required input from its page — the record a detail page shows, the "
        "fields a form collects — and a control that cannot is refused, so an "
        "input left undeclared is a button that fails when pressed. Every "
        "field a step will later read (`{{title}}`) must be declared here as "
        "a `field` input, and a workflow acting on a record must declare the "
        "record; the step author cannot add inputs the pages were not told "
        "about.\n\n"
        "AGREEING TERMS IS A CONVERSATION OF OFFERS. When two people agree "
        "something through the application — the dates and terms of a loan, a "
        "price, a schedule — model each move as its own workflow, not one "
        "approve/decline: the request, a counter-offer that changes the terms "
        "and sets the record to a `countered` state, accepting (which locks "
        "the terms), declining, and withdrawing. Each is launched from the "
        "record's page by the party whose turn it is. Nothing loops: the "
        "record's state says whose move it is."
    ),
    "workflow_steps": (
        "Author the steps of ONE workflow, the one given below. Its identity "
        "and contract — `name`, `trigger`, `launchedFrom`, `inputs` — are "
        "already decided and the pages are being composed against them as "
        "you work; keep them exactly as given and return them unchanged "
        "alongside the `steps` you write. Return exactly one proposal, for "
        "this workflow, under the `natural_key` given below.\n\n"
        "Every step IS a node from the workflow node catalog below: its "
        "`type` is a catalog node, and its `config` carries what that node "
        "declares it needs — the `actionType` and table/values of an action, "
        "the `expression` of a condition, the `assignType` and `assignTarget` "
        "of a human task — filled in with real values (entity tables, "
        "`{{variable}}` bindings, role names), not left for someone else. A "
        "step missing a required key is refused. Connect steps with `next` "
        "(a branching node's first target is the then-branch, its second the "
        "else-branch); the workflow's `trigger` is the start, and an `end` "
        "step is the terminal. Where a check refuses the input, its branch "
        "ends on an `end` with `config.refused: true` and `config.message` — "
        "the sentence the person is shown, saying what to correct — and every "
        "other end says `config.refused: false`; a refused run is reported "
        "to the person as a failure, never as the success message. Any step "
        "that mutates an entity must name a real one.\n\n"
        + 'Conditions and gateway expressions are FEEL, read by the engine\'s parser: `=` (never `==`), `and`, `or`, `not`, names without braces (`caseType = "Refund" and refundAmount > 0`), membership as `stage in ["A", "B"]` with square brackets, never parentheses. Values in step config are templates over what the engine holds: the trigger\'s input fields by name (`{{title}}`, never `{{input.title}}`), a step\'s output under its key (`{{insert_case.id}}`), a variable a set_variable step set by its `variableName`; the current time and actor are the whole-value sentinels `$now`, `$today`, `$user.id`. There is no `now`, `currentUser`, `vars`, `steps` or `sequence` root; a template naming one is refused. The expression functions the engine has are sum, count, min, max, avg, abs, floor, ceiling, round, contains, starts with, ends with, matches, string, number, date, now, duration — nothing else (no concat, substring, uuid, upper, format); a reference number nothing supplies is `$uuid`, a fresh identifier, written in the insert itself. A db_insert supplies every field the data model marks required — an input by name, `$now`, `$user.id`, `$uuid`, or a literal starting state; one that omits a required field is refused, and a later db_update cannot rescue it.'
        + "\n\nTELL THE OTHER PERSON. When a step changes something another person "
        "must act on or would want to know — a request arrives for them, their "
        "request is approved or declined, a case is opened against them, a job "
        "they asked for is done — add an `action` step with `actionType: "
        "send_notification`, a short `title`, a `message` in the domain's words "
        "and `recipient`: that person's user id. Find it with a `db_query` "
        "first when it lives on another record (`{{find_order.customerId}}` — a "
        "query's fields are read from its first row); never `$user.id`, which "
        "is the person acting. A whole team is `recipientRole`. Where the "
        "application has an email integration, a `send_email` step beside it "
        "reaches them away from the app."
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
        "statement constrains people, not forms.\n\n"
        "A person must have DONE SOMETHING BEFORE they may do something else — "
        "verified their identity before selling or buying, been approved "
        "before booking, paid before downloading. That is `kind: "
        "\"prerequisite\"`, never a statement: a statement is prose nothing "
        "enforces, and anyone could do it anyway. Give `gates` (the "
        "workflows it blocks, by id), `requires` (the record that satisfies "
        "it: `entity`, `account` — the field of that entity holding the "
        "person's account id — and `where`, the values it must have, such as "
        "`{\"status\": \"approved\"}`), `message` (what the person is told, "
        "saying what to do first) and `page` (the page where they do it; a "
        "new account is sent there first). Every gated workflow then starts "
        "by checking it and refuses with the message when it is not met."
    ),
    "security": (
        "Define roles and the permissions that guard entities and endpoints. "
        "Then say who reaches which rows: an entity whose rows belong to one "
        "user or one workspace needs an ownershipRules entry naming the entity "
        "and the column that scopes it, because that object is what the data "
        "engine turns into a WHERE clause \u2014 a prose rule beside it "
        "documents the policy and enforces nothing. A rule scoped to a "
        "workspace also names `actorColumn`: the users column whose value is "
        "the actor's workspace (homePropertyId, organisationId), because the "
        "session carries that column and the engine compares against it. "
        "Where authorisation really "
        "is by role and every holder sees every row, write that as a prose rule "
        "so the absence of a scoping object reads as a decision.\n\n"
        "When people create their own accounts, set `signupRole` to the role "
        "they get — the role whose pages and workflows a new self-registered "
        "person uses. Without it a new person holds no role the application "
        "names, and every workflow gated by role refuses them."
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


CONVENTIONS_ADDENDUM = """

## The application as a whole

The app was composed once before any page was, and these are its decisions. \
Follow them; a page that re-decides them breaks the coherence the pass exists \
to give.

Vision: {vision}

Conventions:
{conventions}
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


def _conventions_addendum(doc: dict) -> str:
    """The app-level composition's decisions, for the composer that works under
    them. Doc-level only — never the subject — so it sits in the cached prefix
    and stays byte-identical across a fan-out. Empty when no composition pass
    has run, so a Blueprint from before the node exists composes as it did."""
    comp = doc.get("composition") or {}
    if not comp.get("vision") and not comp.get("conventions"):
        return ""
    conventions = "\n".join(
        f"- {c.get('topic', '')}: {c.get('rule', '')}"
        for c in comp.get("conventions") or []
    ) or "(none stated)"
    return CONVENTIONS_ADDENDUM.format(
        vision=comp.get("vision") or "(none stated)", conventions=conventions,
    )


def build_prompt(
    doc: dict, node: str, *, inline_schema: bool = False, inline_shapes: bool = True,
    subject: str = "", feedback: str = "", references: Sequence[Path] = (),
    output_dir: Any = None, brief: str = "", agent: str = "",
) -> tuple[str, str]:
    """Build (system, user) for a node.

    ``brief`` is Smith's ask for THIS call — what should change in an artifact
    that already exists, and what must stay. It is not feedback: feedback says
    why the last attempt was refused, a brief says what this attempt is for.

    ``inline_schema`` is set when the transport cannot enforce the envelope, so
    the schema is stated in the prompt instead. It is a weaker guarantee — a
    statement rather than a constraint — which is why the validation below it
    is unchanged either way.

    ``references`` are the images the caller is about to attach. They are named
    in the system prompt rather than left to speak for themselves: an image is
    ambiguous about its own status, and the expensive reading — a screenshot of
    the system being replaced taken as a specification of the one being built —
    is the one a model reaches for unprompted.

    ``agent`` is who is being asked, when that is not the node's own owner:
    Smith recomposing a screen asks `a2ui_pages` for a `page_layouts`
    subject, and the build lays pages out without a model at all.
    """
    spec = DAG[node]
    agent = agent or spec.agent
    cap = capability_for(agent)
    system = SYSTEM.format(
        agent=agent,
        writes="\n".join(f"  - {s}" for s in sorted(cap.writes)) or "  (none)",
        reply_rules=(DATA_MODEL_REPLY_RULES if node in SCHEMA_BY_NODE
                     else ENVELOPE_RULES),
        task=NODE_TASKS.get(node, f"Produce the {node} artifacts this stage owns."),
    )
    if inline_shapes:
        shapes = writable_shapes(agent)
        if shapes:
            system += SHAPE_ADDENDUM.format(
                shapes=json.dumps(shapes, indent=2)[:12000]
            )
    system += reference_addendum(references, node)
    if agent == "a2ui_pages":
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
        system += _conventions_addendum(doc)
        brief = page_brief(doc, subject) if subject else {}
        # THIS PAGE'S PLACE IN THE WHOLE. Subject-specific, so it belongs in
        # the user turn, not the cached prefix.
        sketch_note = (
            "`composition.sketch` is this page's place in the whole-app "
            "composition: realise those sections, in that order, from the "
            "catalog. `composition.siblings` shows what the pages next to "
            "this one look like — match their rhythm rather than inventing "
            "your own.\n\n"
            if (brief.get("composition") or {}).get("sketch") else ""
        )
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
            "A field that holds an uploaded file — its URL or name (e.g. "
            "`fileUrl`, `fileName`) — is collected by a `FileUpload`, never a "
            "text field: nobody types a file URL. Set its `name` to the URL "
            "field and `filenameField` to the file-name field, so the one "
            "control provides both.\n\n"
            "A control that runs a workflow names it by id from `workflows` "
            "below — `FLOW-007`, never its title, never a name you infer "
            "from the page, never a template. If no listed workflow does what "
            "the control needs, the control navigates instead or is left "
            "out; there is no workflow this application runs that is not in "
            "that list.\n\n"
            # THE SCREEN'S OWN VALUES. Every action this prompt described above
            # reaches the server. Asked for a calculator that stores nothing,
            # the composer had no word for a number that lives on the screen —
            # so it made the display a column, every key a workflow, and
            # shipped a page where no key did anything.
            #
            # Stated for every page, not only the tool-shaped ones: the hybrid
            # is the common case (a form that totals as you type and then
            # submits the total), and a page cannot be told after the fact that
            # it was allowed to compute.
            "A value that lives only on this screen — a running total, a "
            "calculator's display, a unit conversion, a filter someone is "
            "still typing — is declared in `clientState`: a `name`, a `type` "
            "of string, number or boolean, and what it starts at. Read it "
            "anywhere a binding goes, as `{{state.<name>}}`. A control "
            "changes it with `clientAction`: `{\"kind\": \"set\", "
            "\"target\": \"display\", \"value\": \"0\"}` writes a "
            "literal, and `{\"kind\": \"compute\", \"target\": "
            "\"display\", \"formula\": \"display + '7'\"}` evaluates "
            "over the current values and writes the result. Nothing declared "
            "here is stored, sent anywhere or kept after the page closes.\n\n"
            # MEASURED ON A LIVE RUN. The composer wrote the list before the
            # contract allowed one, and every attempt at the page was refused:
            # a Clear key setting the display, the error flag and the message
            # is three changes and one press, and there was no honest way to
            # say it. The instinct was right and the contract was too narrow.
            "One press may change several values: give `clientAction` a LIST "
            "of actions and they are applied together. Every one of them reads "
            "the state as it was BEFORE the press, so their order means "
            "nothing and none can use another's result. Write each value at "
            "most once in a press, and do not try to chain them.\n\n"
            "`clientState` and `dataSources` are independent. A screen with "
            "only data sources is the ordinary server-backed page. A screen "
            "with only client state is a self-contained tool, and it needs no "
            "entity, no workflow and no table — do not invent one to hold a "
            "value the brief says is not kept. A screen with both is the "
            "hybrid: the same Button may carry a `clientAction` that works out "
            "a total AND a `workflow` that submits it, and both run, the "
            "client action first.\n\n"
            "Declare every value a control writes to, bind every value you "
            "declare somewhere a person can see it, and do not declare state "
            "a page does not need — most pages need none.\n\n"
            + sketch_note +
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

    if node == "workflow_steps":
        return _workflow_steps_prompt(doc, system, subject, feedback,
                                      output_dir=output_dir, brief=brief)

    if node == "workflows":
        # The node catalog goes to `workflow_steps`, the one task that authors
        # steps; this one declares and needs only the trigger kinds it may
        # name. Neither pays for the other's vocabulary.
        from services.catalog import workflow_nodes

        system += (
            "\n\nA workflow's `trigger.kind` is one of: "
            + ", ".join(workflow_nodes().trigger_types) + "."
        )
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
            + json.dumps(context_for(doc, agent), indent=2, sort_keys=True)
            + "\n```"
        )
        if slots:
            user += (
                "\n\n" + workflow_slot_prompt(doc) + "\n\n```json\n"
                + json.dumps(slots, indent=2, ensure_ascii=False) + "\n```"
            )
        if brief:
            user += "\n\nSmith's brief for this call — what to change and what to keep:\n\n" + brief
        if feedback:
            user += "\n\nYour previous attempt was rejected:\n\n" + feedback
        return system, user

    if node == "page_details":
        return _page_details_prompt(doc, system, subject, feedback,
                                    output_dir=output_dir)

    if node == "entity_fields":
        return _entity_fields_prompt(doc, system, subject, feedback, brief=brief)

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
            + json.dumps(context_for(doc, agent), indent=2, sort_keys=True)
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
    if agent == "figma_intelligence" and subject:
        # §48 — the design is evidence, and the brief is where that bound is
        # set. The agent sees the screens' vocabulary and the extraction's
        # gaps; it does not see the generated TSX, which is layout noise that
        # would crowd out the labels that actually carry meaning.
        from services.figma.brief import brief_for

        brief = brief_for(doc, subject, output_dir)
        # THE TOOL THE DESIGN LIVES IN names the evidence type. A UX Pilot
        # page fills the same brief; its citations must say so, or every
        # requirement it evidences would claim a Figma frame that does not
        # exist.
        provider = str(brief.get("provider") or "figma")
        tool_label = {"uxpilot": "UX Pilot", "figma": "Figma"}.get(provider, provider)
        unit = "design" if provider == "uxpilot" else "frame"

        user = (
            f"A user connected this {tool_label} design as the visual reference for "
            "the application being built. Propose the requirements it is "
            "evidence for.\n\n"
            f"Every requirement must cite the {unit} it came from, in "
            "`evidence`, as "
            f'`{{"type": "{provider}", "source": "<source>", "node": "<nodeId>"}}`.\n\n'
            "State only what the design shows. A screen proves that a "
            "capability is reachable; it does not tell you who may use it, "
            "what conditions govern it, what it writes, or what happens when "
            "it is refused. Where the design implies something without "
            "showing it, propose it at the confidence you actually have — the "
            "listed gaps are questions the user will be asked, not holes for "
            "you to fill.\n\n"
            "```json\n"
            + json.dumps(brief, indent=2, sort_keys=True)
            + "\n```"
        )
        if feedback:
            user += f"\n\nYour previous attempt was rejected:\n\n{feedback}"
        return system, user

    user = (
        "Here is the Blueprint as it stands. Propose the artifacts your stage "
        "owns.\n\n```json\n"
        + json.dumps(context_for(doc, agent), indent=2, sort_keys=True)
        + "\n```"
    )
    # WHAT THE USER HANDED OVER. A specification uploaded instead of typed is
    # kept beside the Blueprint (services.blueprint.documents), not inside
    # `application.description`, and put in front of the nodes that read it
    # on every run — the first definition, the clarified one, the build.
    from services.blueprint import documents as _documents
    user += _documents.addendum(output_dir, node)
    # WHAT THE COMPANY LOOKS LIKE AND SOUNDS LIKE, when the owner chose to
    # build this application in their organisation's design language. Adopted
    # beside the Blueprint by the same route a supplied document is, and
    # empty for every node that cannot act on it — the table in
    # `brand_language.READ_FOR` decides, not a condition here.
    from services.blueprint import brand_language as _brand
    user += _brand.addendum(output_dir, node, doc)
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
    if agent == "solution_architecture":
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
                    "account": {
                        "type": "boolean",
                        "description": (
                            "True on the ONE entity that is the person behind a login "
                            "(a Member, a Customer, a Patient): each row IS a signed-in "
                            "person and is created at signup with their account. Omit "
                            "it everywhere else."
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
                                "embedding": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["of"],
                                    "description": (
                                        "ONLY on a `type: \"vector\"` field — omit it on "
                                        "every other field: the image or text field on "
                                        "this entity it embeds. The platform fills it."
                                    ),
                                    "properties": {"of": {"type": "string"}},
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
            "description": (
                "§30 — what you return instead of reaching outside your own "
                "section. TO ASK FOR AN ARTIFACT TO BE RETIRED, set `retire` "
                "to its id: that is acted on, and every stage after you sees "
                "it gone. `entity_fields` runs against ONE entity and is the "
                "stage that discovers a table should not exist — say so here "
                "rather than authoring its columns."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "reason"],
                "properties": {"section": {"type": "string"},
                               "reason": {"type": "string"},
                               "retire": {"type": "string"}},
            },
        },
    },
}

#: The reply shape each node is held to. Absent means the §29 envelope.
SCHEMA_BY_NODE: dict[str, dict[str, Any]] = {
    "data_model": DATA_MODEL_SCHEMA,
    "entity_fields": DATA_MODEL_SCHEMA,  # one entry, for one entity
}


def declared_workflow(doc: dict, workflow_id: str) -> dict | None:
    """The declared row `workflow_steps` is authoring for, or None."""
    for row in doc.get("workflows") or []:
        if isinstance(row, dict) and row.get("id") == workflow_id:
            return row
    return None


#: What the declaration decided and the author may not move. Only `steps` is
#: the author's. `inputs` stay declared because the pages are composed against
#: them concurrently: an input the author adds is one no button supplies, and
#: a step that needs a value nothing declares is refused at apply and re-asked,
#: which is the right place for that conversation.
_DECLARED_FIELDS: tuple[str, ...] = (
    "id", "name", "purpose", "trigger", "launchedFrom", "inputs", "requirements",
    "status",
)


def _workflow_steps_prompt(doc: dict, system: str, subject: str,
                           feedback: str, *, output_dir: Any = None,
                           brief: str = "") -> tuple[str, str]:
    """One workflow, the node catalog, and the slice of the Blueprint its
    steps can name. The full `workflows` section is NOT sent: thirty-four
    sibling declarations are noise to an author writing the thirty-fifth."""
    from services.catalog import workflow_nodes

    system += WORKFLOW_CATALOG_ADDENDUM.format(catalog=workflow_nodes().digest())

    row = declared_workflow(doc, subject) or {"id": subject}
    context = context_for(doc, "workflow")
    # Written by this node as it runs, so never part of the shared prefix.
    context.pop("workflows", None)
    # The requirements this workflow answers, when it says which; the whole
    # section otherwise, which is what the declaration was written from.
    requirements = context.pop("requirements", None) or []
    wanted = set(row.get("requirements") or [])
    if wanted:
        requirements = [r for r in requirements
                        if isinstance(r, dict) and r.get("id") in wanted]
    natural_key = _declared_key(output_dir, subject) or str(row.get("name") or subject)
    user = (
        "The Blueprint slice a workflow's steps may name.\n\n```json\n"
        + json.dumps(context, indent=2, sort_keys=True)
        + "\n```" + CACHE_BREAK
        + f"Author the steps of workflow {subject} ({row.get('name', '')!s}). "
        f"Its proposal's `natural_key` is exactly: {natural_key}\n\n"
        "Here is the workflow as declared, and the requirements it answers."
        "\n\n```json\n"
        + json.dumps({"workflows": [row], "requirements": requirements},
                     indent=2, sort_keys=True)
        + "\n```"
    )
    if brief:
        user += "\n\nSmith's brief for this call — what to change and what to keep:\n\n" + brief
    if feedback:
        user += "\n\nYour previous attempt was rejected:\n\n" + feedback
    return system, user


def _declared_key(output_dir: Any, workflow_id: str) -> str | None:
    """The natural key the allocator bound this workflow's id to; None when
    there is no directory to read the registry from."""
    if not output_dir:
        return None
    from services.blueprint.ids import IdAllocator

    try:
        return IdAllocator.load(output_dir=output_dir).key_for(workflow_id)
    except Exception:  # noqa: BLE001 — a missing registry is not a prompt error
        return None


def declared_entity(doc: dict, entity_id: str) -> dict | None:
    for row in (doc.get("data") or {}).get("entities") or []:
        if isinstance(row, dict) and row.get("id") == entity_id:
            return row
    return None


def pin_entity_set(result: AgentResult) -> None:
    """Keep the entity declaration to what it declares: names, tables,
    descriptions and relationships. Fields are the author's, and a
    declaration that wrote them would read as an authored entity to resume;
    constraints belong to the entity they constrain and go with the fields.
    Anything outside this agent's boundary is left for the contract to
    refuse."""
    result.proposals = [p for p in result.proposals
                        if p.section != "data.constraints"]
    for proposal in result.proposals:
        if proposal.section == "data.entities":
            body = dict(proposal.body or {})
            body["fields"] = []
            body.pop("labelField", None)  # names a field nobody has written
            proposal.body = body


def _entity_fields_prompt(doc: dict, system: str, subject: str,
                          feedback: str, *, brief: str = "") -> tuple[str, str]:
    """One entity in full, every entity by name, and the relationships that
    touch it — the foreign keys this entity must carry a column for."""
    row = declared_entity(doc, subject) or {"id": subject}
    data = doc.get("data") or {}
    others = [
        {"id": e.get("id"), "name": e.get("name"), "table": e.get("table"),
         "description": e.get("description", "")}
        for e in data.get("entities") or []
        if isinstance(e, dict) and e.get("status") != "DEPRECATED"
    ]
    touching = [
        r for r in data.get("relationships") or []
        if isinstance(r, dict) and subject in (r.get("from"), r.get("to"))
    ]
    context = context_for(doc, "data_model")
    requirements = context.pop("requirements", None) or []
    wanted = set(row.get("requirements") or [])
    if wanted:
        requirements = [r for r in requirements
                        if isinstance(r, dict) and r.get("id") in wanted]
    # Shared by every entity first; this entity's own part after the break.
    context["data"] = {"entities": others}
    own = {"data": {"relationships": touching, "constraints": []},
           "requirements": requirements}
    user = (
        "Every entity by name, and the Blueprint slice a field may name.\n\n```json\n"
        + json.dumps(context, indent=2, sort_keys=True)
        + "\n```" + CACHE_BREAK
        + f"Author the fields of entity {subject} ({row.get('name', '')!s}, "
        f"table {row.get('table', '')!s}). Return one entry in `entities`, "
        f"named exactly {row.get('name', '')!s}.\n\n"
        "Here is the entity as declared.\n\n```json\n"
        + json.dumps(row, indent=2, sort_keys=True)
        + "\n```\n\nThe relationships that touch this entity, and the "
        "requirements it answers.\n\n```json\n"
        + json.dumps(own, indent=2, sort_keys=True)
        + "\n```"
    )
    if brief:
        user += "\n\nSmith's brief for this call — what to change and what to keep:\n\n" + brief
    if feedback:
        user += "\n\nYour previous attempt was rejected:\n\n" + feedback
    return system, user


def pin_entity_identity(svc: Any, entity_id: str, result: AgentResult) -> None:
    """Make the field author's reply update the declared entity, and only it.

    The entity proposal is matched by name, case-insensitively, to the
    declared row; any other entity in the reply is one the author added to a
    set it was told was decided, and is dropped. The match takes the
    declaration's key, id, name and table, so a respelled name cannot
    allocate a second entity. Relationships and constraints pass through:
    the batch resolver sees the document's entities by name.
    """
    from services.blueprint.ids import IdAllocator

    row = declared_entity(svc.doc, entity_id)
    if row is None:
        return
    try:
        key = IdAllocator.load(output_dir=svc.output_dir).key_for(entity_id)
    except Exception:  # noqa: BLE001 — fall back to the name, which bound it
        key = None
    key = key or str(row.get("name") or entity_id)

    def loose(name: Any) -> str:
        # "Part usage", "part_usage" and "PartUsage" are one entity to an
        # author asked for exactly one; `_norm` keeps them apart on purpose
        # for allocation, which is why the match is made here and the
        # declared spelling is what gets written.
        return re.sub(r"[^a-z0-9]", "", str(name or "").casefold())

    wanted = loose(row.get("name"))
    entity_proposals = [p for p in result.proposals if p.section == "data.entities"]

    kept: list[Any] = []
    for proposal in result.proposals:
        if proposal.section != "data.entities":
            kept.append(proposal)
            continue
        body = dict(proposal.body or {})
        named = loose(body.get("name") or proposal.natural_key)
        # A reply with one entity is a reply about this entity, whatever it
        # called it; with several, the one that names it is.
        if not (len(entity_proposals) == 1 or named == wanted
                or str(body.get("id") or "") == entity_id):
            logger.warning("[entity_fields] %s: dropped an entity outside the call: %s",
                           entity_id, body.get("name") or proposal.natural_key)
            continue
        proposal.natural_key = key
        body["id"] = entity_id
        body["name"] = row.get("name")
        if row.get("table"):
            body["table"] = row["table"]
        # Whether this is the person behind a login is the entity set's
        # decision; the field author may not move it (an omitted or false
        # `account` here would clear it on upsert).
        body.pop("account", None)
        if row.get("account"):
            body["account"] = True
        # `embedding` MEANS SOMETHING ONLY ON A VECTOR FIELD. The reply schema
        # offers it on every field, and the author filled it on ordinary ones
        # — `kycStatus: {embedding: {of: "none"}}`, `{of: ""}` on two more
        # (0l133sp2). The empty ones failed the contract with a message about
        # a field that should not have had the key, the retry lost confidence
        # and was blocked, and the whole build stopped at the data model.
        body["fields"] = [
            ({k: v for k, v in f.items() if k != "embedding"}
             if isinstance(f, dict) and "embedding" in f and str(f.get("type") or "").lower() != "vector" else f)
            for f in body.get("fields") or []
        ]
        proposal.body = body
        kept.append(proposal)
    result.proposals = kept


#: What the page-set declaration decides. Everything else on a page is the
#: contract, written per feature by `page_details`; a declaration that wrote
#: `states` would read as an authored contract to the resume rule.
_DECLARED_PAGE_FIELDS: frozenset[str] = frozenset({
    "name", "route", "purpose", "pattern", "module", "data", "access", "entry",
    "presentation", "figmaFrame", "requirements", "confidence", "status",
})

#: What the declaration decided and the contract author may not move.
_PINNED_PAGE_FIELDS: tuple[str, ...] = ("id", "route", "figmaFrame", "module")


def pin_page_set(result: AgentResult) -> None:
    """Keep the declaration to what it declares.

    The page-set call is asked for routes and patterns and told to write
    nothing else, and it is a model: given the whole page shape it will
    sometimes fill it. A declaration carrying `states` would satisfy the
    resume rule for a contract nobody wrote, and a widget declared here would
    sit on a page whose contract is still to come. Dropped here, so the
    document only ever holds what this call is for.

    Only widgets are dropped. A proposal for a section this agent may not
    write at all is left for `apply_agent_result` to refuse: a boundary
    violation is a fact about the model that must surface, not be tidied.
    """
    result.proposals = [p for p in result.proposals if p.section != "widgets"]
    for proposal in result.proposals:
        if proposal.section != "pages":
            continue
        proposal.body = {k: v for k, v in (proposal.body or {}).items()
                         if k in _DECLARED_PAGE_FIELDS}


def _page_details_prompt(doc: dict, system: str, subject: str,
                         feedback: str, *, output_dir: Any = None) -> tuple[str, str]:
    """One feature's declared pages, the whole page set by id, and the slice
    of the Blueprint a contract can name."""
    from services.blueprint.ids import page_key
    from services.blueprint.orchestrator import feature_pages

    mine = feature_pages(doc, subject)
    index = [
        {"id": p.get("id"), "route": p.get("route"), "name": p.get("name"),
         "pattern": p.get("pattern"),
         "entity": (p.get("data") or {}).get("primaryEntity")}
        for p in doc.get("pages") or []
        if isinstance(p, dict) and p.get("status") != "DEPRECATED"
    ]
    context = context_for(doc, "page_design")
    context["pages"] = index
    keys = {
        str(p.get("id")): _declared_key(output_dir, str(p.get("id")))
        or page_key(str(p.get("route") or ""))
        for p in mine
    }
    from services.blueprint.orchestrator import PART

    feature, _, part = subject.partition(PART)
    what = f"feature {feature}" + (
        f" (part {part}: its other pages are written beside this one)" if part else "")
    user = (
        "The whole page set, by id — `navigatesTo` names any of these — and "
        "the Blueprint slice a contract may name.\n\n```json\n"
        + json.dumps(context, indent=2, sort_keys=True)
        + "\n```" + CACHE_BREAK
        + f"Write the contracts for {what}: the {len(mine)} page(s) "
        "below, each under the `natural_key` listed for it.\n\n```json\n"
        + json.dumps({"pages": mine, "naturalKeys": keys}, indent=2, sort_keys=True)
        + "\n```"
    )
    if feedback:
        user += "\n\nYour previous attempt was rejected:\n\n" + feedback
    return system, user


def pin_page_identity(svc: Any, subject: str, result: AgentResult) -> None:
    """Make the contract author's reply update the declared pages, and only
    those.

    A page proposal is matched to a declared page by id, then by route. One
    that matches nothing is a page the author added to a set it was told was
    decided, and is dropped — the declaration is where the page set is argued.
    A match takes the declaration's key and pinned fields, so a route
    respelled or a frame forgotten cannot allocate a second page.
    """
    from services.blueprint.ids import IdAllocator, page_key
    from services.blueprint.orchestrator import feature_pages

    declared = feature_pages(svc.doc, subject)
    by_id = {str(p.get("id")): p for p in declared}
    by_route = {page_key(str(p.get("route") or "")): p for p in declared}
    try:
        alloc = IdAllocator.load(output_dir=svc.output_dir)
    except Exception:  # noqa: BLE001 — fall back to the route, which bound it
        alloc = None

    kept: list[Any] = []
    for proposal in result.proposals:
        if proposal.section != "pages":
            kept.append(proposal)
            continue
        body = dict(proposal.body or {})
        row = by_id.get(str(body.get("id") or "")) \
            or by_route.get(page_key(str(body.get("route") or ""))) \
            or by_route.get(page_key(str(proposal.natural_key or "").removeprefix("PAGE:")))
        if row is None:
            logger.warning("[page_details] %s: dropped a page outside the feature: %s",
                           subject, body.get("route") or proposal.natural_key)
            continue
        key = (alloc.key_for(str(row.get("id"))) if alloc else None) \
            or page_key(str(row.get("route") or ""))
        proposal.natural_key = key
        for field_name in _PINNED_PAGE_FIELDS:
            if field_name in row:
                body[field_name] = row[field_name]
            else:
                body.pop(field_name, None)
        declared_entity = (row.get("data") or {}).get("primaryEntity")
        data = dict(body.get("data") or {})
        if declared_entity:
            data["primaryEntity"] = declared_entity
        if data:
            body["data"] = data
        proposal.body = body
        kept.append(proposal)
    result.proposals = kept


def pin_workflow_identity(svc: Any, workflow_id: str, result: AgentResult) -> None:
    """Make the author's reply update the declared row, whatever it replied.

    Identity is the natural key (§12). The declaration bound this workflow's
    id to one key; an author that returns the name spelled differently — or
    a `natural_key` of its own choosing — would be allocated a second id and
    the application would carry a declared workflow with no steps beside an
    authored one nobody's page launches. So the key and the declared fields
    are put back from the declaration here, before apply, and the reply
    keeps only what it was asked for: the steps.
    """
    row = declared_workflow(svc.doc, workflow_id)
    if row is None:
        return
    from services.blueprint.ids import IdAllocator

    try:
        key = IdAllocator.load(output_dir=svc.output_dir).key_for(workflow_id)
    except Exception:  # noqa: BLE001 — fall back to the name, which bound it
        key = None
    key = key or str(row.get("name") or workflow_id)

    for proposal in result.proposals:
        if proposal.section != "workflows":
            continue
        proposal.natural_key = key
        body = dict(proposal.body or {})
        authored_inputs = body.get("inputs")
        for field_name in _DECLARED_FIELDS:
            if field_name in row:
                body[field_name] = row[field_name]
            else:
                body.pop(field_name, None)
        body["inputs"] = _declared_plus_added(row.get("inputs"), authored_inputs)
        if not body["inputs"] and "inputs" not in row:
            body.pop("inputs")
        proposal.body = body


def _declared_plus_added(declared: Any, authored: Any) -> list:
    """The declared inputs, untouched, plus any NEW input the step author adds.

    A REFUSAL THE AUTHOR COULD NOT ANSWER. The reference check tells a step
    author whose step reads `{{endTime}}` to "declare 'endTime' as an input".
    It did — and this function's caller put every declared field back from
    the declaration, `inputs` among them, so the declaration was discarded,
    the same refusal came back, and after two the author was not asked again.
    On UAT (2026-09-18) that left a dental app's Book Appointment and Add
    Service workflows with no steps at all.

    Declared inputs still cannot be changed or removed — pages were designed
    against them. An input the declaration never had is added, and the page
    checks then require a form to collect it, like any other.
    """
    base = [i for i in (declared or []) if isinstance(i, dict)]
    have = {str(i.get("name")) for i in base}
    extra = [i for i in (authored or []) if isinstance(i, dict)
             and i.get("name") and str(i.get("name")) not in have]
    return base + extra


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


class Truncated(ValueError):
    """The reply ran into ``max_tokens`` mid-answer.

    It parsed as "not JSON: Unterminated string" and was retried as a
    malformed reply — the same question, the same budget, and often the same
    cut (HippieKit page_details ENTITY-003, 2026-09-21). A reply that ran out
    of room is not a reply that was wrong: the retry needs the room and the
    lighter reasoning the first call lacked, and to be told it was cut off,
    not that it was rejected. Under structured outputs a reply cannot be
    continued from where it stopped, so this is the closest thing to it."""

    def __init__(self, message: str, output_tokens: int = 0) -> None:
        super().__init__(message)
        self.output_tokens = output_tokens


class MalformedEnvelope(ValueError):
    """The model's reply did not parse as the §29 envelope."""


def _meant_to_store_nothing(node: str, data: dict) -> bool:
    """Whether an empty data model is this reply's ANSWER rather than its
    failure to give one.

    TWO AUTHORITIES THAT DISAGREED. `data_model` is told, in its own task
    text, that some applications store nothing — a calculator, a converter —
    and that the right answer is then `entities: []` with the reason in
    `assumptions`. It did exactly that on a measured run and this check
    refused the reply as malformed, twice, so the node retried until it
    invented a table. The instruction and the validator were describing
    different contracts.

    The distinction the check actually needs is not "did it name entities" but
    "did it MEAN to name none". A stall produces no `entities` key and no
    reasoning; the instructed answer produces both, because the instruction
    asks for both. Read, not inferred.

    Only for `data_model`. `entity_fields` is handed one entity and asked for
    its columns, and "this entity has no fields" is not an answer it can mean
    — an entity that should not exist is a `change_request`, which is the path
    the corrections machinery already acts on.
    """
    if node != "data_model":
        return False
    declared = data.get("entities")
    if not isinstance(declared, list) or declared:
        return False
    said = [str(a).strip() for a in (data.get("assumptions") or [])]
    return any(said)


def parse_envelope(raw: str, *, task_id: str, agent: str,
                   node: str = "") -> AgentResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedEnvelope(f"reply was not JSON: {exc}") from exc

    proposals: list[ArtifactProposal] = []
    if node in SCHEMA_BY_NODE:
        proposals = expand_data_model(data)
        if not proposals and not _meant_to_store_nothing(node, data):
            # A reply that parsed but named nothing is not a data model. Said
            # here rather than committed as an empty section, which is how a
            # missing `data.entities` looked like a stall for three runs.
            raise MalformedEnvelope("data_model: reply declared no entities")
    for i, p in enumerate(data.get("proposals") or []):
        body_raw = p.get("body")
        try:
            # strict=False: a raw newline inside a string value is what a model
            # writes in a long description, and it failed a whole restyle
            # ("Invalid control character") twice over (UAT replay).
            body = json.loads(body_raw, strict=False) if isinstance(body_raw, str) else body_raw
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

    WHOSE SPEND IT IS, AND WHAT IT WAS FOR. ``project`` and ``phase`` are
    settled once, where the run is started and both are known, because the
    calls themselves are not all in a position to say. The observer is the
    case that proved it: it judges a document it was handed and has no
    ``BlueprintService``, so it recorded ``project=""`` and every critic call
    landed in the ledger under the literal string ``blueprint``. Summing a
    project's rows then silently omitted the watching — 19-28% of three
    measured builds — and the omission looked like a smaller bill rather than
    a missing one. The alternative, matching those rows back by the times they
    were written, is a guess: runs overlap, and a guess about money is worse
    than no answer.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)
    #: The application every call on this run is spending on — its
    #: ``application.id``. Used whenever a call site cannot say for itself.
    project: str = ""
    #: What this run IS to the person who owns the application: ``build``
    #: while it is being made (defining it, building it, building it again),
    #: ``change`` for anything asked for afterwards. Recorded per row so the
    #: two can be told apart without reading timestamps.
    phase: str = "build"

    @classmethod
    def for_app(cls, svc: Any, *, phase: str = "build") -> "RunUsage":
        """A ledger that already knows whose run it is and what it is for.

        The one place the application's id and the run's purpose are both in
        hand is where the run is started, so that is where they are settled —
        rather than at each of the dozen call sites that record a call, only
        some of which are in a position to know either.
        """
        doc = getattr(svc, "doc", None) or {}
        return cls(project=str((doc.get("application") or {}).get("id") or ""),
                   phase=phase)

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
                project=project or self.project or "blueprint",
                agent=f"{node}:{agent}",
                model=usage.model,
                usage=usage.as_ledger_dict(),
                duration_ms=int(elapsed_s * 1000),
                kind="blueprint",
                phase=self.phase,
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
            # PER-STAGE, NOT JUST THE TOTAL. The run already records what every
            # node spent (see `render`); exposing it in the reachable payload is
            # what lets a caller answer "what did the schema stage cost?" without
            # the terminal table (QA D-06 — per-stage tokens/cost were captured
            # but never surfaced through the API).
            "perNode": [
                {
                    "node": e["node"],
                    "model": e["model"],
                    "inputTokens": e["input_tokens"],
                    "outputTokens": e["output_tokens"],
                    "tokens": e["input_tokens"] + e["output_tokens"],
                    "cost_usd": e["cost_usd"],
                    "elapsed_s": round(e["elapsed_s"], 1),
                }
                for e in self.entries
            ],
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
    # The same argument as `database`, one level up: `data_model` names the
    # entity and what it is for, and this authors the columns of ONE of them
    # against that. Measured at 284s for a first call on a five-field entity —
    # longer than `database` was before it was tuned — while the two repair
    # calls that followed took ~60s each, because a repair carries the
    # finding and has something concrete to do. It fans out per entity, so
    # the ceiling is paid once per record rather than once per build.
    "entity_fields": "medium",
    # Tests are enumerated from what the Blueprint already claims, not invented.
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
#: Effort by AGENT, for the ones that are not a node: the reviewer that
#: looks at each page as it is written (`page_look`) gives a verdict on two
#: screenshots against a contract — not a design from nothing. Measured on
#: one list page: `high` 42s and 3,184 output tokens, `medium` 30s and 1,929,
#: the same score and the same five issues.
EFFORT_BY_AGENT: dict[str, str] = {
    "page_reviewer": "medium",
}

MAX_TOKENS_BY_NODE: dict[str, int] = {
    # Names the entities and their relationships without a field; the 64k
    # the single call needed went on fields, which `entity_fields` writes one
    # entity at a time inside the default.
    "data_model": 32000,
    # Declares the page set without the contracts; the 64k the single call
    # needed went on contracts, which `page_details` writes per feature.
    #
    # BACK TO 64k, BECAUSE THE SLOT LIST GROWS WITH THE APPLICATION. The table
    # above already recorded this node reaching 32,000 once. On UAT a 23-entity
    # laboratory app offered 24 slots in a 19,570-character question, and the
    # model reasoned through the whole 32,000 without writing a single page —
    # twice, failing the node and skipping every node after it. Unused headroom
    # is free; this failure cost the entire build.
    "page_contracts": 64000,
    "security": 64000,
    # Declares thirty-odd workflows without their steps; the 64k the single
    # call needed went on step graphs, which `workflow_steps` now writes one
    # workflow at a time inside the default.
    "workflows": 32000,
    # One page's thinking plus two whole files — a record workspace's view
    # runs to several hundred lines — and a compile round re-sends the code.
    # 48k ran out on a fifteen-fact record page (0l133sp2); headroom is free.
    "page_code": 64000,
}


#: The budget a retry gets after a reply that was all reasoning and no answer.
NO_ANSWER_RETRY_TOKENS = 64000


def after_no_answer(client: Any, feedback: str) -> Any:
    """The client for a retry of a call that thought until its budget ran
    out and wrote nothing: less effort and more room. Asking again at the same
    effort and budget got the same nothing (UAT twice; 0l133sp2's /rentals/[id],
    a record page with fifteen facts and ten workflows, spent 48,000 tokens
    reasoning). A reply CUT OFF mid-answer (`Truncated`) is the same shape
    one step later: the budget went on reasoning and the answer did not fit
    in what was left. Any other retry, or a client that has no effort to
    lower, is returned as it is."""
    import dataclasses

    if not str(feedback or "").startswith(("NoAnswer", "Truncated")) \
            or not dataclasses.is_dataclass(client) or not hasattr(client, "effort"):
        return client
    # ALL THE WAY DOWN, NOT ONE NOTCH. A notch was measured and is not
    # enough: a Calculator page spent its whole budget reasoning at `high`,
    # and the retry — at `medium` — spent the whole budget again. A reply
    # that never starts is not improved by thinking slightly less; the cure
    # is to write first. `low` still reasons, it just does not deliberate
    # its way past the point of writing anything down.
    lower = "low"
    return dataclasses.replace(client, effort=lower,
                               max_tokens=max(int(getattr(client, "max_tokens", 0) or 0), NO_ANSWER_RETRY_TOKENS))


#: One notch down, never below `low`.
_LOWER_EFFORT = {"max": "xhigh", "xhigh": "high", "high": "medium", "medium": "low", "low": "low"}


def for_repair(client: Any, spec: Any) -> Any:
    """The client for an observer repair: the node's own, one effort notch
    lower.

    A REPAIR IS NOT A FIRST DRAFT. It carries the findings — this entity has
    no unique key on the pair, this workflow never stores the embedding — and
    edits an answer that was already accepted. Measured on HippieKit
    (2026-09-21): one workflow repair took 280s at the node's `high`, and the
    whole `workflow_steps` node waited on it; `entity_fields` repairs at
    `medium` took ~60s. What the thinking buys on a first pass — deciding the
    shape — the repair is handed. A retry after a refusal is not a repair and
    keeps the node's effort: its answer was never accepted."""
    import dataclasses

    if not getattr(spec, "repair", False) or not dataclasses.is_dataclass(client) \
            or not hasattr(client, "effort"):
        return client
    return dataclasses.replace(client, effort=_LOWER_EFFORT.get(str(client.effort), client.effort))


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
        by_agent={
            agent: AnthropicModel(model=model, effort=effort, reasoning=reasoning)
            for agent, effort in EFFORT_BY_AGENT.items()
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

    def _record_composer_usage(spec: TaskSpec, out: dict, elapsed: float) -> None:
        """The composer calls the model itself; its cost reached no ledger,
        so page composition — the dominant cost of a build — was missing from
        every per-application figure. The MCP now reports it and it is
        recorded here as the page's own entry, `a2ui_pages:compose`."""
        got = out.get("usage") if isinstance(out, dict) else None
        if usage is None or not got or not isinstance(got, dict):
            return
        try:
            usage.record(
                node=spec.node, agent=f"{spec.agent}:compose",
                usage=Usage(model=str(got.get("model") or ""),
                            input_tokens=int(got.get("input_tokens") or 0),
                            output_tokens=int(got.get("output_tokens") or 0),
                            cache_read_tokens=int(got.get("cache_read_tokens") or 0),
                            cache_write_tokens=int(got.get("cache_write_tokens") or 0)),
                elapsed_s=elapsed,
                project=str((svc.doc.get("application") or {}).get("id", "")),
            )
        except Exception:  # noqa: BLE001 — the ledger never fails a build
            logger.debug("[a2ui] usage record failed", exc_info=True)

    def _compose_via_a2ui(spec: TaskSpec) -> AgentResult | None:
        """§34 — A2UI composes the page; the agent is what runs if it declines.

        Returns None rather than raising when A2UI does not own this page, so
        the caller falls through to the authoring agent. An unreachable server
        must cost the composition, never the page: this node fans out 34 times
        on a real app, and a run that finished 28 of 32 pages is the reason
        per-subject tolerance exists.
        """
        from services.a2ui_authority import (
            compose_page_via_a2ui, is_standalone, registry_from_blueprint,
        )
        from services.a2ui_ui_composition import shared_context

        with svc.lock:
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
            _provider = str(drawn.get("provider") or "figma")
            _tool_label = {"uxpilot": "UX Pilot design", "figma": "Figma frame"}.get(
                _provider, f"{_provider} design")
            tell(reasoning, f"Building {page.get('route')} from its {_tool_label}.",
                 "step", spec.node)
            return AgentResult(
                task_id=spec.task_id,
                agent=spec.agent,
                proposals=[ArtifactProposal(
                    section="pageLayouts",
                    natural_key=spec.subject,
                    body={"page": spec.subject,
                          "root": _as_template(drawn["root"]),
                          "composedBy": _provider,
                          "dataSources": drawn["dataSources"],
                          # THE FRAME'S SIZE TRAVELS WITH THE TREE. `compose`
                          # returns it and `FigmaCanvas` scales by it, but
                          # nothing between them carried it: a projected app
                          # had no `_figmaCanvas`, so a 3902px frame rendered
                          # cropped instead of scaled. Absent for a frame with
                          # no recorded size, which composes flowed anyway.
                          **({"canvas": drawn["canvas"]} if drawn.get("canvas") else {}),
                          "rationale": (
                              f"built from {_tool_label} "
                              f"{page.get('figmaFrame')} (§48)"),
                          "requirements": list(page.get("requirements") or [])},
                )],
                confidence=0.95,
            )
        # THE DESIGNER THE USER CHOSE. `application.uiDesigner` (or the
        # page's own `designedBy`) says whether UX Pilot generates this page
        # from its brief. A drawn frame still wins above: a screen a person
        # designed is the thing that was designed, whoever else was asked.
        # See docs/plans/2026-09-13-ux-pilot-page-generation.md.
        from services.uxpilot import generate as uxpilot_pages

        fallback_note = ""
        if uxpilot_pages.designer_for(svc.doc, page) == "uxpilot":
            tell(reasoning, f"Asking UX Pilot to design {page.get('route')}.",
                 "step", spec.node)
            outcome = uxpilot_pages.compose(
                svc, page, app_root=Path(svc.output_dir) / "app",
                feedback=spec.feedback or "")
            if outcome.root is not None:
                tell(reasoning,
                     f"Built {page.get('route')} from UX Pilot design "
                     f"{outcome.design_id or '(unnamed)'}"
                     + (" (reused; brief unchanged)." if outcome.reused else "."),
                     "step", spec.node)
                rationale = (f"generated by UX Pilot (design {outcome.design_id}) "
                             f"from the page brief (§34)")
                if outcome.warnings:
                    rationale += "; unbound: " + "; ".join(outcome.warnings)
                return AgentResult(
                    task_id=spec.task_id,
                    agent=spec.agent,
                    proposals=[ArtifactProposal(
                        section="pageLayouts",
                        natural_key=spec.subject,
                        body={"page": spec.subject,
                              "root": _as_template(outcome.root),
                              "composedBy": "uxpilot",
                              "dataSources": list(outcome.data_sources),
                              "rationale": rationale,
                              "requirements": list(page.get("requirements") or [])},
                    )],
                    confidence=0.95,
                    issues=list(outcome.warnings),
                )
            # THE USER CLICKED UX PILOT AND DID NOT GET IT. Neither a hole
            # nor a silent swap: the page is composed by A2UI below and the
            # layout says so, so the mismatch with `designedBy` is visible.
            fallback_note = (f"UX Pilot could not design this page ({outcome.reason}); "
                             f"composed by the Forge UI Designer instead")
            tell(reasoning, f"{fallback_note} for {page.get('route')}.", "step", spec.node)

        # A TOOL GOES STRAIGHT TO THE COMPOSER THAT CAN EXPRESS ONE.
        #
        # A self-contained screen is made of `clientState` and `clientAction`,
        # and the A2UI protocol has no word for either — it describes surfaces
        # over a data model, which is exactly what a tool does not have. So
        # A2UI cannot compose one, and the tool floor will refuse whatever it
        # returns: a guaranteed decline at roughly 135 seconds, three times on
        # the calculator build, before the page reached the author that could
        # do it.
        #
        # Returning None here is the ordinary "A2UI did not take this page"
        # answer the caller already handles — the LLM page author picks it up,
        # and its prompt was taught the vocabulary.
        if is_standalone(page.get("pattern") or "", page):
            tell(reasoning,
                 f"{page.get('route')} is a self-contained tool — composing it "
                 f"directly, since its values live on the screen.",
                 "step", spec.node)
            spec.feedback = (
                f"{spec.feedback}\n\n" if spec.feedback else ""
            ) + (
                "This screen is a self-contained tool: it is about no entity "
                "and shows no stored records. Declare the values it keeps on "
                "screen in `clientState` and change them with `clientAction`; "
                "do not give it a data source, a workflow or a table."
            )
            return None

        # Read under the lock, compose outside it: the context is a slice of
        # the document, the composition is minutes of network.
        with svc.lock:
            context = shared_context(svc.doc)
            registry = registry_from_blueprint(svc.doc)
        t0 = time.monotonic()
        try:
            out = compose_page_via_a2ui(
                svc.output_dir, page["route"], page.get("pattern") or "",
                shared_context=context,
                page_id=spec.subject,
                registry=registry,
                presentation=page.get("presentation") or "page",
                progress=reasoning,
                # The retry's whole point. `spec.feedback` carries the
                # validator's message from the attempt that was refused, and
                # this path re-composed with A2UI before the authoring agent
                # could read it — so on a page A2UI owns, the correction
                # reached nobody.
                feedback=spec.feedback or "",
                contract=page,
                # WHAT THIS CALL IS FOR. Smith sets a brief when a
                # conversation asks for one page; without it the composer saw
                # only the page contract and the domain, so "not that — a
                # simple arithmetic calculator" re-composed the identical
                # screen from the identical prompt.
                brief=getattr(spec, "brief", "") or "",
            )
        except Exception as exc:  # noqa: BLE001 — composition, never the build
            logger.warning("[a2ui] %s: %s", spec.subject, exc)
            return None
        _record_composer_usage(spec, out, time.monotonic() - t0)
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
            if fallback_note:
                # The authoring agent writes its own rationale; the only way
                # the fallback stays visible on its layout is through what it
                # is told.
                spec.feedback = (
                    f"{spec.feedback}\n\n" if spec.feedback else ""
                ) + f"{fallback_note}. Say so in the rationale."
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
                      "rationale": "composed by A2UI (§34)"
                                   + (f"; {fallback_note}" if fallback_note else ""),
                      "requirements": list(page.get("requirements") or [])},
            )],
            confidence=0.95,
        )

    def _patch_page(spec: TaskSpec) -> AgentResult | None:
        """A repair of a page that already has an accepted tree is an edit
        of that tree (see ``page_patch``); ``None`` means compose in full."""
        from services.blueprint.page_patch import patch_page_layout
        from services.llm_client import tell
        client = (model.for_task(spec.node, spec.agent)
                  if isinstance(model, ModelRouter) else model)
        try:
            return patch_page_layout(
                svc, spec, client, usage=usage,
                tell=lambda msg: tell(reasoning, msg, "step", spec.node))
        except Exception as exc:  # noqa: BLE001 — a patch that breaks is a compose
            logger.warning("[patch] %s: %s", spec.subject, exc)
            return None

    def _edit_repair(spec: TaskSpec) -> AgentResult | None:
        """An observer repair as edits to the accepted answer (see
        ``artifact_patch``); ``None`` means rewrite in full, as before."""
        from services.blueprint.artifact_patch import patch_node_output
        from services.blueprint.orchestrator import DAG

        client = for_repair(model.for_task(spec.node, spec.agent)
                            if isinstance(model, ModelRouter) else model, spec)
        try:
            with svc.lock:
                system, context = build_prompt(
                    svc.doc, spec.node,
                    inline_schema=not getattr(client, "enforces_schema", True),
                    subject=spec.subject, feedback="", references=[],
                    output_dir=svc.output_dir, brief="", agent=spec.agent,
                )
                project = str(svc.doc.get("application", {}).get("id", ""))
            result = patch_node_output(
                spec, client, system=system, produces=DAG[spec.node].produces,
                task_id=spec.task_id, context=context, usage=usage,
                project=project, refused=not getattr(spec, "repair", False))
        except Exception as exc:  # noqa: BLE001 — an edit that breaks is a rewrite
            if api_outage(exc):
                raise           # not the edit's fault, and not worth a rewrite call
            logger.warning("[edit-repair] %s: %s", spec.node, exc)
            return None
        if result is None:
            return None
        # The same identity pins a rewrite gets, so an edited fan-out subject
        # still updates only its own artifacts.
        if spec.node == "workflow_steps":
            with svc.lock:
                pin_workflow_identity(svc, spec.subject, result)
        elif spec.node == "page_details":
            with svc.lock:
                pin_page_identity(svc, spec.subject, result)
        elif spec.node == "data_model":
            pin_entity_set(result)
        elif spec.node == "entity_fields":
            with svc.lock:
                pin_entity_identity(svc, spec.subject, result)
        return result

    def _compose_ui(spec: TaskSpec) -> AgentResult:
        """The UI director and the UI engineer (see ``ui_engineer``). Their
        replies are code and prose, not artifact envelopes, and the engineer's
        is compiled before it is returned — so they have their own path."""
        import copy as _copy

        from services.blueprint import ui_engineer
        from services.llm_client import tell

        client = after_no_answer(model.for_task(spec.node, spec.agent)
                                 if isinstance(model, ModelRouter) else model, spec.feedback)
        project = str((svc.doc.get("application") or {}).get("id", ""))

        def record(u: Any, elapsed: float) -> None:
            if usage is not None and u is not None:
                usage.record(node=spec.node, agent=spec.agent, usage=u,
                             elapsed_s=elapsed, project=project)

        with svc.lock:
            doc = _copy.deepcopy(svc.doc)
        if spec.agent == "ui_director":
            t0 = time.monotonic()
            body, u = ui_engineer.compose_direction(doc, client, references=references.paths(svc.output_dir))
            record(u, time.monotonic() - t0)
            return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                               proposals=[ArtifactProposal(section="composition",
                                                           natural_key="composition", body=body)])
        page = next((p for p in doc.get("pages") or [] if str(p.get("id")) == spec.subject), None)
        if page is None:
            raise ValueError(f"{spec.subject} is not a page of this application")
        current = next((row for row in doc.get("pageCode") or []
                        if str(row.get("page")) == spec.subject), None)
        tell(reasoning, f"Writing {page.get('route')} in React.", "step", spec.node)
        # THE PAGE IS LOOKED AT AS IT IS WRITTEN (`page_look`): the reviewer
        # is the page reviewer's tier, and only a client that can see an
        # image can review one.
        critic = (model.for_task("page_look", "page_reviewer") if isinstance(model, ModelRouter) else model)
        if not getattr(critic, "accepts_images", False):
            critic = None
        body, spent = ui_engineer.compose_page(
            doc, page, Path(svc.output_dir) / "app", client,
            feedback=spec.feedback or "", brief=getattr(spec, "brief", "") or "",
            current=current if (spec.feedback or getattr(spec, "brief", "")) else None,
            critic=critic,
            on_look=lambda v: _looked(svc, spec, page, v, reasoning))
        for u, elapsed, *who in spent:
            if usage is not None and u is not None:
                usage.record(node=spec.node, agent=who[0] if who else spec.agent, usage=u,
                             elapsed_s=elapsed, project=project)
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal(section="pageCode",
                                                       natural_key=spec.subject, body=body)])

    def _looked(svc: Any, spec: TaskSpec, page: dict, v: dict, reasoning: Any) -> None:
        """A look's verdict, told to whoever watches: the thoughts and the
        run ledger (from which the panel draws the page's score and picture)."""
        from services.llm_client import tell

        issues = [str(i.get("problem") or "") for i in (v.get("issues") or []) if i.get("problem")]
        tell(reasoning, f"Looked at {page.get('route')}: {v.get('score')}/10 — "
             + ("passed." if v.get("verdict") == "pass" else "sent back: " + "; ".join(issues[:3])),
             "step", spec.node)
        ledger = getattr(svc, "run_ledger", None)
        if ledger is None:
            return
        try:
            ledger.page_look(spec.node, spec.subject, route=str(page.get("route") or ""),
                             attempt=int(v.get("attempt") or 0), score=int(v.get("score") or 0),
                             verdict=str(v.get("verdict") or ""), issues=issues,
                             broken=len(v.get("broken") or []), shots=sorted(v.get("shots") or {}))
        except Exception:  # noqa: BLE001 — the account of the run never ends it
            pass

    def executor(spec: TaskSpec) -> AgentResult:
        if spec.agent in ("ui_director", "ui_engineer"):
            return _compose_ui(spec)
        # A REPAIR EDITS WHAT WAS ACCEPTED, AND A RETRY EDITS WHAT WAS
        # REFUSED. An observer repair carries the accepted answer in
        # `current`; a retry after a contract refusal now carries the refused
        # proposals in it, so a reply the contract turned back for one bad
        # field is fixed by an edit rather than written again from nothing
        # (31 full rewrites in the builds since 2026-09-15, each paid for).
        # The two data-model envelopes are a different reply shape and are
        # off the observer, so an observer repair of them still rewrites; a
        # refused data-model reply has already been parsed into proposals
        # and edits like any other.
        if (spec.feedback and getattr(spec, "current", ())
                and spec.agent != "a2ui_pages"
                and (not getattr(spec, "repair", False) or spec.node not in SCHEMA_BY_NODE)):
            edited = _edit_repair(spec)
            if edited is not None:
                return edited
        if spec.agent == "a2ui_pages" and spec.subject:
            # A REPAIR EDITS; A FIRST PASS COMPOSES. `feedback` is set only on
            # a retry or an observer repair, and only a page with an accepted
            # tree can be edited — a fresh page, or one whose layout the review
            # invalidated, has nothing to patch and composes in full.
            if spec.feedback:
                patched = _patch_page(spec)
                if patched is not None:
                    return patched
            composed = _compose_via_a2ui(spec)
            if composed is not None:
                return composed
        client = for_repair(after_no_answer(
            model.for_task(spec.node, spec.agent)
            if isinstance(model, ModelRouter)
            else model,
            spec.feedback,
        ), spec)
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
        with svc.lock:  # the read; the call below runs without it
            system, user = build_prompt(
                svc.doc, spec.node,
                inline_schema=not getattr(client, "enforces_schema", True),
                subject=spec.subject, feedback=spec.feedback, references=shown,
                output_dir=svc.output_dir, brief=getattr(spec, "brief", "") or "",
                agent=spec.agent,
            )
        last: Exception | None = None

        for attempt in range(repair_attempts + 1):
            prompt = user
            if attempt and isinstance(last, Truncated):
                prompt = (
                    f"{user}\n\nYour previous reply was CUT OFF before it was "
                    f"complete: {last}. It was not wrong; it was too long for "
                    "the room. Write the same answer, complete, with no "
                    "explanation and no repetition — the budget is larger now."
                )
            elif attempt and last:
                prompt = (
                    f"{user}\n\nYour previous reply was rejected: {last}\n"
                    "Return a corrected envelope. Do not explain the mistake."
                )
            t0 = time.monotonic()
            reply_schema = SCHEMA_BY_NODE.get(spec.node, PROPOSAL_SCHEMA)
            try:
                raw = (
                    client(system=system, user=prompt, schema=reply_schema,
                           images=shown)
                    if shown else
                    client(system=system, user=prompt, schema=reply_schema)
                )
            except NoAnswer as exc:
                # Recorded before it surfaces: the call that wrote nothing is
                # the one that spent the most. Not retried here — asking again
                # with the same budget produced the same nothing on UAT, twice.
                if usage is not None and exc.usage is not None:
                    usage.record(
                        node=spec.node, agent=spec.agent, usage=exc.usage,
                        elapsed_s=time.monotonic() - t0,
                        project=str(svc.doc.get("application", {}).get("id", "")),
                    )
                raise
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
                parsed = parse_envelope(text, task_id=spec.task_id,
                                        agent=spec.agent, node=spec.node)
            except MalformedEnvelope as exc:
                if getattr(raw, "stop_reason", None) == "max_tokens":
                    spent_out = getattr(reply_usage, "output_tokens", 0) or 0
                    last = Truncated(
                        f"the reply was cut off at {spent_out:,} output tokens "
                        f"(budget {getattr(client, 'max_tokens', '?')}) before the "
                        "answer was complete", output_tokens=spent_out)
                    # THE RETRY GETS ROOM, NOT THE SAME CUT. Same lever as a
                    # reply that never started: least effort, most budget.
                    client = after_no_answer(client, f"Truncated: {last}")
                    continue
                last = exc
                continue
            if spec.node == "workflow_steps":
                with svc.lock:
                    pin_workflow_identity(svc, spec.subject, parsed)
            elif spec.node == "page_contracts":
                pin_page_set(parsed)
            elif spec.node == "page_details":
                with svc.lock:
                    pin_page_identity(svc, spec.subject, parsed)
                    if spec.attempt >= 2:
                        # The last attempt keeps the facts that resolve: a
                        # content plan with one bad source must not cost the
                        # feature its contracts.
                        from services.blueprint.page_content import drop_unresolved_content
                        for fault in drop_unresolved_content(parsed, svc.doc):
                            logger.warning("[page_details] %s: dropped content — %s", spec.subject, fault)
            elif spec.node == "data_model":
                pin_entity_set(parsed)
            elif spec.node == "entity_fields":
                with svc.lock:
                    pin_entity_identity(svc, spec.subject, parsed)
            return parsed

        if isinstance(last, Truncated):
            raise Truncated(f"{spec.node}: {last}", output_tokens=last.output_tokens)
        raise MalformedEnvelope(f"{spec.node}: {last}")

    # A model executor writes a fan-out's shared prefix to the cache; the
    # scheduler holds the node's other calls until the first has made it
    # readable (see the orchestrator's `_call_warm`).
    executor.warms_prefix = True  # type: ignore[attr-defined]
    return executor

"""ChatAnthropic-backed drop-in for the ``anthropic`` SDK client surface.

LG-1 of the LangGraph migration: the backend's ~28 one-shot LLM call sites
(classifiers, maquette authors, critics, planners' single calls) all used the
raw ``anthropic`` SDK directly. Routing them through LangChain's
``ChatAnthropic`` buys LangSmith tracing (every call becomes a trace span
with tokens + latency once ``LANGSMITH_TRACING=true`` is set) and per-call
model portability, with zero behavioural change at the call sites.

This module intentionally mirrors the *exact* client surface those sites use
— nothing more:

    client = llm_client.AsyncAnthropic(api_key=...)
    resp   = await client.messages.create(model=..., max_tokens=...,
                                          system=..., messages=[...])
    text   = resp.content[0].text

    async with client.messages.stream(...) as s:      # planner/refiner path
        async for chunk in s.text_stream: ...
        final = await s.get_final_message()

Escape hatch: ``FORGE_LEGACY_ANTHROPIC=1`` makes the factories return REAL
``anthropic`` clients — a one-env-var rollback to the pre-migration
transport, mirroring FORGE_LANGGRAPH's role for the agentic runner.

Content passes through verbatim: anthropic-style block lists (including
image blocks for the vision call sites) are valid ChatAnthropic message
content, so multimodal callers need no changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

_DEFAULT_MAX_TOKENS = 4096


# ── response shapes (duck-typed to anthropic's Message) ──────────────────

@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ThinkingBlock:
    """Extended-thinking block — duck-typed to anthropic's (has ``.thinking``,
    no ``.text``, so text extractors that iterate ``hasattr(b, "text")``
    naturally skip it and Smith's reasoning forwarder finds it)."""
    thinking: str
    type: str = "thinking"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class Message:
    content: list[Any] = field(default_factory=list)
    stop_reason: str | None = None
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    role: str = "assistant"


# ── translation helpers ──────────────────────────────────────────────────

def _lc_messages(messages: list[dict], system: Any = None) -> list[Any]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    out: list[Any] = []
    if system:
        out.append(SystemMessage(content=system))
    for m in messages or []:
        role = m.get("role")
        content = m.get("content")
        if role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def _text_of(content: Any) -> str:
    """Blocks → text, whatever shape the blocks arrive in.

    This handled `str` and `dict` blocks only, while `_content_blocks` right
    below constructs anthropic `TextBlock` OBJECTS — so `_to_message` produced
    `[TextBlock(text='OK')]`, neither branch matched, and `complete()` returned
    an EMPTY STRING for every prompt. No exception, valid key, working model:
    every one-shot caller read "" as "the model had nothing to say".
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if p.get("type") == "text":
                    parts.append(str(p.get("text", "")))
            elif getattr(p, "type", None) == "text":
                # TextBlock and anything else attribute-shaped. Non-text blocks
                # (thinking, tool_use) carry no answer and are skipped.
                parts.append(str(getattr(p, "text", "") or ""))
        return "".join(parts)
    return str(content or "")


def _content_blocks(content: Any) -> list[Any]:
    """AIMessage content → anthropic-shaped blocks, thinking preserved in
    API order (thinking first). Plain-text models still yield one TextBlock."""
    if isinstance(content, list):
        blocks: list[Any] = []
        text_parts: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "thinking":
                blocks.append(ThinkingBlock(thinking=str(p.get("thinking", ""))))
            elif isinstance(p, dict) and p.get("type") == "text":
                text_parts.append(str(p.get("text", "")))
            elif isinstance(p, str):
                text_parts.append(p)
        blocks.append(TextBlock(text="".join(text_parts)))
        return blocks
    return [TextBlock(text=_text_of(content))]


def _to_message(ai_msg: Any, model: str) -> Message:
    um = getattr(ai_msg, "usage_metadata", None) or {}
    details = um.get("input_token_details") or {}
    meta = getattr(ai_msg, "response_metadata", None) or {}
    return Message(
        content=_content_blocks(ai_msg.content),
        stop_reason=meta.get("stop_reason"),
        model=model,
        usage=Usage(
            input_tokens=int(um.get("input_tokens") or 0),
            output_tokens=int(um.get("output_tokens") or 0),
            cache_read_input_tokens=int(details.get("cache_read") or 0),
            cache_creation_input_tokens=int(details.get("cache_creation") or 0),
        ),
    )


#: Time between chunks, not total elapsed — see `_anthropic` in
#: `blueprint/executors.py` for why that distinction is what makes a bound
#: safe here. Every caller passed `timeout=None` and nothing supplied a
#: default, so a Smith turn whose stream went silent waited forever: the
#: `approve` step hung three separate runs this way, on briefs from 357 bytes
#: to 1.15MB, which is how we learned it was not a size problem.
DEFAULT_READ_TIMEOUT_S = 300.0


def _chat_model(api_key: str | None, *, model: str, max_tokens: int,
                temperature: float | None, timeout: float | None,
                thinking: dict | None = None):
    from langchain_anthropic import ChatAnthropic
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
    if api_key:
        kwargs["api_key"] = api_key
    if temperature is not None:
        kwargs["temperature"] = temperature
    kwargs["timeout"] = DEFAULT_READ_TIMEOUT_S if timeout is None else timeout
    kwargs["max_retries"] = 3
    if thinking is not None:
        # Anthropic extended thinking — ChatAnthropic forwards this verbatim.
        kwargs["thinking"] = thinking
    return ChatAnthropic(**kwargs)


# ── streaming (anthropic's `async with client.messages.stream(...)`) ─────

class _AsyncStream:
    def __init__(self, api_key: str | None, kwargs: dict):
        self._api_key = api_key
        self._kwargs = kwargs
        self._parts: list[str] = []
        self._final_chunk: Any = None

    async def __aenter__(self) -> "_AsyncStream":
        model = self._kwargs.pop("model")
        max_tokens = self._kwargs.pop("max_tokens", _DEFAULT_MAX_TOKENS)
        system = self._kwargs.pop("system", None)
        messages = self._kwargs.pop("messages", [])
        temperature = self._kwargs.pop("temperature", None)
        timeout = self._kwargs.pop("timeout", None)
        self._model_name = model
        chat = _chat_model(self._api_key, model=model, max_tokens=max_tokens,
                           temperature=temperature, timeout=timeout)
        self._aiter = chat.astream(_lc_messages(messages, system))
        return self

    async def __aexit__(self, *exc: Any) -> None:
        aclose = getattr(self._aiter, "aclose", None)
        if aclose:
            await aclose()

    @property
    async def text_stream(self) -> AsyncIterator[str]:
        async for chunk in self._aiter:
            # Aggregate chunks so get_final_message sees the terminal
            # metadata (stop_reason + usage arrive on the last chunk).
            # `+` is only defined for AIMessageChunk — full AIMessage
            # addition builds a ChatPromptTemplate — so fall back to
            # keeping the latest chunk when aggregation isn't possible.
            from langchain_core.messages import AIMessageChunk
            if isinstance(chunk, AIMessageChunk) and \
                    isinstance(self._final_chunk, AIMessageChunk):
                # Chunk addition merges usage_metadata + response_metadata.
                # (Full AIMessage `+` silently builds a ChatPromptTemplate,
                # so gate on the chunk type explicitly.)
                self._final_chunk = self._final_chunk + chunk
            else:
                self._final_chunk = chunk
            text = _text_of(chunk.content)
            if text:
                self._parts.append(text)
                yield text

    async def get_final_message(self) -> Message:
        # Text always comes from the accumulated stream — the final chunk
        # only reliably carries metadata (stop_reason / usage), and on
        # non-chunk models it holds just the LAST piece, not the whole.
        full_text = "".join(self._parts)
        if self._final_chunk is not None:
            msg = _to_message(self._final_chunk, self._model_name)
            msg.content = [TextBlock(text=full_text)]
            return msg
        return Message(content=[TextBlock(text=full_text)],
                       model=self._model_name)


# ── client surface ───────────────────────────────────────────────────────

class _AsyncMessages:
    def __init__(self, api_key: str | None):
        self._api_key = api_key

    async def create(self, *, model: str, max_tokens: int = _DEFAULT_MAX_TOKENS,
                     messages: list[dict], system: Any = None,
                     temperature: float | None = None,
                     timeout: float | None = None,
                     thinking: dict | None = None, **_: Any) -> Message:
        chat = _chat_model(self._api_key, model=model, max_tokens=max_tokens,
                           temperature=temperature, timeout=timeout,
                           thinking=thinking)
        ai = await chat.ainvoke(_lc_messages(messages, system))
        return _to_message(ai, model)

    def stream(self, **kwargs: Any) -> _AsyncStream:
        return _AsyncStream(self._api_key, dict(kwargs))


class _SyncMessages:
    def __init__(self, api_key: str | None):
        self._api_key = api_key

    def create(self, *, model: str, max_tokens: int = _DEFAULT_MAX_TOKENS,
               messages: list[dict], system: Any = None,
               temperature: float | None = None,
               timeout: float | None = None,
               thinking: dict | None = None, **_: Any) -> Message:
        chat = _chat_model(self._api_key, model=model, max_tokens=max_tokens,
                           temperature=temperature, timeout=timeout,
                           thinking=thinking)
        ai = chat.invoke(_lc_messages(messages, system))
        return _to_message(ai, model)


class _AsyncClient:
    def __init__(self, api_key: str | None = None):
        self.messages = _AsyncMessages(api_key)


class _SyncClient:
    def __init__(self, api_key: str | None = None):
        self.messages = _SyncMessages(api_key)


def _legacy() -> bool:
    return os.environ.get("FORGE_LEGACY_ANTHROPIC") == "1"


def AsyncAnthropic(api_key: str | None = None, **kwargs: Any):
    """Factory matching ``anthropic.AsyncAnthropic(api_key=...)``."""
    if _legacy():
        import anthropic  # type: ignore[import-not-found]
        return anthropic.AsyncAnthropic(api_key=api_key, **kwargs)
    return _AsyncClient(api_key)


def Anthropic(api_key: str | None = None, **kwargs: Any):
    """Factory matching ``anthropic.Anthropic(api_key=...)``."""
    if _legacy():
        import anthropic  # type: ignore[import-not-found]
        return anthropic.Anthropic(api_key=api_key, **kwargs)
    return _SyncClient(api_key)

# ── One-shot completion ─────────────────────────────────────────────────────
# Two modules import this (`brief_from_screenshot`, `montage_composition`) and
# neither could ever have run: the symbol did not exist, so both raised
# ImportError the first time their live path executed. Their unit tests all
# inject `llm=`, which is why it stayed hidden. Restored here rather than in
# each caller so there is one place that knows how a one-shot is issued.

_ONE_SHOT_MODEL = os.environ.get("FORGE_ONESHOT_MODEL", "claude-sonnet-4-6")


# ── extended thinking ───────────────────────────────────────────────────────
# WHICH BLOCK A MODEL ACCEPTS IS A FACT ABOUT THE TRANSPORT, so it lives with
# the transport. `agents.fix_chat_agent` asked the same question for the ReAct
# loop and answered it locally; two tables of model prefixes drift the moment
# one of them is updated for a new release, and the symptom is a 400 from
# whichever call site was not updated.

#: Models with extended thinking at all. Prefix match, so dated variants
#: (``…-20260215``) all pass.
_THINKING_MODEL_PREFIXES: tuple[str, ...] = (
    "claude-sonnet-4-5", "claude-sonnet-4-6", "claude-sonnet-5",
    "claude-opus-4", "claude-opus-5", "claude-fable-5",
)

#: Of those, the ones that take ``{"type": "adaptive"}`` and REJECT
#: ``budget_tokens`` outright (400) — everything from the 4.6 generation on.
#: Adaptive lets the model decide how long to think per turn, which is what
#: makes thinking affordable interactively.
_ADAPTIVE_THINKING_PREFIXES: tuple[str, ...] = (
    "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8", "claude-opus-5",
    "claude-sonnet-4-6", "claude-sonnet-5", "claude-fable-5",
)

#: Reasoning headroom for the pre-4.6 models that still take an explicit
#: budget, and the headroom added to ``max_tokens`` on the adaptive path,
#: where the cap covers thinking and output together.
THINKING_HEADROOM_TOKENS = 4096


def supports_thinking(model: str) -> bool:
    if not isinstance(model, str) or not model.strip():
        return False
    return any(model.strip().startswith(p) for p in _THINKING_MODEL_PREFIXES)


def thinking_block_for(model: str) -> dict | None:
    """The ``thinking`` request block for this model, or None when it has none.

    TWO FORMS, AND SENDING THE WRONG ONE IS A 400 that names neither the model
    nor the block. `budget_tokens` is how thinking was requested before the 4.6
    generation and is rejected from 4.7 on; `adaptive` is the current form.
    """
    if not supports_thinking(model):
        return None
    if any(model.strip().startswith(p) for p in _ADAPTIVE_THINKING_PREFIXES):
        return {"type": "adaptive"}
    return {"type": "enabled", "budget_tokens": THINKING_HEADROOM_TOKENS}


def tell(sink: Any, text: str, kind: str = "reasoning",
         node: str = "") -> None:
    """Report one line to whoever is watching, if anyone is.

    TWO KINDS ON ONE CHANNEL. `reasoning` is the model thinking; `step` is
    deterministic work naming itself — "Regenerating the frontend". They read
    differently and must LOOK different, or the projection step renders as
    something the model thought, which is a small lie told repeatedly.

    A sink taking one argument gets one argument. Every existing caller passes
    `list.append` or a plain lambda, and none of them should have to grow a
    parameter to say they only ever hear reasoning.
    """
    if sink is None:
        return
    try:
        arity = _arity(sink)
        if arity >= 3:
            sink(text, kind, node)
        elif arity == 2:
            sink(text, kind)
        else:
            sink(text)
    except Exception:  # noqa: BLE001 — reporting the work must never fail it
        pass


def _arity(fn: Any) -> int:
    import inspect

    try:
        return len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return 1


class ReasoningSink:
    """Thinking deltas in, readable lines out.

    A model streams reasoning a few tokens at a time. Forwarding each delta as
    its own event gives the reader a stuttering column of fragments — "The",
    " route", " /" — which is motion without meaning; buffering the whole reply
    gives one wall of text at the end, which is not streaming at all. Neither
    is what "show me what it is thinking" asks for.

    So deltas accumulate and flush at a sentence boundary once there is enough
    to be worth reading. The reader gets whole thoughts, as they are had.

    `close()` flushes the remainder — reasoning rarely ends on a full stop, and
    a dropped tail would silently lose the conclusion, which is the sentence
    that mattered.
    """

    #: Below this a "sentence" is usually an abbreviation or a list marker.
    MIN_CHARS = 60

    def __init__(self, emit: Any, *, min_chars: int = MIN_CHARS) -> None:
        self._emit = emit
        self._min = min_chars
        self._buf: list[str] = []

    def feed(self, delta: str) -> None:
        if not isinstance(delta, str) or not delta:
            return
        self._buf.append(delta)
        text = "".join(self._buf)
        cut = max(text.rfind(". "), text.rfind(".\n"), text.rfind("\n\n"))
        if cut >= self._min:
            self._flush(text[:cut + 1], keep=text[cut + 1:])

    def close(self) -> None:
        self._flush("".join(self._buf), keep="")

    def _flush(self, text: str, *, keep: str) -> None:
        self._buf = [keep] if keep else []
        if not text.strip():
            return
        try:
            self._emit(text.strip())
        except Exception:  # noqa: BLE001 — showing the reasoning must never
            pass          # be able to fail the turn that is producing it


def _thinking_of(content: Any) -> list[str]:
    """The reasoning in a reply, in order. Empty when the model did none."""
    out: list[str] = []
    for p in content if isinstance(content, list) else []:
        if isinstance(p, dict):
            if p.get("type") == "thinking":
                text = str(p.get("thinking") or "")
        else:
            text = str(getattr(p, "thinking", "") or "")
        if text.strip():
            out.append(text)
    return out


def complete(*, system: Any = None, messages: list[dict] | None = None,
             content: Any = None, model: str | None = None,
             max_tokens: int = _DEFAULT_MAX_TOKENS,
             temperature: float | None = None,
             timeout: float | None = None,
             reasoning_callback: Any = None) -> str:
    """Run one prompt, return the response text.

    Accepts either a full ``messages`` list or a bare ``content`` payload
    (string or Anthropic content blocks) that is wrapped into a single user
    turn — vision callers build blocks, prose callers pass a string.

    ``reasoning_callback`` asks for extended thinking and hands each reasoning
    block to the caller before the text is returned. Passing it is the whole
    difference between a one-shot that reasons privately and one whose caller
    can show the user why it answered as it did; every block the transport
    needs — ThinkingBlock, `_content_blocks` preserving it, `_chat_model`
    forwarding the request — was already here and nothing asked for it.
    """
    if messages is None:
        if content is None:
            raise ValueError("complete() needs messages= or content=")
        messages = [{"role": "user", "content": content}]

    use = model or _ONE_SHOT_MODEL
    thinking = thinking_block_for(use) if reasoning_callback is not None else None
    if thinking is not None:
        # STREAMED, NOT DELIVERED AT THE END. `create` returns once the whole
        # reply exists, so the reasoning arrived in a single burst after the
        # wait it was supposed to fill. Streaming is what makes it reasoning
        # you can watch rather than a transcript of reasoning already done.
        return _complete_streaming(
            model=use, max_tokens=max_tokens + THINKING_HEADROOM_TOKENS,
            messages=messages, system=system, timeout=timeout,
            thinking=thinking, reasoning_callback=reasoning_callback)

    msg = _SyncMessages(None).create(
        model=use,
        # The cap covers thinking AND output together on the adaptive path, so
        # asking for reasoning without raising it buys the reasoning at the
        # answer's expense — and a truncated reply parses as a failed one.
        max_tokens=max_tokens + (THINKING_HEADROOM_TOKENS if thinking else 0),
        messages=messages, system=system,
        # Extended thinking requires temperature=1.0; the API rejects other
        # values when the thinking block is present.
        temperature=1.0 if thinking else temperature,
        timeout=timeout, thinking=thinking)

    if reasoning_callback is not None:
        for chunk in _thinking_of(msg.content):
            try:
                reasoning_callback(chunk)
            except Exception:  # noqa: BLE001 — showing the reasoning must
                pass          # never be able to fail the turn producing it
    return _text_of(msg.content)



def _complete_streaming(*, model: str, max_tokens: int, messages: list[dict],
                        system: Any, timeout: float | None,
                        thinking: dict, reasoning_callback: Any) -> str:
    """One prompt, streamed, with the reasoning forwarded as it is produced.

    Returns the same thing `complete` returns — the answer text — so the caller
    cannot tell which path ran except by when the reasoning showed up.
    """
    chat = _chat_model(None, model=model, max_tokens=max_tokens,
                       # Extended thinking requires temperature=1.0; the API
                       # rejects other values when the block is present.
                       temperature=1.0, timeout=timeout, thinking=thinking)
    sink = ReasoningSink(reasoning_callback)
    parts: list[str] = []
    try:
        for chunk in chat.stream(_lc_messages(messages, system)):
            for block in (chunk.content if isinstance(chunk.content, list)
                          else [chunk.content]):
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    kind = block.get("type")
                    if kind == "thinking":
                        sink.feed(str(block.get("thinking") or ""))
                    elif kind == "text":
                        parts.append(str(block.get("text") or ""))
    finally:
        # The tail matters most — reasoning rarely ends on a full stop, and the
        # last sentence is usually the conclusion. Flushed even when the stream
        # raises, so a failed call still shows how far the thinking got.
        sink.close()
    return "".join(parts)

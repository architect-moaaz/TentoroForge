"""Drop-in replacement for ``claude_agent_sdk.query`` that runs agentic agents on the
Anthropic SDK (reliable, ~seconds/turn) instead of the bundled CLI, which wedges/hangs
under subscription-auth throttle (the contract/schema/api/auth agents kept stalling).

It implements the file tools the agents use (Write / Read / Glob / Edit) in-process
against ``options.cwd`` and yields the SAME ``claude_agent_sdk`` message types the SSE
layer already consumes (AssistantMessage → Text/ToolUse blocks, then ResultMessage), so
callers swap only their import. Falls back to the real bundled-CLI query when no API key.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator

from services.agent_messages import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

logger = logging.getLogger(__name__)

# Terminal billing/credit phrases. When the Anthropic API rejects a call with
# one of these, retrying or degrading to stubs is pointless — the whole run
# must halt and surface a clear "out of credits" message. (Deliberately narrow:
# excludes transient "rate limit"/"overloaded" errors, which SHOULD degrade.)
_TERMINAL_BILLING_PHRASES = (
    "credit balance",
    "balance is too low",
    "insufficient credits",
    "credits exhausted",
    "out of credits",
    "purchase credits",
    "plans & billing",
    "billing_error",
)


def _is_terminal_billing_error(text: str) -> bool:
    low = (text or "").lower()
    return any(p in low for p in _TERMINAL_BILLING_PHRASES)

_TOOL_DEFS = [
    {"name": "Write", "description": "Write a file, creating parent dirs and overwriting.",
     "input_schema": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["file_path", "content"]}},
    {"name": "Read", "description": "Read a UTF-8 text file and return its contents.",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}},
                      "required": ["file_path"]}},
    {"name": "Glob", "description": "List files matching a glob pattern (relative to cwd).",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}},
                      "required": ["pattern"]}},
    {"name": "Edit", "description": "Replace the first occurrence of old_string with new_string in a file.",
     "input_schema": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}},
         "required": ["file_path", "old_string", "new_string"]}},
]


def _resolve(cwd: str, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else Path(cwd) / path


def _exec_tool(cwd: str, name: str, inp: dict) -> str:
    try:
        if name == "Write":
            fp = _resolve(cwd, inp["file_path"])
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(inp.get("content", ""), encoding="utf-8")
            return f"Wrote {inp['file_path']}"
        if name == "Read":
            return _resolve(cwd, inp["file_path"]).read_text(encoding="utf-8")[:20000]
        if name == "Glob":
            base = Path(cwd)
            matches = [str(p.relative_to(base)) for p in sorted(base.glob(inp["pattern"]))]
            return "\n".join(matches[:200]) or "(no matches)"
        if name == "Edit":
            fp = _resolve(cwd, inp["file_path"])
            src = fp.read_text(encoding="utf-8")
            old = inp["old_string"]
            if old not in src:
                return f"ERROR: old_string not found in {inp['file_path']}"
            fp.write_text(src.replace(old, inp["new_string"], 1), encoding="utf-8")
            return f"Edited {inp['file_path']}"
    except Exception as e:  # surface the error to the model so it can recover
        return f"ERROR: {e}"
    return f"ERROR: unknown tool {name}"


_CACHE = {"type": "ephemeral"}
# A caller can prefix the prompt with this marker to say "cache everything up to
# the marker" — the large shared context (component contracts, exemplars, registry)
# is identical across a page's skeleton + every region fill, so caching it turns
# ~14 full-context calls per page into 1 full + 13 cache-hits.
CACHE_PREFIX_MARKER = "\x00__FORGE_CACHE_HERE__\x00"


def with_cache_prefix(prefix: str, tail: str) -> str:
    """Return a prompt string that tells query() to cache `prefix` and not `tail`."""
    return f"{prefix}{CACHE_PREFIX_MARKER}{tail}"


def _user_content(prompt: str) -> list[dict] | str:
    """Split a prompt on the cache marker into a cached prefix block + plain tail.
    Falls back to the raw string when no marker is present."""
    if CACHE_PREFIX_MARKER not in prompt:
        return prompt
    prefix, tail = prompt.split(CACHE_PREFIX_MARKER, 1)
    blocks: list[dict] = []
    if prefix:
        blocks.append({"type": "text", "text": prefix, "cache_control": _CACHE})
    blocks.append({"type": "text", "text": tail or " "})
    return blocks


async def query(*, prompt: str, options: Any) -> AsyncIterator[Any]:
    """Mimic ``claude_agent_sdk.query(prompt=…, options=…)``. Agentic loop on the
    Anthropic SDK with in-process file tools; yields claude_agent_sdk messages.

    Prompt caching: the (large, constant) system prompt + tool defs are always
    cached, and a user-prompt prefix marked via with_cache_prefix() is cached too
    — so repeated calls with the same context (page fan-out, chunk region fills,
    retries) pay full input tokens once and cache-read tokens thereafter."""
    # LangGraph is the DEFAULT transport (LG-4 cutover); FORGE_LANGGRAPH=0
    # opts back into the legacy in-process Anthropic-SDK loop below. Every
    # agent through the LangGraph runner (same message contract, same file
    # tools). This flag lives HERE — the one seam all 53 call sites import —
    # so flipping transports never touches an agent. Falls through to the
    # Anthropic-SDK loop below if the LangGraph stack isn't importable.
    if os.environ.get("FORGE_LANGGRAPH", "1") != "0" and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from services.langgraph_agent_runner import query as _lg_query
        except Exception as e:  # noqa: BLE001 — missing deps → legacy path
            logger.warning("[sdk-runner] FORGE_LANGGRAPH=1 but LangGraph "
                           "unavailable (%s) — using Anthropic SDK loop", e)
        else:
            async for m in _lg_query(prompt=prompt, options=options):
                yield m
            return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # LG-4: the claude-agent-sdk bundled-CLI executor is no longer a
        # dependency, so there is no keyless fallback. Fail loudly instead
        # of silently producing an empty stream.
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required — the agent transport runs on "
            "LangGraph/LangChain (no bundled-CLI fallback since LG-4)."
        )

    import anthropic  # type: ignore[import-not-found]

    cwd = getattr(options, "cwd", None) or os.getcwd()
    model = getattr(options, "model", None) or "claude-sonnet-4-6"
    max_turns = getattr(options, "max_turns", None) or 16
    system = getattr(options, "system_prompt", None) or ""
    allowed = set(getattr(options, "allowed_tools", None) or [t["name"] for t in _TOOL_DEFS])
    tools = [t for t in _TOOL_DEFS if t["name"] in allowed] or _TOOL_DEFS

    # Cache the system prompt (constant per agent) and the tool defs (constant).
    system_param: Any = (
        [{"type": "text", "text": system, "cache_control": _CACHE}] if system else system
    )
    tools_param = [dict(t) for t in tools]
    if tools_param:
        tools_param[-1] = {**tools_param[-1], "cache_control": _CACHE}

    client = anthropic.AsyncAnthropic(api_key=api_key)
    messages: list[dict] = [{"role": "user", "content": _user_content(prompt)}]
    t0 = time.time()
    turns = 0
    is_error = False

    for _ in range(max_turns):
        turns += 1
        try:
            resp = await asyncio.wait_for(
                client.messages.create(
                    model=model, max_tokens=16000, system=system_param,
                    tools=tools_param, messages=messages),
                timeout=240,
            )
        except Exception as e:
            logger.warning("[sdk-runner] model call failed on turn %d: %s", turns, e)
            # A credit/billing rejection is terminal: don't limp on to emit empty
            # stubs and then falsely report success. Raise BillingError so the
            # pipeline halts and the user sees a clear "out of credits" message.
            if _is_terminal_billing_error(str(e)):
                from sse_helpers import BillingError, BILLING_ERROR_MSG
                raise BillingError(BILLING_ERROR_MSG) from e
            is_error = True
            yield AssistantMessage(content=[TextBlock(text=f"[sdk-runner] error: {e}")], model=model)
            break

        blocks: list[Any] = []
        assistant_content: list[dict] = []
        tool_results: list[dict] = []
        for b in resp.content:
            if b.type == "text":
                blocks.append(TextBlock(text=b.text))
                assistant_content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                blocks.append(ToolUseBlock(id=b.id, name=b.name, input=b.input))
                assistant_content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                tool_results.append({"type": "tool_result", "tool_use_id": b.id,
                                     "content": _exec_tool(cwd, b.name, b.input)})

        yield AssistantMessage(content=blocks, model=model)
        messages.append({"role": "assistant", "content": assistant_content})

        if resp.stop_reason == "tool_use" and tool_results:
            messages.append({"role": "user", "content": tool_results})
            continue
        break  # end_turn / max_tokens — the agent finished

    yield ResultMessage(
        subtype="success" if not is_error else "error",
        duration_ms=int((time.time() - t0) * 1000),
        duration_api_ms=0, is_error=is_error, num_turns=turns,
        session_id="sdk-runner", total_cost_usd=0.0,
    )

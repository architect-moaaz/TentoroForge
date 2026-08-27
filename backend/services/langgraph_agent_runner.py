"""LangGraph transport for the pipeline's agentic agents (Phase 1 of the
Anthropic-SDK → LangGraph migration).

Drop-in for :func:`services.sdk_agent_runner.query`: same keyword signature,
yields the same ``claude_agent_sdk`` message types (AssistantMessage with
Text/ToolUse blocks, then a terminal ResultMessage), so the SSE layer and all
53 agent call sites are untouched. Selected at runtime by ``FORGE_LANGGRAPH=1``
(sdk_agent_runner.query delegates here when the flag is on).

Internally: a ``langgraph.prebuilt.create_react_agent`` over
``langchain_anthropic.ChatAnthropic`` with the SAME four in-process file tools
(Write / Read / Glob / Edit — implementations reused from sdk_agent_runner so
behaviour cannot drift). What this buys over the hand-rolled loop:

  - LangSmith tracing out of the box (set LANGSMITH_TRACING=true +
    LANGSMITH_API_KEY; every agent step, token count and latency lands in a
    trace tree with zero code here).
  - A checkpointable graph — Phase 2 threads a checkpointer through for
    resumable builds.
  - Model portability — swap ChatAnthropic for any LangChain chat model
    per-agent without touching call sites.

Parity guarantees carried over from sdk_agent_runner:
  - prompt caching: system prompt + tool defs are cache_control-tagged, and a
    ``with_cache_prefix()`` marker in the user prompt splits it into a cached
    prefix block + uncached tail;
  - terminal billing errors raise ``BillingError`` (halts the pipeline with a
    clear out-of-credits message instead of limping on);
  - ``options`` fields honoured: cwd, model, max_turns, system_prompt,
    allowed_tools;
  - the terminal ResultMessage now also carries aggregated ``usage`` (input /
    output / cache tokens) for the build-usage ledger — an upgrade over the
    SDK runner, which reported none.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, AsyncIterator

from services.agent_messages import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from services.sdk_agent_runner import (
    _CACHE,
    _TOOL_DEFS,
    _exec_tool,
    _is_terminal_billing_error,
    _user_content,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 16000
_RESULT_SESSION = "langgraph-runner"


def _build_tools(cwd: str, allowed: set[str]):
    """LangChain StructuredTools wrapping sdk_agent_runner's _exec_tool.

    Built per-call (closures over cwd) so parallel agents writing different
    app dirs never share state. Schemas come from the SAME _TOOL_DEFS the SDK
    runner sends to Anthropic — one source of truth for tool contracts.
    """
    from langchain_core.tools import StructuredTool

    tools = []
    for td in _TOOL_DEFS:
        if td["name"] not in allowed:
            continue

        def _make(name: str):
            def _run(**kwargs: Any) -> str:
                return _exec_tool(cwd, name, kwargs)
            return _run

        tools.append(StructuredTool.from_function(
            func=_make(td["name"]),
            name=td["name"],
            description=td["description"],
            args_schema=td["input_schema"],
        ))
    return tools


def _split_system(system: str) -> Any:
    """System prompt as a cache_control-tagged block (constant per agent)."""
    if not system:
        return None
    from langchain_core.messages import SystemMessage
    return SystemMessage(content=[
        {"type": "text", "text": system, "cache_control": _CACHE},
    ])


def _ai_to_blocks(msg: Any) -> list[Any]:
    """AIMessage → claude_agent_sdk content blocks (TextBlock / ToolUseBlock)."""
    blocks: list[Any] = []
    content = msg.content
    if isinstance(content, str):
        if content.strip():
            blocks.append(TextBlock(text=content))
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, str):
                if part.strip():
                    blocks.append(TextBlock(text=part))
            elif isinstance(part, dict) and part.get("type") == "text":
                if str(part.get("text", "")).strip():
                    blocks.append(TextBlock(text=part["text"]))
            # tool_use parts are surfaced via msg.tool_calls below — skip here
    for tc in getattr(msg, "tool_calls", None) or []:
        blocks.append(ToolUseBlock(
            id=tc.get("id") or "call",
            name=tc.get("name") or "",
            input=tc.get("args") or {},
        ))
    return blocks


def _accumulate_usage(totals: dict[str, int], msg: Any) -> None:
    um = getattr(msg, "usage_metadata", None)
    if not um:
        return
    totals["input_tokens"] += int(um.get("input_tokens") or 0)
    totals["output_tokens"] += int(um.get("output_tokens") or 0)
    details = um.get("input_token_details") or {}
    totals["cache_read_input_tokens"] += int(details.get("cache_read") or 0)
    totals["cache_creation_input_tokens"] += int(details.get("cache_creation") or 0)


async def query(*, prompt: str, options: Any) -> AsyncIterator[Any]:
    """LangGraph agent loop, claude_agent_sdk message stream out."""
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.prebuilt import create_react_agent

    cwd = getattr(options, "cwd", None) or os.getcwd()
    model_name = getattr(options, "model", None) or _DEFAULT_MODEL
    max_turns = getattr(options, "max_turns", None) or 16
    system = getattr(options, "system_prompt", None) or ""
    allowed = set(getattr(options, "allowed_tools", None)
                  or [t["name"] for t in _TOOL_DEFS])

    model = ChatAnthropic(model=model_name, max_tokens=_MAX_TOKENS, timeout=240)
    tools = _build_tools(cwd, allowed)
    agent = create_react_agent(model, tools, prompt=_split_system(system))

    # with_cache_prefix() marker → anthropic-style content blocks with a
    # cache_control-tagged prefix; ChatAnthropic passes them through verbatim.
    user_content = _user_content(prompt)
    inputs = {"messages": [HumanMessage(content=user_content)]}
    # create_react_agent counts one superstep per node visit; a model+tools
    # round trip is 2 supersteps, so max_turns model calls ≈ 2*max_turns + 1.
    config = {"recursion_limit": 2 * max_turns + 1}

    t0 = time.time()
    turns = 0
    is_error = False
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}

    try:
        async for update in agent.astream(inputs, config, stream_mode="updates"):
            for node, payload in (update or {}).items():
                if node != "agent" or not isinstance(payload, dict):
                    continue  # tool results feed the loop; SSE only shows AI steps
                for msg in payload.get("messages") or []:
                    if not isinstance(msg, AIMessage):
                        continue
                    turns += 1
                    _accumulate_usage(usage, msg)
                    blocks = _ai_to_blocks(msg)
                    if blocks:
                        yield AssistantMessage(content=blocks, model=model_name)
    except Exception as e:  # noqa: BLE001
        if _is_terminal_billing_error(str(e)):
            from sse_helpers import BILLING_ERROR_MSG, BillingError
            raise BillingError(BILLING_ERROR_MSG) from e
        # GraphRecursionError (hit recursion_limit) and transient API errors
        # both land here: report like the SDK runner does and let the caller's
        # guards handle the (possibly partial) output.
        logger.warning("[langgraph-runner] agent failed after %d turn(s): %s", turns, e)
        is_error = True
        yield AssistantMessage(
            content=[TextBlock(text=f"[langgraph-runner] error: {e}")],
            model=model_name,
        )

    yield ResultMessage(
        subtype="success" if not is_error else "error",
        duration_ms=int((time.time() - t0) * 1000),
        duration_api_ms=0,
        is_error=is_error,
        num_turns=turns,
        session_id=_RESULT_SESSION,
        total_cost_usd=0.0,
        usage=usage if usage["input_tokens"] or usage["output_tokens"] else None,
    )

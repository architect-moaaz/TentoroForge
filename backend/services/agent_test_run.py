"""The Agent Builder's Test console — a real model call, tools shown but not run.

The console used to answer every message with a canned "[Test mode] simulated
response" and a made-up 50 ms per node, so nothing about the agent could be learned
from it. This runs the agent's compiled definition against the model for real: the
system prompt, the input guardrails, the tool list the model is offered, the real
tokens and the real latency.

What it does NOT do is execute tools. The builder has no signed-in end user of the
generated app, so a tool that reads orders "as the customer" has no customer to be;
and a test message must never create a record or fire a workflow. When the model
asks for a tool, the console stops there and says which tool and with what input —
which is the thing a builder wants to see (did it pick the right tool, did it fill
the arguments). Running the tools end to end is what the generated app's chat does.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from services.agent_runtime_config import compile_agent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pattern(src: str) -> re.Pattern[str]:
    """Same reading of a pattern as the runtime's guardrails.ts: a Python-style `(?i)`
    prefix is accepted, and one that is not a valid regex is taken literally."""
    stripped = re.sub(r"^\(\?i\)", "", src)
    try:
        return re.compile(stripped, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(stripped), re.IGNORECASE)


def check_input(message: str, config: dict[str, Any]) -> str | None:
    """The reason the runtime would refuse this message, or None."""
    rules = config["guardrails"]["input"]
    if len(message) > rules["maxLength"]:
        return f"That message is too long (limit {rules['maxLength']} characters)."
    for p in rules["blockPatterns"]:
        if _pattern(p).search(message):
            return "That message contains something the assistant can't act on."
    return None


def _history(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in items or []:
        role, content = m.get("role"), m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _entry(node: dict[str, Any], status: str, *, started: str, ms: int = 0, tokens: int = 0,
           result: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
    d = node.get("data") or {}
    e: dict[str, Any] = {
        "node_id": node.get("id", ""),
        "node_type": d.get("nodeType") or node.get("type") or "",
        "label": d.get("label") or node.get("id") or "",
        "started_at": started,
        "completed_at": _now(),
        "status": status,
        "duration_ms": ms,
        "tokens_used": tokens,
    }
    if result is not None:
        e["result"] = result
    if error:
        e["error"] = error
    return e


async def run_agent_test(agent_data: dict[str, Any], message: str,
                         history: list[dict[str, Any]] | None = None, *,
                         client: Any = None) -> dict[str, Any]:
    """Run one test message. ``client`` is injectable for tests (anything with
    ``messages.create``); by default a real Anthropic client from ANTHROPIC_API_KEY."""
    compiled = compile_agent(agent_data)
    cfg = compiled.config
    nodes = [n for n in (agent_data.get("nodes") or []) if isinstance(n, dict)]
    started_all = time.perf_counter()
    t0 = _now()

    def kind(n: dict[str, Any]) -> str:
        return (n.get("data") or {}).get("nodeType") or n.get("type") or ""

    def finish(response: str, trace: list[dict[str, Any]], tokens: int, **extra: Any) -> dict[str, Any]:
        return {
            "response": response,
            "trace": trace,
            "total_tokens": tokens,
            "total_duration_ms": int((time.perf_counter() - started_all) * 1000),
            "dry_run": True,
            "warnings": compiled.warnings,
            **extra,
        }

    def skipped(except_kinds: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        return [_entry(n, "skipped", started=t0) for n in nodes if kind(n) not in except_kinds]

    # 1 ── input guardrails, exactly as the runtime would apply them
    refusal = check_input(message, cfg)
    if refusal:
        trace = [
            _entry(n, "failed" if kind(n) == "guardrail" else "skipped", started=t0,
                   error=refusal if kind(n) == "guardrail" else None)
            for n in nodes
        ]
        return finish(refusal, trace, 0, blocked=True, model_called=False)

    # 2 ── the model
    if client is None:
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            return finish(
                "The test console needs a model key. Set ANTHROPIC_API_KEY for the platform and try again.",
                skipped(), 0, model_called=False, error="ANTHROPIC_API_KEY is not set")
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=key)

    tools = [{"name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
             for t in cfg["tools"]]
    model_name = cfg["model"].get("name") or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    req: dict[str, Any] = {
        "model": model_name,
        "max_tokens": cfg["model"]["maxTokens"],
        "system": cfg["systemPrompt"],
        "messages": _history(history) + [{"role": "user", "content": message}],
    }
    if tools:
        req["tools"] = tools
    if cfg["model"].get("temperature") is not None:
        req["temperature"] = cfg["model"]["temperature"]

    sp = next((n for n in nodes if kind(n) == "system_prompt"), None)
    started = _now()
    t_model = time.perf_counter()
    try:
        resp = await client.messages.create(**req)
    except Exception as exc:  # noqa: BLE001 — shown to the builder, who can fix a key or a model name
        trace = [_entry(n, "failed" if n is sp else "skipped", started=started,
                        error=str(exc) if n is sp else None) for n in nodes]
        return finish(f"The model call failed: {exc}", trace, 0, model_called=True, error=str(exc))
    ms = int((time.perf_counter() - t_model) * 1000)
    usage = getattr(resp, "usage", None)
    tokens = int(getattr(usage, "input_tokens", 0) or 0) + int(getattr(usage, "output_tokens", 0) or 0)

    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
    calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]

    # 3 ── what the model wants to do next
    trace: list[dict[str, Any]] = []
    called = {c.name for c in calls}
    for n in nodes:
        k = kind(n)
        if n is sp:
            trace.append(_entry(n, "completed", started=started, ms=ms, tokens=tokens,
                                result={"model": model_name, "stop_reason": getattr(resp, "stop_reason", None)}))
        elif k == "tool":
            tname = ((n.get("data") or {}).get("config") or {}).get("tool_name") or (n.get("data") or {}).get("label")
            match = next((c for c in calls if c.name == re.sub(r"[^A-Za-z0-9_-]+", "_", str(tname)).strip("_")), None)
            if match:
                trace.append(_entry(n, "completed", started=started, result={
                    "dry_run": True, "would_call": match.name, "input": dict(match.input or {}),
                    "note": "Not executed — the test console never runs tools."}))
            else:
                trace.append(_entry(n, "skipped", started=started))
        elif k == "guardrail":
            trace.append(_entry(n, "completed", started=started, result={"input": "passed"}))
        elif k == "memory":
            trace.append(_entry(n, "completed", started=started,
                                result={"history_messages": len(req["messages"]) - 1}))
        else:
            trace.append(_entry(n, "skipped", started=started))

    answer = text
    if calls:
        lines = [f"• {c.name}({', '.join(f'{k}={v!r}' for k, v in (c.input or {}).items())})" for c in calls]
        answer = (text + "\n\n" if text else "") + (
            "[Dry run] The agent wants to call:\n" + "\n".join(lines)
            + "\nTools are not executed in the test console — try the same message in the app to see them run.")
    return finish(answer or "(the model returned no text)", trace, tokens, model_called=True,
                  tool_calls=[{"name": c.name, "input": dict(c.input or {})} for c in calls],
                  model=model_name, unused_tools=sorted(t["name"] for t in cfg["tools"] if t["name"] not in called))

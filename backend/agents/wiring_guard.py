# backend/agents/wiring_guard.py
"""LLM completeness guard — ensure every actionable button is tied to a real
backend (workflow or navigate). Deterministic validation: only apply repairs
referencing a real workflow / real route. Safety net over the deterministic
binding; degrades to no-op without an API key.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_ACTIONABLE = {"Button", "IconButton", "Form"}


def _walk_nodes(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_nodes(v)


def collect_actionable(schema: dict, real_workflows: set | None = None) -> list[dict]:
    """List actionable nodes with a `wired` flag (has workflow/navigate/onClick).

    When ``real_workflows`` is provided, a button is wired only if it navigates,
    has an onClick, or its ``workflow`` is in ``real_workflows``. A button whose
    ``workflow`` is set but not real is flagged ``phantom: True`` and not wired.
    When ``real_workflows`` is None, any ``workflow`` counts as wired (back-compat).
    """
    out: list[dict] = []
    for n in _walk_nodes(schema):
        if isinstance(n, dict) and n.get("type") in _ACTIONABLE:
            p = n.get("props") or {}
            wf = p.get("workflow")
            phantom = bool(wf) and real_workflows is not None and wf not in real_workflows
            if real_workflows is None:
                workflow_ok = bool(wf)
            else:
                workflow_ok = bool(wf) and wf in real_workflows
            wired = bool(workflow_ok or p.get("navigate") or p.get("onClick"))
            out.append({"id": n.get("id"), "label": p.get("label") or p.get("children"),
                        "wired": wired, "phantom": phantom})
    return out


def apply_guard_repairs(schema: dict, repairs: list[dict], *, real_workflows: set,
                        real_routes: set) -> tuple[dict, list[dict]]:
    """Apply only repairs that reference a real workflow or real route.
    Returns (schema, applied_repairs)."""
    by_id = {n.get("id"): n for n in _walk_nodes(schema) if isinstance(n, dict) and n.get("id")}
    applied: list[dict] = []
    for r in repairs or []:
        node = by_id.get(r.get("id"))
        if not node:
            continue
        props = node.setdefault("props", {})
        if r.get("kind") == "workflow" and r.get("workflow") in real_workflows:
            current = props.get("workflow")
            # Fill if absent, or override a phantom (present but not real).
            # Never override a workflow that is already real.
            if not current or current not in real_workflows:
                props["workflow"] = r["workflow"]
                applied.append(r)
        elif r.get("kind") == "navigate" and r.get("to") in real_routes:
            if not props.get("navigate"):
                props["navigate"] = r["to"]
                applied.append(r)
    return schema, applied


_GUARD_PROMPT = """Some buttons on a generated app page have no action wired.
For each UNWIRED actionable button below, decide if it should dispatch a workflow
or navigate. Only use a workflow name from REAL_WORKFLOWS or a route from
REAL_ROUTES. If a button is intentionally inert (UI toggle, export, etc.), omit it.
Return ONLY a JSON array of {id, kind:"workflow"|"navigate", workflow?, to?}.

UNWIRED_BUTTONS:
__BUTTONS__
REAL_WORKFLOWS: __WORKFLOWS__
REAL_ROUTES: __ROUTES__
"""


async def run_wiring_guard(schema: dict, *, real_workflows: set, real_routes: set,
                           call_llm) -> tuple[dict, dict]:
    """Verify completeness; apply only validated repairs. call_llm is an async
    (prompt)->list or None (then no-op). Returns (schema, report)."""
    items = collect_actionable(schema, real_workflows=real_workflows)
    unwired = [i for i in items if not i["wired"]]
    report = {"actionable": len(items), "unwired": len(unwired), "repaired": 0,
              "still_unwired": len(unwired)}
    if not unwired or call_llm is None:
        return schema, report
    try:
        prompt = (_GUARD_PROMPT
                  .replace("__BUTTONS__", json.dumps([{"id": i["id"], "label": i["label"]} for i in unwired]))
                  .replace("__WORKFLOWS__", json.dumps(sorted(real_workflows)))
                  .replace("__ROUTES__", json.dumps(sorted(real_routes))))
        repairs = await call_llm(prompt)
        if not isinstance(repairs, list):
            raise ValueError("guard LLM did not return a list")
        schema, applied = apply_guard_repairs(schema, repairs,
                                              real_workflows=real_workflows, real_routes=real_routes)
        report["repaired"] = len(applied)
        report["still_unwired"] = len(unwired) - len(applied)
    except Exception as exc:  # noqa: BLE001 — guard is best-effort
        logger.warning("wiring guard failed: %s", exc)
    return schema, report


def make_anthropic_guard_llm(*, model: str = "claude-sonnet-4-6", max_tokens: int = 4096):
    """Return an async call_llm(prompt)->list backed by Anthropic. Mirrors
    figma_plan_binding.make_anthropic_call_llm but parses a JSON array."""
    import os

    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = llm_client.AsyncAnthropic(api_key=api_key)

    async def _call(prompt: str) -> list:
        msg = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("no JSON array in LLM response")
        return json.loads(text[start:end + 1])

    return _call

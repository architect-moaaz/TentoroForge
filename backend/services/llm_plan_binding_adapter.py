# backend/services/llm_plan_binding_adapter.py
"""Adapter: build a binding page_intent from an LLM/prompt plan.

The deterministic binding pass (services/schema_binding.apply_bindings) consumes
a page_intent of {file, entity, actions:[{label, workflow, kind}]}. For the LLM
path we source `actions` from the planner-declared `page["actions"]`, falling
back to `plan["api_strategy"][entity]["workflow_actions"]` when present.
"""
from __future__ import annotations

_ALLOWED_KINDS = ("row_action", "page_action")


def _slug(route: str) -> str:
    return (route or "/").strip("/").replace("/", "-") or "home"


def _known_workflows(plan: dict) -> set[str]:
    return {w["name"] for w in (plan.get("workflows") or [])
            if isinstance(w, dict) and w.get("name")}


def _from_page_actions(page: dict, known: set[str]) -> list[dict]:
    out: list[dict] = []
    for a in page.get("actions") or []:
        if not (isinstance(a, dict) and a.get("label")):
            continue
        if a.get("kind") == "navigate" and a.get("to"):
            # Navigate actions need no workflow — they carry a route target.
            out.append({"label": a["label"], "kind": "navigate", "to": a["to"]})
        elif a.get("workflow") in known and a.get("kind") in _ALLOWED_KINDS:
            out.append({"label": a["label"], "workflow": a["workflow"], "kind": a["kind"]})
    return out


def _from_api_strategy(page: dict, plan: dict, known: set[str]) -> list[dict]:
    entity = page.get("entity")
    strat = ((plan.get("api_strategy") or {}).get(entity) or {}) if entity else {}
    out: list[dict] = []
    for wa in strat.get("workflow_actions") or []:
        if not isinstance(wa, dict):
            continue
        trig = wa.get("trigger") or ""
        label = trig.split("button:", 1)[1].strip() if "button:" in trig else None
        workflow = wa.get("workflow")
        if not label or workflow not in known:
            continue
        kind = "row_action" if wa.get("ui_location") == "list_page" else "page_action"
        out.append({"label": label, "workflow": workflow, "kind": kind})
    return out


def build_page_intent(page: dict, plan: dict) -> dict:
    """Return {file, entity, actions} for the binding pass. Prefers
    planner-declared page['actions']; else derives from api_strategy. Drops
    actions whose workflow isn't declared or whose kind is invalid."""
    known = _known_workflows(plan)
    actions = _from_page_actions(page, known)
    if not actions:
        actions = _from_api_strategy(page, plan, known)
    intent = {
        "file": page.get("file") or f"src/schemas/{_slug(page.get('route', ''))}.json",
        "entity": page.get("entity"),
        "actions": actions,
    }
    # Pass through form-binding threading fields when present (set by the
    # pipeline hook) so apply_bindings can run apply_form_bindings and
    # canonicalize_and_guard_workflow_buttons.
    for key in ("_existing_workflows", "_workflow_index", "_status_index",
                "_page_type", "_route"):
        if key in page:
            intent[key] = page[key]
    return intent

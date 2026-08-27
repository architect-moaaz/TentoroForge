# backend/services/figma_plan_binding.py
"""Layer A — enrich the Figma plan with structured binding intent.

Adds top-level data_models[] + workflows[] and per-page entity + actions[]
so the deterministic applier (services/schema_binding.py) can wire schemas.
The enrichment runs at plan-build time, before plan_ready, so the user can
review/correct bindings at approval.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _find_frame(node: Any, frame_id: str) -> dict | None:
    if isinstance(node, dict):
        if node.get("id") == frame_id:
            return node
        for c in node.get("children") or []:
            found = _find_frame(c, frame_id)
            if found:
                return found
    elif isinstance(node, list):
        for c in node:
            found = _find_frame(c, frame_id)
            if found:
                return found
    return None


def _frame_texts(frame: dict | None) -> list[str]:
    out: list[str] = []
    if not frame:
        return out

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("type") == "TEXT" and isinstance(n.get("characters"), str):
                t = n["characters"].strip()
                if t:
                    out.append(t)
            for c in n.get("children") or []:
                _walk(c)
        elif isinstance(n, list):
            for c in n:
                _walk(c)

    _walk(frame)
    return out


def build_binding_analysis_input(plan: dict, file_meta: dict) -> dict:
    """Compact per-page summary (route/name/type + visible text) for the LLM."""
    document = (file_meta or {}).get("document") or {}
    pages = []
    for p in (plan or {}).get("pages") or []:
        frame = _find_frame(document, p.get("figma_node_id")) if p.get("figma_node_id") else None
        pages.append({
            "route": p.get("route"),
            "name": p.get("name"),
            "type": p.get("type"),
            "file": p.get("file"),
            "texts": _frame_texts(frame),
        })
    return {"app_name": (plan or {}).get("name"), "pages": pages}


def merge_binding_analysis(plan: dict, analysis: dict) -> dict:
    """Merge LLM analysis into the plan: set top-level data_models/workflows and
    per-page entity + actions. Drops actions whose workflow isn't declared.
    Returns the same plan dict (mutated) for convenience."""
    analysis = analysis or {}
    models = [m for m in (analysis.get("data_models") or []) if isinstance(m, dict) and m.get("name")]
    workflows = [w for w in (analysis.get("workflows") or []) if isinstance(w, dict) and w.get("name")]
    plan["data_models"] = models
    plan["workflows"] = workflows
    known_wf = {w["name"] for w in workflows}

    by_route = {}
    for ap in analysis.get("pages") or []:
        if isinstance(ap, dict) and ap.get("route"):
            by_route[ap["route"]] = ap

    for page in plan.get("pages") or []:
        ap = by_route.get(page.get("route")) or {}
        page["entity"] = ap.get("entity") if ap.get("entity") else page.get("entity")
        actions = []
        for a in ap.get("actions") or []:
            if (isinstance(a, dict) and a.get("label") and a.get("workflow") in known_wf
                    and a.get("kind") in ("row_action", "page_action")):
                actions.append({"label": a["label"], "workflow": a["workflow"], "kind": a["kind"]})
        page["actions"] = actions
    return plan


_ANALYSIS_PROMPT = """You are wiring a generated app's data + actions.
Given these screens (with their visible text), propose:
- data_models: the entities the screens display, each with fields [{name, type}]
- workflows: the actions buttons should trigger, each {name, description}
- pages: for each screen route, its primary {entity} and {actions:[{label, workflow, kind}]}
  where kind is "row_action" (a button repeated per list row) or "page_action".
Only use workflow names you declared in `workflows`. Use the EXACT button label text.
Return ONLY a JSON object with keys data_models, workflows, pages.

SCREENS:
__SCREENS__
"""


async def enrich_figma_plan_with_bindings(plan: dict, file_meta: dict, *, call_llm) -> dict:
    """Run the binding analysis and merge it into the plan. `call_llm` is an
    async callable (prompt:str) -> dict. On any error, returns the plan with
    empty binding intent (build proceeds; pages just stay unbound)."""
    plan.setdefault("data_models", [])
    plan.setdefault("workflows", [])
    for p in plan.get("pages") or []:
        p.setdefault("actions", [])
    try:
        analysis_input = build_binding_analysis_input(plan, file_meta)
        prompt = _ANALYSIS_PROMPT.replace("__SCREENS__", json.dumps(analysis_input["pages"], indent=1))
        analysis = await call_llm(prompt)
        if not isinstance(analysis, dict):
            raise ValueError("analysis not a dict")
        return merge_binding_analysis(plan, analysis)
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        logger.warning("Figma binding enrichment failed: %s — plan left unbound", exc)
        return plan


def make_anthropic_call_llm(*, model: str = "claude-sonnet-4-6", max_tokens: int = 4096):
    """Return an async call_llm(prompt)->dict backed by Anthropic. Mirrors the
    client construction used in agents/figma_schema_refiner.py."""
    import os

    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = llm_client.AsyncAnthropic(api_key=api_key)

    async def _call(prompt: str) -> dict:
        msg = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object in LLM response")
        return json.loads(text[start:end + 1])

    return _call

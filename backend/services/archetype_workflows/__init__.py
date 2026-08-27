"""Archetype-owned workflow emitters.

An archetype can register a deterministic emitter for one of its named
workflows. When the workflow generator sees a plan.workflows entry whose
name matches (fuzzy) a registered alias for the plan's archetype, the
emitter takes precedence over the planner's step list and the LLM/
heuristic fallback.

This is how the pipeline delivers wired multi-step domain workflows that
depend on runtime primitives (mcp_tool_call, ai_identify_product, etc.)
without hoping the planner authors them correctly step-for-step.

Fuzzy matching matters because the planner names workflows freely — the
same "scan → identify product → get prices" flow arrives as
``ScanProductWorkflow``, ``IdentifyProductWorkflow``,
``ScanIdentifyWorkflow``, etc. The registry lists ALIASES per emitter
and matches by normalized substring (drop non-alnum, lowercase).

Registered emitters must return a full workflow JSON dict of the shape:

    {
      "id": "...",           # slug
      "name": "...",         # human name (same as plan)
      "description": "...",
      "processVariables": [...],
      "definition": {"trigger": {...}, "nodes": [...], "edges": [...]},
    }

Signature:  emit(wf: dict, plan: dict, table_names: set[str], registry: dict|None) -> dict|None
Return None to fall through to the default generator path.
"""
from __future__ import annotations

import re
from typing import Callable

from services.archetype_workflows import visual_product_search as _vps


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]", "", s.lower())


# {archetype_name: [(aliases_normalized, emitter_fn)]}
# Each alias is matched by `_norm(alias) in _norm(workflow_name)` OR
# `_norm(workflow_name) in _norm(alias)` (contains either way). Fuzzy on
# purpose — the planner freely names ScanProductWorkflow,
# IdentifyProductWorkflow, ScanIdentifyProductPricesWorkflow, etc.
_ALIASED: dict[str, list[tuple[tuple[str, ...], Callable]]] = {
    "visual-product-search": [
        (
            (
                "scanproductworkflow",
                "identifyproductworkflow",
                "scanidentifyworkflow",
                "scanidentifyproductworkflow",
                "productscanworkflow",
                "productidentificationworkflow",
                "identifyandpriceworkflow",
                "scanandcompareworkflow",
            ),
            _vps.build_scan_product_workflow,
        ),
        (
            (
                "barcodesearchworkflow",
                "barcodescanworkflow",
                "barcodelookupworkflow",
                "searchbybarcodeworkflow",
                "scanbarcodeworkflow",
                "barcodeworkflow",
            ),
            _vps.build_barcode_search_workflow,
        ),
    ],
}


def find_emitter(archetype: str | None, workflow_name: str | None) -> Callable | None:
    """Return an emitter for (archetype, workflow_name) or None.

    Fuzzy: strips non-alnum from both sides, then checks substring both ways.
    Aliases per emitter cover the common names the planner produces for the
    same domain workflow. Add new aliases as new plans surface them; don't
    tighten the matcher to exact — the planner isn't a deterministic naming
    authority.
    """
    if not archetype or not workflow_name:
        return None
    wf_norm = _norm(workflow_name)
    if not wf_norm:
        return None
    for aliases, fn in _ALIASED.get(archetype, []):
        for alias in aliases:
            if alias in wf_norm or wf_norm in alias:
                return fn
    return None


# Back-compat surface: some callers might inspect EMITTERS as a flat dict.
# Populate with the canonical name per archetype (first alias in each tuple).
EMITTERS: dict[str, dict[str, Callable]] = {
    a: {aliases[0]: fn for aliases, fn in entries}
    for a, entries in _ALIASED.items()
}

"""Shared, module-level LLM-classifier context for the Figma pipeline.

Spec D Wave 5 introduces LLM classifiers that replace the keyword
tables in ``figma_action_classifier``, ``figma_name_classifier``, and
``nav_icon_map``. The classifiers need a *closed vocabulary* the LLM
cannot invent past — real route paths, real workflow names, real
component identifiers. That vocabulary is only known to the top-level
caller (the pipeline that runs the Figma transform against a specific
target app).

Rather than threading four extra kwargs through every walker function,
we keep a single module-level context here. The top-level caller sets
it once before the walk and resets it after.

Registry-safety is ALWAYS enforced by the LLM modules themselves. This
context module only decides *whether the LLM path is eligible to run*:

    * ``FORGE_FIGMA_LLM`` env flag is set → and
    * at least one of the relevant closed vocabularies is populated.

When either condition fails, callers fall back to the keyword path.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

_CTX: dict = {
    "routes": [],
    "workflows": [],
    "component_registry": [],
    "nav_icon_set": [],
    "action_query_fn": None,
    "name_query_fn": None,
    "nav_icon_query_fn": None,
}


def set_figma_llm_context(
    *,
    routes: Optional[list[str]] = None,
    workflows: Optional[list[str]] = None,
    component_registry: Optional[list[str]] = None,
    nav_icon_set: Optional[list[str]] = None,
    action_query_fn: Optional[Callable[[str, str], str]] = None,
    name_query_fn: Optional[Callable[[str, str], str]] = None,
    nav_icon_query_fn: Optional[Callable[[str, str], str]] = None,
) -> None:
    """Populate the closed vocabularies before running a Figma transform.

    Idempotent per-key: passing ``None`` leaves that key alone. Call
    :func:`reset_figma_llm_context` to clear all keys between runs.
    """
    if routes is not None:
        _CTX["routes"] = list(routes)
    if workflows is not None:
        _CTX["workflows"] = list(workflows)
    if component_registry is not None:
        _CTX["component_registry"] = list(component_registry)
    if nav_icon_set is not None:
        _CTX["nav_icon_set"] = list(nav_icon_set)
    if action_query_fn is not None:
        _CTX["action_query_fn"] = action_query_fn
    if name_query_fn is not None:
        _CTX["name_query_fn"] = name_query_fn
    if nav_icon_query_fn is not None:
        _CTX["nav_icon_query_fn"] = nav_icon_query_fn


def reset_figma_llm_context() -> None:
    _CTX["routes"] = []
    _CTX["workflows"] = []
    _CTX["component_registry"] = []
    _CTX["nav_icon_set"] = []
    _CTX["action_query_fn"] = None
    _CTX["name_query_fn"] = None
    _CTX["nav_icon_query_fn"] = None


def figma_llm_enabled() -> bool:
    """Return True when the LLM-classifier path is enabled via the
    ``FORGE_FIGMA_LLM`` env flag. Accepts 1/true/yes/on (case-insensitive)."""
    return os.environ.get("FORGE_FIGMA_LLM", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def get_routes() -> list[str]:
    return list(_CTX.get("routes") or [])


def get_workflows() -> list[str]:
    return list(_CTX.get("workflows") or [])


def get_component_registry() -> list[str]:
    return list(_CTX.get("component_registry") or [])


def get_nav_icon_set() -> list[str]:
    return list(_CTX.get("nav_icon_set") or [])


def get_action_query_fn():
    return _CTX.get("action_query_fn")


def get_name_query_fn():
    return _CTX.get("name_query_fn")


def get_nav_icon_query_fn():
    return _CTX.get("nav_icon_query_fn")


# --------------------------------------------------------------------------- #
# Entrypoint helper — build a closed vocabulary from a plan (Wave 5-C wire)   #
# --------------------------------------------------------------------------- #

def context_from_plan(plan: dict | None) -> dict:
    """Derive the closed-vocabulary kwargs the Wave 5 classifiers need
    from a fully-resolved plan. Returned dict is safe to splat into
    :func:`set_figma_llm_context` — always contains all four registry
    keys with sane defaults ([] when the plan is silent).

    * ``routes``      : ``plan.pages[*].route`` (deduped, sorted, only
                        strings starting with ``/``).
    * ``workflows``   : ``plan.workflows[*].name`` (deduped, sorted).
    * ``component_registry`` : the shipped Forge library components
                        (imported lazily; empty list if the registry
                        module can't be loaded).
    * ``nav_icon_set`` : the ~60 canonical Lucide identifiers exposed
                        by :mod:`services.nav_icon_llm.LUCIDE_ICON_SET`
                        (imported lazily; empty list on fallback).

    Never raises — a malformed plan or missing sibling module yields
    empty lists for that key, and the Wave 5 wire treats an empty
    registry as "LLM path ineligible, keyword fallback wins" so the
    pipeline degrades gracefully rather than breaking.
    """
    plan = plan or {}

    routes: set[str] = set()
    _pages = plan.get("pages")
    if isinstance(_pages, list):
        for p in _pages:
            if isinstance(p, dict):
                r = p.get("route")
                if isinstance(r, str) and r.startswith("/"):
                    routes.add(r)

    workflows: set[str] = set()
    _workflows = plan.get("workflows")
    if isinstance(_workflows, list):
        for w in _workflows:
            if isinstance(w, dict):
                n = w.get("name")
                if isinstance(n, str) and n.strip():
                    workflows.add(n.strip())

    components: list[str] = []
    try:
        from services.component_registry import list_component_names  # type: ignore
        components = list(list_component_names() or [])
    except Exception:
        # Try the deprecated location + fall back to empty.
        try:
            from services.smith_tools import _load_library_component_names  # type: ignore
            components = list(_load_library_component_names() or [])
        except Exception:
            components = []

    icons: list[str] = []
    try:
        from services.nav_icon_llm import LUCIDE_ICON_SET  # type: ignore
        icons = sorted(LUCIDE_ICON_SET)
    except Exception:
        icons = []

    return {
        "routes":             sorted(routes),
        "workflows":          sorted(workflows),
        "component_registry": components,
        "nav_icon_set":       icons,
    }

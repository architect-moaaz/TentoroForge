"""Slice 5 — pipeline hook that wires recipes into the page builder.

Behind FORGE_COMPOSITION_RECIPES. When the flag is on and a brief carries
`page_recipes[<route>] = <recipe_key>`, the deterministic dispatcher calls
`try_build_recipe_page` FIRST, before the widget/dashboard/CRUD paths.
When the recipe can't render (no v1 anchors, missing recipe) the hook
returns None and the classic builders take over.

Design contract:
- Pure function of (route, output_dir).
- No exceptions escape into the pipeline — every failure returns None.
- Never a hard dependency on the brief being present — missing brief just
  means "no recipe for this route".
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any  # noqa: F401 — re-exported via type hints

from services.composition.build_recipe_page import build_recipe_page

logger = logging.getLogger(__name__)


_FLAG_ENV = "FORGE_COMPOSITION_RECIPES"


def is_flag_on() -> bool:
    """True when the recipe pipeline should run.

    The flag accepts:
        "warn"    — recipes active, validation only warns
        "strict"  — recipes active, validation raises
        "1"/"true"/"on" — same as "warn"
    Anything else (unset, "0", "off", "") disables the whole slice.
    """
    val = (os.environ.get(_FLAG_ENV) or "").strip().lower()
    return val in {"warn", "strict", "1", "true", "on", "yes"}


def is_strict() -> bool:
    return (os.environ.get(_FLAG_ENV) or "").strip().lower() == "strict"


def _brief_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "contracts" / "brief.json"


def load_page_recipes(output_dir: str | Path) -> dict[str, str]:
    """Read `brief.page_recipes` from disk. Empty dict on any failure."""
    p = _brief_path(output_dir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[composition-hook] brief.json unreadable: %s", exc)
        return {}
    recipes = data.get("page_recipes")
    if not isinstance(recipes, dict):
        return {}
    # Coerce to str->str; drop anything malformed.
    return {
        str(k): str(v)
        for k, v in recipes.items()
        if isinstance(k, str) and isinstance(v, str) and k and v
    }


def try_build_recipe_page(
    route: str,
    output_dir: str | Path,
    *,
    layout: str = "main",
) -> dict[str, Any] | None:
    """Return a page schema for `route` if a recipe is registered, else None.

    Silent no-op when the flag is off — safe to call unconditionally at the
    top of the deterministic dispatcher.
    """
    if not is_flag_on():
        return None
    if not route:
        return None
    recipes = load_page_recipes(output_dir)
    key = recipes.get(route)
    if not key:
        return None
    page = build_recipe_page(route, key, layout=layout)
    if page is None:
        logger.info(
            "[composition-hook] recipe %r for %s had no resolvable anchors — "
            "falling back to classic builder", key, route,
        )
        return None
    logger.info("[composition-hook] built %s from recipe %r", route, key)
    return page


def recipe_owned_routes(output_dir: str | Path) -> set[str]:
    """Return the set of routes a recipe page will actually build for.

    "Owned" means: (a) the brief lists the route in page_recipes, AND
    (b) the recipe would successfully render — its key exists and at
    least one anchor has `impl_status == "v1"`. Routes with recipes
    that can't render are NOT owned; the classic path is authoritative
    for those.

    Returns an empty set when the flag is off. Callers use this to
    filter routes out of the LLM page-schema-agent's worklist.
    """
    if not is_flag_on():
        return set()
    recipes = load_page_recipes(output_dir)
    if not recipes:
        return set()

    # Import lazily to avoid a hard circular dep at module load time.
    from services.composition.loader import (
        CompositionLibraryError,
        load_library,
    )
    try:
        library = load_library()
    except CompositionLibraryError as exc:
        logger.warning("[composition-hook] library load failed: %s", exc)
        return set()

    owned: set[str] = set()
    for route, key in recipes.items():
        recipe = library.recipes.get(key)
        if recipe is None:
            continue  # unknown recipe — gate would have flagged it
        has_v1 = any(
            (anch := library.anchors.get(a)) and anch.impl_status == "v1"
            for a in recipe.anchors
        )
        if has_v1:
            owned.add(route)
    return owned


def is_route_recipe_owned(route: str, output_dir: str | Path) -> bool:
    """Convenience predicate used at LLM-agent entry points."""
    if not route:
        return False
    return route in recipe_owned_routes(output_dir)


def filter_pages_owned_by_recipes(
    pages: list[dict[str, Any]],
    output_dir: str | Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split a plan's `pages` list into (llm_pages, recipe_owned_routes_seen).

    Callers that iterate over pages to invoke an LLM page-schema-agent
    should use this to skip recipe-owned routes at the orchestrator
    level — the LLM's per-call short-circuit (S6) is defensive; this is
    the efficiency version. Returns the untouched list when the flag is
    off, so wiring is safe to add unconditionally.
    """
    if not is_flag_on() or not pages:
        return list(pages), []
    owned = recipe_owned_routes(output_dir)
    if not owned:
        return list(pages), []
    llm_pages: list[dict[str, Any]] = []
    skipped: list[str] = []
    for p in pages:
        if not isinstance(p, dict):
            llm_pages.append(p)
            continue
        route = p.get("route")
        if isinstance(route, str) and route in owned:
            skipped.append(route)
            continue
        llm_pages.append(p)
    if skipped:
        logger.info(
            "[composition-hook] filtered %d recipe-owned routes from LLM worklist: %s",
            len(skipped), skipped,
        )
    return llm_pages, skipped


__all__ = [
    "filter_pages_owned_by_recipes",
    "is_flag_on",
    "is_route_recipe_owned",
    "is_strict",
    "load_page_recipes",
    "recipe_owned_routes",
    "try_build_recipe_page",
]

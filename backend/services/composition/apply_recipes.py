"""Slice 3 wiring — derive `page_recipes` from a plan and apply to a brief.

The picker (recipe_picker.py) is a pure function of (persona, page_intent).
This module walks a plan, derives those inputs per-page, calls the picker,
and produces the `{route -> recipe_key}` map that gets stamped onto
`DesignBrief.page_recipes`.

Nothing here is gated — the caller decides when to invoke it. In the
pipeline that's behind `FORGE_COMPOSITION_RECIPES`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import re

from schemas.design_brief import DesignBrief
from services.composition.recipe_picker import pick_recipe, score_recipes

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Task #596 — picker greediness fix.
#
# The picker itself is a pure function of (persona, page_intent) and scores
# every recipe by word overlap. On its own it will happily match a persona-
# shaped home recipe (member_home) to /login or /admin because the persona
# alone scores ≥2. That's what shipped 12 wrong recipes on tr7rfk34's brief
# (/admin, /login, /signup, /profile, /*/[id], /*/new — all silently attached
# to member_home, then rendered as empty-anchor pages).
#
# Two gates enforced HERE (not in the picker, so unit tests can still exercise
# the pure scoring surface):
#   1. Eligibility blocklist — /login, /signup, /admin*, /logout, /reset*,
#      /forgot*, /verify* never get a recipe. Category-none.
#   2. Kind ↔ category compatibility — a route's derived kind (home / list /
#      detail / form) must match the recipe's category. A `home` recipe
#      cannot land on a `/*/new` (form) or `/*/[id]` (detail) route.
# Plus: require min_score ≥ 3 so persona-alone (2 points) is never enough —
# some intent overlap is required.
# ─────────────────────────────────────────────────────────────────────────────

_AUTH_ROUTES = frozenset({"/login", "/signup", "/logout", "/signout", "/sign-in", "/sign-up"})
_AUTH_PREFIXES = ("/forgot", "/reset", "/verify", "/auth")
_ADMIN_PREFIX = "/admin"

# Recipe category → set of route kinds where it's allowed. Categories not
# listed default to "always allowed" so new categories (calendar, timeline,
# workflow, learning, …) aren't stranded when they arrive.
_CATEGORY_TO_KINDS: dict[str, frozenset[str]] = {
    "home":   frozenset({"home"}),
    "list":   frozenset({"list"}),
    "detail": frozenset({"detail"}),
    "form":   frozenset({"form"}),
}

_MIN_SCORE = 3  # persona (2) alone never enough — require intent overlap


def _route_kind(route: str) -> str:
    """Coarse page-kind classifier from route pattern only (no plan lookup).

    Returns one of: 'auth', 'admin', 'form', 'detail', 'home', 'list'.
    'auth' + 'admin' are terminal — they short-circuit recipe assignment.
    """
    r = (route or "").strip()
    if not r:
        return "list"  # empty → conservative default
    # Auth prefixes match anything under them: /forgot-password, /reset/xxx,
    # /verify-email, /auth/callback all count as auth.
    if r in _AUTH_ROUTES or any(r == p or r.startswith(p + "/") or r.startswith(p + "-") for p in _AUTH_PREFIXES):
        return "auth"
    if r == _ADMIN_PREFIX or r.startswith(_ADMIN_PREFIX + "/"):
        return "admin"
    # /*/new, /*/create, /*/add → create form
    # /*/edit, /*/update → edit form
    if r.endswith(("/new", "/create", "/add", "/edit", "/update")):
        return "form"
    # Parameterized detail route: any bracketed segment (Next-style [id]).
    if "[" in r and "]" in r:
        return "detail"
    if r in ("/", "/dashboard", "/home", "/overview", "/index"):
        return "home"
    # Home-shaped route names in ANY path segment (or bare slug without a
    # leading slash). Common landing-surface vocabulary across personas:
    # /console for operators, /today for field workers, /inbox for approvers,
    # /workspace for creators, /overview for analysts, etc. Also handles
    # bare slugs like "member-home" (no leading slash — fallback path in
    # derive_page_recipes when page has slug/name but no route).
    _HOME_NAMES = {"home", "dashboard", "overview", "index", "console",
                   "workspace", "today", "inbox", "hub", "landing"}
    for seg in re.split(r"[/\-_]", r):
        if seg and seg.lower() in _HOME_NAMES:
            return "home"
    return "list"


def _is_route_recipe_eligible(route: str) -> bool:
    """Hard block for routes that should never receive a persona home recipe.

    Auth pages need their own auth composition; admin surfaces are role-
    scoped tools not member journeys.
    """
    return _route_kind(route) not in ("auth", "admin")


def _category_matches_route_kind(route: str, category: str) -> bool:
    """True when a recipe's category is compatible with the route's kind.

    Unknown categories pass through so novel recipe categories aren't
    stranded — the eligibility gate above still blocks auth/admin.
    """
    allowed_kinds = _CATEGORY_TO_KINDS.get(category)
    if allowed_kinds is None:
        return True
    return _route_kind(route) in allowed_kinds


def _iter_pages(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the plan's pages, tolerating both flat and nested shapes."""
    if not isinstance(plan, dict):
        return []
    pages = plan.get("pages")
    if isinstance(pages, list):
        return [p for p in pages if isinstance(p, dict)]
    # Some plans nest pages under app_shape or similar; only walk one level.
    for key in ("app_shape", "info_architecture", "ia"):
        block = plan.get(key)
        if isinstance(block, dict):
            nested = block.get("pages")
            if isinstance(nested, list):
                return [p for p in nested if isinstance(p, dict)]
    return []


def _actor_persona(page: dict[str, Any], plan: dict[str, Any]) -> str | None:
    """Best-effort persona for a page.

    Look on the page itself first (actor, persona, role), fall back to
    the plan's default primary actor. Return None if nothing found.
    """
    for key in ("persona", "actor", "role"):
        val = page.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Plan-level primary actor as fallback.
    actors = plan.get("actors") if isinstance(plan, dict) else None
    if isinstance(actors, list) and actors:
        first = actors[0]
        if isinstance(first, dict):
            for key in ("role", "name", "persona"):
                val = first.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        elif isinstance(first, str) and first.strip():
            return first.strip()
    return None


def _page_intent(page: dict[str, Any]) -> str:
    """Concat the words that describe what a page is for."""
    parts: list[str] = []
    for key in ("title", "label", "name", "route", "purpose", "kind", "archetype", "page_type"):
        val = page.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return " ".join(parts)


def derive_page_recipes(plan: dict[str, Any]) -> dict[str, str]:
    """Walk a plan's pages and return `{route_or_slug: recipe_key}`.

    Pages the picker can't match are simply omitted — the classic
    (non-recipe) path handles them.
    """
    out: dict[str, str] = {}
    if not isinstance(plan, dict):
        return out
    for page in _iter_pages(plan):
        route = page.get("route") or page.get("slug") or page.get("name")
        if not isinstance(route, str) or not route.strip():
            continue
        # Task #596 gate 1 — auth / admin routes never get a recipe.
        if not _is_route_recipe_eligible(route):
            continue
        persona = _actor_persona(page, plan)
        intent = _page_intent(page)
        # Task #596 gate 2 — take the highest-scoring recipe whose category
        # matches the route's kind AND whose score meets the floor. This
        # replaces the old `pick_recipe(persona, intent)` call which had no
        # floor and no kind check.
        ranked = score_recipes(persona, intent)
        for match in ranked:
            if match.score < _MIN_SCORE:
                break  # sorted; nothing beyond this reaches the floor
            if _category_matches_route_kind(route, match.recipe.category):
                out[route] = match.key
                break
    return out


def apply_recipes_to_brief(
    brief: DesignBrief,
    plan: dict[str, Any],
    *,
    overwrite: bool = False,
) -> DesignBrief:
    """Return a copy of `brief` with `page_recipes` derived from `plan`.

    When `brief.page_recipes` already has entries and `overwrite` is False,
    the derived map is merged (existing entries win). Set `overwrite=True`
    to replace the field wholesale.
    """
    derived = derive_page_recipes(plan)
    if not derived:
        logger.info("[composition] no recipes derived for plan")
        return brief
    if overwrite or not brief.page_recipes:
        merged = derived
    else:
        merged = {**derived, **brief.page_recipes}
    logger.info("[composition] applied %d page recipes", len(merged))
    return brief.model_copy(update={"page_recipes": merged})


def derive_persist_apply(
    output_dir: str | Path,
    plan: dict[str, Any],
    *,
    overwrite: bool = False,
) -> dict[str, str]:
    """Pipeline convenience: read brief.json on disk, derive recipes from
    the plan, write the updated brief back. Behind FORGE_COMPOSITION_RECIPES —
    callers should gate on `pipeline_hook.is_flag_on()` before invoking.

    Returns the final `page_recipes` map that landed on disk. Empty dict
    means either nothing derived or the brief is missing / unreadable —
    both are non-fatal for the pipeline.

    Idempotent: running twice with the same plan produces the same brief.
    """
    brief_path = Path(output_dir) / "contracts" / "brief.json"
    if not brief_path.is_file():
        logger.info("[composition] no brief.json at %s — skipping recipe apply", brief_path)
        return {}

    try:
        raw = json.loads(brief_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[composition] brief.json unreadable: %s", exc)
        return {}

    try:
        brief = DesignBrief.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — validation errors are non-fatal
        logger.warning("[composition] brief.json failed schema validation: %s", exc)
        return {}

    updated = apply_recipes_to_brief(brief, plan, overwrite=overwrite)
    if updated.page_recipes == brief.page_recipes:
        return dict(brief.page_recipes)  # nothing changed — don't rewrite

    # Only rewrite when we actually derived recipes — a no-op should not
    # bump mtime and re-invalidate downstream caches.
    tmp = brief_path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(updated.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    tmp.replace(brief_path)  # atomic swap
    logger.info(
        "[composition] wrote brief.json with %d page recipes",
        len(updated.page_recipes),
    )
    return dict(updated.page_recipes)


__all__ = [
    "apply_recipes_to_brief",
    "derive_page_recipes",
    "derive_persist_apply",
]

"""Archetype recipe detector — keyword scorer for recipe pick (M1-T7).

Same safety-net role as ``shape_profile_detector``: LLM is primary
author of ``plan.archetypes``. This module fills a recipe when the
LLM emits an unknown one, and offers a bare-capability composition
when no recipe fits.

Never runs on the hot path.
"""
from __future__ import annotations

from typing import Any

from services.shape_profile import (
    Finding,
    known_recipes,
    safe_default_capabilities,
)


# Curated per-recipe keyword signals.
_RECIPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "visual_product_search": ("scan product", "camera search", "visual lookup", "identify item"),
    "catalog":               ("browse", "gallery", "storefront", "catalog", "listings"),
    "crud":                  ("create edit delete", "records", "basic data"),
    "directory":             ("directory", "roster", "employees", "people list"),
    "dashboard":             ("dashboard", "metrics", "analytics", "kpi"),
    "kanban":                ("kanban", "board", "swimlanes", "columns", "drag between"),
    "approval_queue":        ("approval", "review queue", "moderation", "sign-off"),
    "wizard":                ("wizard", "multi-step", "onboarding steps"),
    "checkout":              ("checkout", "buy flow", "payment"),
    "cart":                  ("cart", "basket", "add to cart"),
    "chat":                  ("chat", "messaging", "conversation"),
    "feed":                  ("feed", "timeline", "posts stream"),
    "player":                ("player", "listen", "watch", "playback"),
    "chart_analysis":        ("chart analysis", "trading chart", "technical analysis"),
    "map_pins":              ("map with pins", "locations", "tracked positions"),
}


def score_recipe(brief: str) -> str | None:
    """Return the best-matching recipe for a brief; ``None`` when no
    signal — caller should fall back to a bare CRUD capabilities
    composition."""
    lower = brief.lower()
    valid = set(known_recipes())
    best_recipe: str | None = None
    best_score = 0
    for recipe, needles in _RECIPE_KEYWORDS.items():
        if recipe not in valid:
            continue
        score = sum(1 for needle in needles if needle in lower)
        if score > best_score:
            best_score = score
            best_recipe = recipe
    return best_recipe if best_score > 0 else None


def detect_archetype_instance(
    brief: str, *, module_name: str = "main", routes: tuple[str, ...] = ("/",)
) -> tuple[dict[str, Any], list[Finding]]:
    """Fill a single ArchetypeInstance when the LLM's output was
    unusable. Prefer a recipe when the keyword scorer finds one;
    otherwise emit a bare capabilities composition using safe
    defaults.

    Returns ``(instance_dict, findings)`` with ``LLM_UNAVAILABLE``
    always present."""
    findings: list[Finding] = [Finding(
        rule="LLM_UNAVAILABLE",
        message=(
            "Archetype instance filled from keyword detector — LLM "
            "output was unusable or unavailable. Generation is marked "
            "'produced under degraded conditions'."
        ),
        severity="warning",
        axis="archetypes",
    )]
    recipe = score_recipe(brief)
    if recipe is not None:
        findings.append(Finding(
            rule="archetypes.degraded_fill_recipe",
            message=f"picked recipe={recipe!r} from keyword detector",
            severity="info",
            axis="archetypes",
        ))
        return ({
            "name": module_name,
            "recipe": recipe,
            "entities": [],
            "routes": list(routes),
        }, findings)

    caps = safe_default_capabilities()
    findings.append(Finding(
        rule="archetypes.safe_default_capabilities",
        message="filled capabilities from safe defaults (no keyword signal)",
        severity="warning",
        axis="archetypes",
    ))
    return ({
        "name": module_name,
        "capabilities": caps,
        "entities": [],
        "routes": list(routes),
    }, findings)


def repair_unknown_recipe(recipe: str, brief: str) -> tuple[str | None, Finding]:
    """LLM emitted a recipe name that isn't in recipes.json. Try to
    map it to a real recipe via the keyword scorer; return
    ``(None, finding)`` when we can't — caller should either compose
    capabilities from safe defaults or REVISE."""
    scored = score_recipe(brief)
    if scored is not None:
        return (scored, Finding(
            rule="archetypes.recipe_remapped",
            message=f"LLM emitted unknown recipe={recipe!r}; remapped to {scored!r} via keyword detector",
            severity="warning",
            axis="archetypes",
        ))
    return (None, Finding(
        rule="archetypes.recipe_unrecoverable",
        message=(
            f"LLM emitted unknown recipe={recipe!r} and no keyword "
            "detector match. Fall through to capability composition."
        ),
        severity="warning",
        axis="archetypes",
    ))

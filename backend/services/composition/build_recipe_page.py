"""Slice 4 — build a page schema from a composition recipe key.

Given a recipe key like `"member_home"`, produce a schemaVersion:"2"
Page whose root is a Stack of the recipe's anchors in order. Each
anchor resolves to a registered library component via the
`component` field in anchors.json (Slice 2).

This is a *substrate* builder — every anchor gets sensible default
props so the page renders standalone. Real data-binding + copy come
from later passes (design brief, plan bindings, deterministic strings).

Returns None if the recipe key doesn't exist or none of its anchors
resolve to a registered component (safe fallback → classic builder).
"""

from __future__ import annotations

import logging
from typing import Any

from services.composition.loader import CompositionLibraryError, load_library

logger = logging.getLogger(__name__)


# Anchors emit only what their propsSchema requires by default; anything
# else the library components tolerate as "empty state / skeleton".
# Keeping defaults intentionally spartan — copy authors elsewhere.
_ANCHOR_DEFAULTS: dict[str, dict[str, Any]] = {
    # member_home v1
    "PinnedMomentHero":  {},
    "VitalsInContext":   {},
    "ScanStrip":         {},
    "RecsRailReasoned":  {},
    "CommunityPulse":    {},
    "StickyPrimaryCta":  {},
    # shopper_home v1
    "FeaturedMomentHero": {},
    "ReasonsToReturnRow": {},
    "TrendingRail":       {},
    "TasteRecsRail":      {},
    "BrandStoryPulse":    {},
    "CartCta":            {},
    # operator_console v1
    "AttentionQueueHero":  {},
    "SlaVitalsStrip":      {},
    "LiveEventLog":        {},
    "TeamStatusBoard":     {},
    "ShiftMetricsRail":    {},
    "EmergencyActionRail": {},
    # manager_overview v1
    "TeamGlanceHero":   {},
    "PrioritiesStrip":  {},
    "CalendarWeek":     {},
    "EscalationsQueue": {},
    "RecognitionFeed":  {},
    # creator/field/learner/analyst/patron v1 (5 new components)
    "DiscoveryRail":     {},
    "DraftFocusHero":    {},
    "JobChecklist":      {},
    "CompletionCapture": {},
    "NarrativeHeadline": {},
    # Chart + DescriptionList are re-used from the main library — no defaults
    # needed here since they're already in the runtime registry with their own
    # sensible fallbacks.
}


def _route_to_id(route: str) -> str:
    """Turn `/dashboard/member` → `dashboard_member` for schema.id."""
    parts = [p for p in route.strip("/").split("/") if p]
    return "_".join(parts) or "home"


def build_recipe_page(
    route: str,
    recipe_key: str,
    *,
    layout: str = "main",
) -> dict[str, Any] | None:
    """Build a page schema from a recipe.

    Args:
        route: the page route, e.g. `/dashboard`. Becomes schema.route.
        recipe_key: recipe key from `recipes.json` (e.g. `"member_home"`).
        layout: shell layout id. Default `"main"` matches the standard shell.

    Returns:
        A page schema dict (schemaVersion:"2") ready to be written to
        `src/schemas/<route>.json`, or None if the recipe is unknown or
        no anchor resolves.
    """
    try:
        library = load_library()
    except CompositionLibraryError as exc:
        logger.warning("[recipe] library load failed: %s", exc)
        return None

    recipe = library.recipes.get(recipe_key)
    if recipe is None:
        logger.info("[recipe] unknown recipe %r — falling back", recipe_key)
        return None

    children: list[dict[str, Any]] = []
    for anchor_name in recipe.anchors:
        anchor = library.anchors.get(anchor_name)
        if anchor is None:
            logger.debug("[recipe] anchor %r missing from library", anchor_name)
            continue
        # Every anchor name auto-CamelCases to a component string in
        # anchors.json, but only anchors with `impl_status == "v1"` have
        # a matching runtime component registered in packages/library.
        # Emitting an unimplemented anchor would render as a "⚠ <Type>"
        # placeholder — worse than the classic path, so skip it.
        if anchor.impl_status != "v1":
            continue
        component = anchor.component
        if not component:
            continue
        props = dict(_ANCHOR_DEFAULTS.get(component, {}))
        children.append({
            "type": component,
            "props": props,
        })

    if not children:
        logger.info(
            "[recipe] recipe %r has no resolvable anchors — falling back",
            recipe_key,
        )
        return None

    return {
        "schemaVersion": "2",
        "id": _route_to_id(route),
        "route": route,
        "layout": layout,
        "dataSources": [],  # anchors carry their own binds when the plan has them
        "root": {
            "type": "Stack",
            "props": {"gap": "tokens.spacing.6"},
            "children": children,
        },
        "meta": {
            "recipe": recipe_key,
            "category": recipe.category,
        },
    }


__all__ = ["build_recipe_page"]

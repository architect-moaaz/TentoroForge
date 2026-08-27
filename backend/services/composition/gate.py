"""Slice 6 — build-time validation gate for composition recipes.

Validates every entry in a brief's `page_recipes`:
    1. recipe key exists in recipes.json
    2. recipe has at least one anchor with `impl_status == "v1"`
       (otherwise the page would render as an empty Stack)
    3. every anchor named by the recipe exists in anchors.json
       (structural integrity — anchors.json is auto-generated from
       recipes.json, so a violation here means the library is stale)

Modes (via FORGE_COMPOSITION_RECIPES env, read by pipeline_hook.is_strict):
    - "strict" → assert_valid_or_raise() throws CompositionGateError
    - "warn"/other truthy → assert_valid_or_raise() logs, returns quietly
    - unset/off → gate never runs at all (pipeline_hook.is_flag_on gates it)

The gate is designed to run once at the top of the generation pipeline
so bad recipe references are caught before any pages are emitted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from schemas.design_brief import DesignBrief
from services.composition.loader import CompositionLibraryError, load_library
from services.composition.pipeline_hook import is_flag_on, is_strict

logger = logging.getLogger(__name__)


class CompositionGateError(Exception):
    """Raised in strict mode when page_recipes contains invalid references."""


@dataclass(frozen=True)
class ValidationError:
    route: str
    recipe: str
    kind: str    # "unknown_recipe" | "no_v1_anchors" | "anchor_missing"
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.route} → {self.recipe!r}: {self.detail}"


def validate_page_recipes(brief: DesignBrief) -> list[ValidationError]:
    """Return every problem with brief.page_recipes. Empty list = all clean.

    Never raises — the caller decides whether to log or throw
    (see `assert_valid_or_raise`).
    """
    errors: list[ValidationError] = []
    if not brief.page_recipes:
        return errors

    try:
        library = load_library()
    except CompositionLibraryError as exc:
        # Can't validate without a library; surface it as a single error so the
        # strict-mode caller still fails visibly.
        errors.append(ValidationError(
            route="*", recipe="*",
            kind="library_load_failed", detail=str(exc),
        ))
        return errors

    for route, recipe_key in brief.page_recipes.items():
        recipe = library.recipes.get(recipe_key)
        if recipe is None:
            errors.append(ValidationError(
                route=route, recipe=recipe_key,
                kind="unknown_recipe",
                detail="not in recipes.json",
            ))
            continue

        # Every anchor named by the recipe must exist in anchors.json.
        # anchors.json is auto-generated from recipes so a miss here is a
        # library-integrity bug, not a user-authoring bug.
        missing = [a for a in recipe.anchors if a not in library.anchors]
        if missing:
            errors.append(ValidationError(
                route=route, recipe=recipe_key,
                kind="anchor_missing",
                detail=f"anchors not in library: {missing}",
            ))
            continue  # further checks would be misleading with a broken recipe

        # At least one anchor has to be v1-implemented — otherwise the recipe
        # renders as an empty Stack and the classic path would be strictly
        # better. This *warns* the user which recipe still needs
        # anchor components built.
        v1_anchors = [
            a for a in recipe.anchors
            if (anch := library.anchors.get(a)) and anch.impl_status == "v1"
        ]
        if not v1_anchors:
            errors.append(ValidationError(
                route=route, recipe=recipe_key,
                kind="no_v1_anchors",
                detail=(
                    f"recipe has {len(recipe.anchors)} anchors but none are "
                    f"implemented yet — page would fall back to classic builder"
                ),
            ))

    return errors


def assert_valid_or_raise(brief: DesignBrief) -> list[ValidationError]:
    """Run the gate and honour FORGE_COMPOSITION_RECIPES mode.

    - flag off → no-op, returns [].
    - "warn"   → logs every error, returns them.
    - "strict" → logs and raises CompositionGateError if any errors.

    Returns the error list either way (caller can inspect for telemetry).
    """
    if not is_flag_on():
        return []

    errors = validate_page_recipes(brief)
    if not errors:
        return errors

    # `no_v1_anchors` is a "recipe registered but not yet implementable"
    # signal — always warn, never fatal, even in strict mode. The classic
    # builder handles those pages just fine.
    fatal = [e for e in errors if e.kind != "no_v1_anchors"]
    for e in errors:
        (logger.warning if e.kind == "no_v1_anchors" else logger.error)(
            "[composition-gate] %s", e,
        )
    if is_strict() and fatal:
        raise CompositionGateError(
            f"{len(fatal)} recipe reference(s) invalid: "
            + "; ".join(str(e) for e in fatal)
        )
    return errors


__all__ = [
    "CompositionGateError",
    "ValidationError",
    "assert_valid_or_raise",
    "validate_page_recipes",
]

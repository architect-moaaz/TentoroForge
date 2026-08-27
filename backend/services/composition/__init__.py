"""Composition recipe library.

The library sits between discovery, planner, and page-schema-agent. It defines
the shared vocabulary of page shapes (recipes) and their component slots
(anchors) so every downstream layer can validate against a single source of
truth.

Contents
--------
recipes.json — 50 page recipes across 10 categories (home, list, detail, form,
    flow, system, workflow, location, learning, calendar). Each recipe declares
    an ordered list of anchor names it instantiates.

anchors.json — every anchor referenced by any recipe. Machine-readable contract
    per anchor: what data it binds to, what copy slots it accepts, what tokens
    it consumes, which TS component implements it, and which recipes use it.

loader.py — read + validate + expose typed accessors. Fails at import if any
    recipe cites an anchor that doesn't exist in anchors.json (the whole point
    of having a machine-readable library).

Consumption points (wired incrementally in later slices)
--------------------------------------------------------
1. Discovery — picks which recipe fits which persona.
2. Planner — for each page, expands recipe → anchor list, asks LLM to fill
   copy/binds only. Emits pages[].sections[] with anchor names.
3. Build-time gate — validates every section cites a real anchor + binds
   satisfied. Fail-fast before generation continues.
4. Page-schema agent — instantiates `<AnchorComponent {...props}>` from
   section declarations. No composition freedom.
5. Component library — implements each anchor as a token-consuming React
   component. Same anchor, different app, different look via CSS vars.
6. Design-lead critic — reads brief vs emitted page. Blocks pages that don't
   match the persona's promised patterns.
"""

from services.composition.loader import (
    Anchor,
    CompositionLibraryError,
    Recipe,
    get_anchor,
    get_recipe,
    list_categories,
    list_recipes,
    load_library,
    validate_library,
)
from services.composition.recipe_picker import (
    RecipeMatch,
    pick_recipe,
    score_recipes,
)
from services.composition.apply_recipes import (
    apply_recipes_to_brief,
    derive_page_recipes,
    derive_persist_apply,
)
from services.composition.critic import (
    CriticFinding,
    CriticReport,
    critique_recipe_page,
)
from services.composition.build_recipe_page import build_recipe_page
from services.composition.pipeline_hook import (
    filter_pages_owned_by_recipes,
    is_flag_on,
    is_route_recipe_owned,
    is_strict,
    load_page_recipes,
    recipe_owned_routes,
    try_build_recipe_page,
)
from services.composition.gate import (
    CompositionGateError,
    ValidationError,
    assert_valid_or_raise,
    validate_page_recipes,
)

__all__ = [
    "Anchor",
    "CompositionGateError",
    "CompositionLibraryError",
    "CriticFinding",
    "CriticReport",
    "Recipe",
    "RecipeMatch",
    "ValidationError",
    "apply_recipes_to_brief",
    "assert_valid_or_raise",
    "build_recipe_page",
    "critique_recipe_page",
    "derive_page_recipes",
    "derive_persist_apply",
    "filter_pages_owned_by_recipes",
    "get_anchor",
    "get_recipe",
    "is_flag_on",
    "is_route_recipe_owned",
    "is_strict",
    "list_categories",
    "list_recipes",
    "load_library",
    "load_page_recipes",
    "pick_recipe",
    "recipe_owned_routes",
    "score_recipes",
    "try_build_recipe_page",
    "validate_library",
    "validate_page_recipes",
]

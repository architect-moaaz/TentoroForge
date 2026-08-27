"""Composition recipes — the picker that decides which root primitive
a page's content region uses.

Every generated app today emits ``root: Stack{children:[...]}`` for
its dashboards, collections, and records. That's why apps look alike
even when the paint (palette, fonts, chrome) varies — the reading
grammar is one shape. Recipes are the layer that lets a dashboard
open as an ``asymmetric-split`` (Banking suite), a ``chart-grid``
(DORA-style engineering), or a ``ranked-leaderboard`` (top-N ops)
instead of a symmetric Stack every time.

**Authority, not gates.** ``select_composition(page_type, archetype,
brief)`` is a pure lookup — vocabulary declaration wins, then a small
transparent heuristic on ``page_type`` + ``register``, else the safe
``kpi-hero-split`` default. No env flag, no fallback classifier.

This module is the pure REGISTRY + SELECTOR. It ships with no wiring
into composers — that's a follow-up slice (needs the "root must be
Stack" prompt/validator constraint in ``page_composer.py`` relaxed,
and each composer's root emission to dispatch on the chosen recipe's
``root`` primitive). Landing the registry now unblocks the composer
work and gives the vocabulary a first-class ``dashboard_recipe``
field to declare against.

See docs/superpowers/specs/2026-08-15-widget-anatomy-composition-recipes.md
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Allowed root primitives ────────────────────────────────────────────
# Each recipe declares which layout-component wraps the composed
# section list at the page root. The composer emits that primitive
# instead of the hardcoded ``Stack``. All are library components
# already shipped — see packages/library/src/components/.
class Primitive:
    STACK = "Stack"            # today's default — one column, vertical rhythm
    SPLIT_VIEW = "SplitView"   # left+right with configurable ratio
    GRID = "Grid"              # regular multi-column grid
    SIDEBAR = "Sidebar"        # rail + main pattern within the content region
    INSPECTOR_PANEL = "InspectorPanel"  # main + right rail (context/detail)
    CLUSTER = "Cluster"        # wrap-flow (chip fields, small multiples)


# ── Recipe registry ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Recipe:
    """A composition recipe — how the content region is laid out at the
    page root, plus a slot map that names where each maquette section
    plugs in.
    """

    name: str
    root: str  # one of Primitive.*
    # Maps a logical slot name → the ordered list of maquette section
    # kinds that fill it. Example for ``asymmetric-split``:
    #   { "primary": ["kpis"], "secondary": ["hero_chart"], "footer": [...] }
    # A composer wiring this up feeds each slot's maquette-section list
    # to the SAME section builders it uses today, then plugs the
    # resulting nodes into the root primitive's children.
    slot_map: dict[str, list[str]] = field(default_factory=dict)
    # Layout hints the composer applies to the root primitive (ratio
    # for SplitView, columns for Grid, gap, etc). Kept opaque here —
    # each root builder interprets its own hints.
    hints: dict[str, Any] = field(default_factory=dict)
    # Human explanation — surfaces in Smith / editor to explain "why
    # this dashboard is a chart-grid, not a KPI dashboard". Not for
    # runtime dispatch.
    when_it_fits: str = ""


# The six recipes shipped in the initial registry. Ordering matters
# only for docs and vocabulary examples — selection is a pure lookup.
_REGISTRY: dict[str, Recipe] = {}


def _register(recipe: Recipe) -> None:
    _REGISTRY[recipe.name] = recipe


_register(Recipe(
    name="kpi-hero-split",
    root=Primitive.STACK,
    slot_map={
        "header":   ["chrome", "hero"],
        "kpi_row":  ["kpis"],
        "hero":     ["hero_chart"],
        "footer":   ["activity", "small_multiples"],
    },
    hints={"gap": "tokens.spacing.6"},
    when_it_fits=(
        "The safe universal — today's default. A KPI row across the top, "
        "a large hero chart, and an activity feed beneath. Fits any "
        "dashboard where no other recipe explicitly maps better."
    ),
))
_register(Recipe(
    name="asymmetric-split",
    root=Primitive.SPLIT_VIEW,
    slot_map={
        "primary":   ["kpis"],            # left ~1/3, dense KPI stack
        "secondary": ["hero_chart"],       # right ~2/3, big chart
        "footer":    ["small_multiples"],  # 4-col row of small charts below
    },
    hints={"ratio": "1fr 2fr", "gap": "tokens.spacing.6"},
    when_it_fits=(
        "Data-rich analytical dashboards where the reader interrogates "
        "one chart while a stack of numbers stays visible — the Banking "
        "Demographics / Financial Health / Transactions grammar. Best "
        "when the brief mentions 'analytical', 'quant-heavy', 'reviewing'."
    ),
))
_register(Recipe(
    name="chart-grid",
    root=Primitive.GRID,
    slot_map={
        "filter_bar": ["chrome"],
        "charts":     ["primary_chart", "small_multiples"],
    },
    hints={"columns": 2, "gap": "tokens.spacing.4"},
    when_it_fits=(
        "Engineering / observability / monitoring dashboards — DORA "
        "Metrics style. No KPIs, no hero, no activity feed. Just N charts "
        "in an even grid with filter chips at top. The reader reads "
        "patterns from the small multiples, not headlines."
    ),
))
_register(Recipe(
    name="ranked-leaderboard",
    root=Primitive.SPLIT_VIEW,
    slot_map={
        "primary":   ["primary_chart"],  # leaderboard-encoded chart
        "secondary": ["hero"],           # detail / drill-in on selection
    },
    hints={"ratio": "3fr 2fr", "gap": "tokens.spacing.6"},
    when_it_fits=(
        "Top-N ranking screens where the primary artifact is a sorted "
        "leaderboard (top merchants by revenue, worst-performing services). "
        "Requires the primary_chart's encoding.leaderboard to be true."
    ),
))
_register(Recipe(
    name="command-center",
    root=Primitive.GRID,
    slot_map={
        "header":       ["chrome"],
        "main":         ["primary_chart"],
        "right_rail":   ["kpis", "activity"],
    },
    hints={"columns": "3fr 1fr", "gap": "tokens.spacing.4"},
    when_it_fits=(
        "High-density operational dashboards — trading desk, NOC, "
        "dispatch. Main hero on the left, a status rail on the right "
        "with tight KPIs + live activity. Best when the brief is "
        "'real-time', 'operational', 'monitoring the state of X'."
    ),
))
_register(Recipe(
    name="inspector-panel",
    root=Primitive.INSPECTOR_PANEL,
    slot_map={
        "main":      ["primary_chart"],  # list / kanban / table
        "inspector": ["hero", "activity"],  # detail card for the current selection
    },
    hints={"ratio": "2fr 1fr", "gap": "tokens.spacing.4"},
    when_it_fits=(
        "Case-management / ticket-triage screens where the user selects "
        "a row on the left and inspects it on the right. Requires an "
        "entity with a selectable primary artifact (Kanban, Table with "
        "rowClick). Best for support, CRM, ticketing."
    ),
))


DEFAULT_RECIPE = "kpi-hero-split"


def list_recipes() -> list[Recipe]:
    """All registered recipes in registration order."""
    return list(_REGISTRY.values())


def get_recipe(name: str) -> Optional[Recipe]:
    """Look up a recipe by name. Returns None for unknown names — callers
    fall back to :func:`get_default_recipe` (never raise).
    """
    return _REGISTRY.get(name)


def get_default_recipe() -> Recipe:
    """The safe universal — today's KPI-Hero-Stack behavior."""
    return _REGISTRY[DEFAULT_RECIPE]


# ── Selector ──────────────────────────────────────────────────────────


# Vocabulary-declared archetype → recipe name. Loaded at select time
# via ``services.archetype_vocabulary`` when available; hardcoded here
# as a fallback so the selector is testable in isolation.
_ARCHETYPE_RECIPE_HINTS: dict[str, str] = {
    # Analytical / banking family — the Banking suite grammar
    "banking-platform":    "asymmetric-split",
    "analytics-dashboard": "asymmetric-split",
    # Engineering / observability / monitoring — DORA-style
    "dev-tools":           "chart-grid",
    "observability":       "chart-grid",
    "monitoring":          "chart-grid",
    "devops":              "chart-grid",
    # Case management / triage — inspector on the right
    "crm":                 "inspector-panel",
    "case-management":     "inspector-panel",
    "ticketing":           "inspector-panel",
    "support-desk":        "inspector-panel",
    # High-density operational
    "trading-desk":        "command-center",
    "dispatch":            "command-center",
    "noc":                 "command-center",
}


# Vocabulary-declared "register" (brief tone) hints. Only used when the
# archetype didn't already resolve; a small transparent heuristic.
_REGISTER_RECIPE_HINTS: dict[str, str] = {
    "analytical":   "asymmetric-split",
    "quant-heavy":  "asymmetric-split",
    "operational":  "command-center",
    "triage":       "inspector-panel",
}


def _vocab_recipe_for(archetype: Optional[str]) -> Optional[str]:
    """Look up an archetype's vocabulary-declared recipe.

    Returns the declared recipe name ONLY when it's a valid registered
    recipe. Unknown / missing / import-failed all return None so the
    caller can transparently fall through to :func:`_archetype_hint_for`.
    """
    if not archetype:
        return None
    try:
        from services.archetype_vocabulary import load_vocabulary
        vocab = load_vocabulary(archetype)
        if vocab is not None and getattr(vocab, "dashboard_recipe", None):
            return str(vocab.dashboard_recipe)
    except Exception as exc:  # noqa: BLE001 — never break the selector
        logger.debug("[composition_recipes] vocab lookup failed: %s", exc)
    return None


def _archetype_hint_for(archetype: Optional[str]) -> Optional[str]:
    """Hardcoded archetype → recipe name fallback used when the
    vocabulary didn't declare (or the archetype isn't in the vocab
    module yet). Safe subset kept in sync with the vocab library.
    """
    if not archetype:
        return None
    return _ARCHETYPE_RECIPE_HINTS.get(archetype)


def _brief_recipe_for(brief: Any) -> Optional[str]:
    """When neither the vocab nor the archetype-hints table matched,
    peek at the brief's ``register`` (tone) or ``interaction_model``.
    """
    if not isinstance(brief, dict):
        return None
    reg = brief.get("register")
    if isinstance(reg, str) and reg in _REGISTER_RECIPE_HINTS:
        return _REGISTER_RECIPE_HINTS[reg]
    im = brief.get("interaction_model")
    if isinstance(im, str) and im in _REGISTER_RECIPE_HINTS:
        return _REGISTER_RECIPE_HINTS[im]
    return None


def select_composition(
    page_type: str,
    archetype: Optional[str] = None,
    brief: Optional[dict] = None,
) -> Recipe:
    """Choose the composition recipe for a page.

    Deterministic pure lookup. Never raises; falls back to the default.

    Selection order:

    1. **Vocabulary authority** — if the archetype's vocabulary
       declared a ``dashboard_recipe``, use it verbatim.
    2. **Archetype hints** — hardcoded ``dev-tools`` → chart-grid,
       ``banking-platform`` → asymmetric-split, etc.
    3. **Brief tone** — ``register: analytical`` → asymmetric-split,
       ``interaction_model: triage`` → inspector-panel.
    4. **Safe default** — ``kpi-hero-split``.

    Args:
        page_type: The page's declared type (``dashboard``, ``list``,
            ``detail`` etc). Only ``dashboard`` currently participates
            in recipe selection; other types always return the default
            (they'll get their own recipes in a later slice).
        archetype: Optional archetype slug from the plan (e.g.
            ``banking-platform``, ``dev-tools``).
        brief: Optional brief dict — a subset of :class:`ProductBrief`
            with at least ``register`` and/or ``interaction_model``
            keys is enough.

    Returns:
        The chosen :class:`Recipe`. Never None.
    """
    # Only dashboards select alternate recipes today. List / detail /
    # form pages have their own composers and shape decisions; giving
    # them recipes is a follow-up. Keep the surface small until it's
    # proven on dashboards.
    if page_type != "dashboard":
        return get_default_recipe()

    # 1. Vocabulary declaration (highest authority). Only used when
    #    the name resolves to a real recipe — unknown values fall
    #    through so a typo doesn't force a bad shape.
    name = _vocab_recipe_for(archetype)
    if name and name in _REGISTRY:
        return _REGISTRY[name]

    # 2. Hardcoded archetype hint — the fallback keyed table.
    name = _archetype_hint_for(archetype)
    if name and name in _REGISTRY:
        return _REGISTRY[name]

    # 3. Brief tone (register / interaction_model).
    name = _brief_recipe_for(brief)
    if name and name in _REGISTRY:
        return _REGISTRY[name]

    # 4. Safe default.
    return get_default_recipe()


__all__ = [
    "DEFAULT_RECIPE",
    "Primitive",
    "Recipe",
    "get_default_recipe",
    "get_recipe",
    "list_recipes",
    "select_composition",
]

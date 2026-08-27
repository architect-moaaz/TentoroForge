"""Slice B — composition recipes registry + selector.

Selector is a pure deterministic lookup. No env flag, no fallback
that swallows unknown values. Vocabulary declaration wins over
hardcoded hints; hints win over brief tone; else safe default.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.composition_recipes import (
    DEFAULT_RECIPE,
    Primitive,
    Recipe,
    get_default_recipe,
    get_recipe,
    list_recipes,
    select_composition,
)


class TestRegistry:
    def test_default_is_kpi_hero_split(self):
        assert DEFAULT_RECIPE == "kpi-hero-split"
        r = get_default_recipe()
        assert r.name == "kpi-hero-split"
        assert r.root == Primitive.STACK

    def test_all_named_recipes_registered(self):
        names = {r.name for r in list_recipes()}
        # Six shipped in the initial registry per the spec.
        assert names == {
            "kpi-hero-split",
            "asymmetric-split",
            "chart-grid",
            "ranked-leaderboard",
            "command-center",
            "inspector-panel",
        }

    def test_every_recipe_has_slot_map_and_root(self):
        for r in list_recipes():
            assert r.root in {
                Primitive.STACK, Primitive.SPLIT_VIEW, Primitive.GRID,
                Primitive.SIDEBAR, Primitive.INSPECTOR_PANEL, Primitive.CLUSTER,
            }, f"{r.name}: unknown root {r.root}"
            assert r.slot_map, f"{r.name}: slot_map empty"
            assert r.when_it_fits, f"{r.name}: missing when_it_fits doc"

    def test_asymmetric_split_shape(self):
        r = get_recipe("asymmetric-split")
        assert r is not None
        assert r.root == Primitive.SPLIT_VIEW
        assert "primary" in r.slot_map
        assert "secondary" in r.slot_map
        assert r.hints.get("ratio") == "1fr 2fr"

    def test_chart_grid_shape(self):
        r = get_recipe("chart-grid")
        assert r is not None
        assert r.root == Primitive.GRID
        # No KPIs and no hero — pure chart layout
        for slot_kinds in r.slot_map.values():
            for k in slot_kinds:
                assert k not in ("kpis", "hero"), \
                    f"chart-grid must not carry a {k} slot"

    def test_unknown_recipe_returns_none(self):
        assert get_recipe("nonsense") is None


class TestSelectorPageType:
    def test_non_dashboard_page_gets_default(self):
        # List/detail/form don't participate in recipe selection yet —
        # they always return the safe default until they get their own
        # recipes in a follow-up slice.
        for kind in ("list", "detail", "form", "auth", "calendar", "kanban"):
            assert select_composition(kind, archetype="banking-platform").name == "kpi-hero-split", \
                f"{kind} should return default"


class TestSelectorArchetypeHints:
    def test_banking_platform_maps_to_asymmetric_split(self):
        r = select_composition("dashboard", archetype="banking-platform")
        assert r.name == "asymmetric-split"

    def test_dev_tools_maps_to_chart_grid(self):
        r = select_composition("dashboard", archetype="dev-tools")
        assert r.name == "chart-grid"

    def test_observability_maps_to_chart_grid(self):
        r = select_composition("dashboard", archetype="observability")
        assert r.name == "chart-grid"

    def test_crm_maps_to_inspector_panel(self):
        r = select_composition("dashboard", archetype="crm")
        assert r.name == "inspector-panel"

    def test_dispatch_maps_to_command_center(self):
        r = select_composition("dashboard", archetype="dispatch")
        assert r.name == "command-center"

    def test_unknown_archetype_falls_through(self):
        r = select_composition("dashboard", archetype="wibble-wobble")
        assert r.name == "kpi-hero-split"


class TestSelectorBriefTone:
    def test_analytical_register_maps_to_asymmetric_split(self):
        r = select_composition("dashboard", archetype=None,
                                brief={"register": "analytical"})
        assert r.name == "asymmetric-split"

    def test_operational_maps_to_command_center(self):
        r = select_composition("dashboard", archetype=None,
                                brief={"register": "operational"})
        assert r.name == "command-center"

    def test_interaction_model_triage_maps_to_inspector(self):
        r = select_composition("dashboard", archetype=None,
                                brief={"interaction_model": "triage"})
        assert r.name == "inspector-panel"

    def test_unknown_register_falls_through(self):
        r = select_composition("dashboard", archetype=None,
                                brief={"register": "confused"})
        assert r.name == "kpi-hero-split"

    def test_no_hints_returns_default(self):
        assert select_composition("dashboard").name == "kpi-hero-split"


class TestSelectorPriority:
    def test_archetype_wins_over_brief_tone(self):
        # dev-tools → chart-grid should override brief.register=analytical
        # (analytical → asymmetric-split) because archetype hints run first.
        r = select_composition("dashboard", archetype="dev-tools",
                                brief={"register": "analytical"})
        assert r.name == "chart-grid"

    def test_vocab_declaration_wins_over_archetype_hints(self):
        """A vocabulary that declares ``dashboard_recipe='command-center'``
        for the banking archetype should override the hardcoded
        ``banking-platform → asymmetric-split`` hint.
        """
        class FakeVocab:
            dashboard_recipe = "command-center"

        with patch("services.composition_recipes.load_vocabulary",
                   create=True, return_value=FakeVocab()) as _mock:
            # patch the imported name inside select_composition's
            # lookup — since it uses a nested import, patch there.
            import services.composition_recipes as cr
            with patch.object(cr, "_vocab_recipe_for",
                              return_value="command-center"):
                r = cr.select_composition("dashboard",
                                            archetype="banking-platform")
                assert r.name == "command-center"

    def test_vocab_unknown_name_falls_through(self):
        """A vocabulary that declares a recipe NAME the registry doesn't
        know silently falls through to the archetype hints — never
        raises, never returns an invalid recipe.
        """
        import services.composition_recipes as cr
        with patch.object(cr, "_vocab_recipe_for", return_value="wibble"):
            # banking-platform hint should still apply
            r = cr.select_composition("dashboard",
                                        archetype="banking-platform")
            # Because _vocab_recipe_for returned an unknown, it's dropped
            # and the archetype hint wins.
            assert r.name == "asymmetric-split"


class TestNeverRaise:
    def test_none_page_type_returns_default(self):
        # A defensive input check — the module should never raise on
        # weird callers.
        assert select_composition(None, archetype="banking-platform").name == "kpi-hero-split"  # type: ignore[arg-type]

    def test_non_dict_brief_ignored(self):
        r = select_composition("dashboard", archetype="banking-platform",
                                brief="not-a-dict")  # type: ignore[arg-type]
        # archetype still wins
        assert r.name == "asymmetric-split"

"""Tests for the analytics-dashboard-platform archetype vocabulary."""
from __future__ import annotations

import pytest

from services.archetype_vocabulary import (
    KNOWN_SHAPES,
    clear_cache,
    known_archetypes,
    load_vocabulary,
)


_VALID_VARIANTS = {"success", "warning", "danger", "neutral", "accent"}


def _vocab():
    clear_cache()
    v = load_vocabulary("analytics-dashboard-platform")
    assert v is not None
    return v


class TestAnalyticsDashboardRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "analytics-dashboard-platform" in known_archetypes()

    def test_vocab_loads_via_registry(self):
        v = _vocab()
        assert v.id == "analytics-dashboard-platform"

    def test_load_normalises_input(self):
        for raw in ("Analytics Dashboard Platform",
                    "analytics_dashboard_platform",
                    "ANALYTICS-DASHBOARD-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "analytics-dashboard-platform"


class TestAnalyticsDashboardPersonas:
    def test_analyst_aliases_registered(self):
        v = _vocab()
        for alias in ("analyst", "data_analyst"):
            assert alias in v.primary_screens_per_persona, alias

    def test_viewer_aliases_registered(self):
        v = _vocab()
        for alias in ("viewer", "business_user"):
            assert alias in v.primary_screens_per_persona, alias

    def test_admin_aliases_registered(self):
        v = _vocab()
        for alias in ("admin", "bi_admin"):
            assert alias in v.primary_screens_per_persona, alias

    def test_data_engineer_present(self):
        v = _vocab()
        assert "data_engineer" in v.primary_screens_per_persona

    def test_analyst_screens_cover_core_surfaces(self):
        v = _vocab()
        screens = v.primary_screens_per_persona["analyst"]
        assert "dashboards" in screens
        assert "datasets" in screens


class TestAnalyticsDashboardSectionRecipes:
    def test_dashboards_split(self):
        v = _vocab()
        assert v.section_recipes["dashboards"] == [
            "mine", "shared-with-me", "recently-viewed",
        ]

    def test_datasources_state(self):
        v = _vocab()
        assert v.section_recipes["datasources"] == [
            "connected", "disconnected", "failed",
        ]


@pytest.mark.parametrize("entity", [
    "dashboards", "queries", "reports", "datasets", "datasources",
    "collections", "query_runs", "users",
])
class TestAnalyticsDashboardComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None, f"{entity} preference missing"
        assert pref.shape in KNOWN_SHAPES


class TestAnalyticsDashboardComponentSemantics:
    def test_dashboards_is_card_grid(self):
        v = _vocab()
        assert v.component_preferences["dashboards"].shape == "card-grid"

    def test_queries_is_card_list(self):
        v = _vocab()
        assert v.component_preferences["queries"].shape == "card-list"

    def test_query_runs_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["query_runs"].shape == "ledger-list"

    def test_users_is_admin_scoped(self):
        v = _vocab()
        pref = v.component_preferences["users"]
        assert pref.context.lower() == "admin"


class TestAnalyticsDashboardSignatureStates:
    def test_empty_state_per_section_split(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for section in union:
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_empty_dashboards_populated(self):
        v = _vocab()
        assert v.signature_states.get("empty_dashboards")

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestAnalyticsDashboardSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, \
                f"section {name!r} has no filter entry"


class TestAnalyticsDashboardStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_scheduled_is_accent(self):
        v = _vocab()
        assert v.status_badges["scheduled"]["variant"] == "accent"

    def test_failed_is_danger(self):
        v = _vocab()
        assert v.status_badges["failed"]["variant"] == "danger"

    def test_connected_is_success(self):
        v = _vocab()
        assert v.status_badges["connected"]["variant"] == "success"

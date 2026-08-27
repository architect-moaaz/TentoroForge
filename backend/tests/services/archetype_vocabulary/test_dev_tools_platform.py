"""Tests for the dev-tools-platform archetype vocabulary."""
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
    v = load_vocabulary("dev-tools-platform")
    assert v is not None
    return v


class TestDevToolsRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "dev-tools-platform" in known_archetypes()

    def test_vocab_loads_via_registry(self):
        v = _vocab()
        assert v.id == "dev-tools-platform"

    def test_load_normalises_input(self):
        for raw in ("Dev Tools Platform", "dev_tools_platform",
                    "DEV-TOOLS-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "dev-tools-platform"


class TestDevToolsPersonas:
    def test_developer_aliases_registered(self):
        v = _vocab()
        for alias in ("developer", "engineer"):
            assert alias in v.primary_screens_per_persona, alias

    def test_sre_aliases_registered(self):
        v = _vocab()
        for alias in ("sre", "ops", "oncall"):
            assert alias in v.primary_screens_per_persona, alias

    def test_admin_aliases_registered(self):
        v = _vocab()
        for alias in ("admin", "platform_admin"):
            assert alias in v.primary_screens_per_persona, alias

    def test_viewer_present(self):
        v = _vocab()
        assert "viewer" in v.primary_screens_per_persona

    def test_sre_gets_incidents_screen(self):
        v = _vocab()
        assert "incidents" in v.primary_screens_per_persona["sre"]
        assert "oncall" in v.primary_screens_per_persona["sre"]


class TestDevToolsSectionRecipes:
    def test_builds_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["builds"] == [
            "running", "passed", "failed", "cancelled",
        ]

    def test_deployments_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["deployments"] == [
            "succeeded", "in-progress", "rolled-back", "failed",
        ]

    def test_incidents_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["incidents"] == [
            "open", "investigating", "monitoring", "resolved",
        ]


@pytest.mark.parametrize("entity", [
    "builds", "deployments", "errors", "alerts", "incidents",
    "oncall_shifts", "dashboards", "projects", "audit_log",
])
class TestDevToolsComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None, f"{entity} preference missing"
        assert pref.shape in KNOWN_SHAPES


class TestDevToolsComponentSemantics:
    def test_builds_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["builds"].shape == "ledger-list"

    def test_errors_is_kanban(self):
        v = _vocab()
        assert v.component_preferences["errors"].shape == "kanban"

    def test_incidents_is_kanban(self):
        v = _vocab()
        assert v.component_preferences["incidents"].shape == "kanban"

    def test_oncall_shifts_is_schedule_grid(self):
        v = _vocab()
        assert v.component_preferences["oncall_shifts"].shape == "schedule-grid"

    def test_alerts_is_table(self):
        v = _vocab()
        assert v.component_preferences["alerts"].shape == "table"


class TestDevToolsSignatureStates:
    def test_empty_state_per_section_split(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for section in union:
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_empty_builds_populated(self):
        v = _vocab()
        assert v.signature_states.get("empty_builds")

    def test_empty_incidents_populated(self):
        v = _vocab()
        assert v.signature_states.get("empty_incidents")

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestDevToolsSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, \
                f"section {name!r} has no filter entry"


class TestDevToolsStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_passed_is_success(self):
        v = _vocab()
        assert v.status_badges["passed"]["variant"] == "success"

    def test_failed_is_danger(self):
        v = _vocab()
        assert v.status_badges["failed"]["variant"] == "danger"

    def test_firing_is_danger(self):
        v = _vocab()
        assert v.status_badges["firing"]["variant"] == "danger"

    def test_healthy_is_success(self):
        v = _vocab()
        assert v.status_badges["healthy"]["variant"] == "success"

    def test_monitoring_is_accent(self):
        v = _vocab()
        assert v.status_badges["monitoring"]["variant"] == "accent"

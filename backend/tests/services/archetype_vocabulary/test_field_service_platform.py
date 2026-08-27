"""Tests for the field-service-platform archetype vocabulary."""
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
    v = load_vocabulary("field-service-platform")
    assert v is not None
    return v


class TestFieldServiceRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "field-service-platform" in known_archetypes()

    def test_load_normalises_input(self):
        for raw in ("Field Service Platform", "field_service_platform"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "field-service-platform"


class TestFieldServicePersonas:
    def test_technician_aliases_present(self):
        v = _vocab()
        for alias in ("technician", "tech", "field_engineer"):
            assert alias in v.primary_screens_per_persona, alias

    def test_dispatcher_role_present(self):
        v = _vocab()
        assert "dispatcher" in v.primary_screens_per_persona

    def test_service_manager_aliases_present(self):
        v = _vocab()
        assert any(k in v.primary_screens_per_persona
                    for k in ("service_manager", "manager"))

    def test_customer_and_admin_present(self):
        v = _vocab()
        assert "customer" in v.primary_screens_per_persona
        assert "admin" in v.primary_screens_per_persona

    def test_dispatcher_gets_dispatch_board(self):
        v = _vocab()
        assert "dispatch-board" in v.primary_screens_per_persona["dispatcher"]


class TestFieldServiceSectionRecipes:
    def test_jobs_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["jobs"] == [
            "scheduled", "in-progress", "completed", "cancelled",
        ]

    def test_dispatch_board_columns(self):
        v = _vocab()
        assert v.section_recipes["dispatch-board"] == [
            "unassigned", "assigned", "en-route", "onsite",
        ]


@pytest.mark.parametrize("entity", [
    "jobs", "work_orders", "service_requests", "technicians", "customers",
    "parts", "checklists", "schedule", "time_entries",
])
class TestFieldServiceComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None and pref.shape in KNOWN_SHAPES


class TestFieldServiceComponentSemantics:
    def test_jobs_is_kanban(self):
        v = _vocab()
        assert v.component_preferences["jobs"].shape == "kanban"

    def test_parts_is_table(self):
        v = _vocab()
        assert v.component_preferences["parts"].shape == "table"

    def test_schedule_is_schedule_grid(self):
        v = _vocab()
        assert v.component_preferences["schedule"].shape == "schedule-grid"

    def test_time_entries_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["time_entries"].shape == "ledger-list"


class TestFieldServiceSignatureStates:
    def test_empty_state_per_dispatch_column(self):
        v = _vocab()
        for section in ("unassigned", "assigned", "en_route", "onsite"):
            key = f"empty_{section}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestFieldServiceSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, f"section {name!r} has no filter"


class TestFieldServiceStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_completed_is_success(self):
        v = _vocab()
        assert v.status_badges["completed"]["variant"] == "success"

    def test_escalated_is_danger(self):
        v = _vocab()
        assert v.status_badges["escalated"]["variant"] == "danger"

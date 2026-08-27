"""Tests for the project-platform archetype vocabulary."""
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
    v = load_vocabulary("project-platform")
    assert v is not None
    return v


class TestProjectRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "project-platform" in known_archetypes()

    def test_load_normalises_input(self):
        for raw in ("Project Platform", "project_platform"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "project-platform"


class TestProjectPersonas:
    def test_contributor_aliases_present(self):
        v = _vocab()
        for alias in ("contributor", "team_member"):
            assert alias in v.primary_screens_per_persona

    def test_pm_aliases_present(self):
        v = _vocab()
        for alias in ("project_manager", "pm", "manager"):
            assert alias in v.primary_screens_per_persona

    def test_admin_and_client_present(self):
        v = _vocab()
        assert "admin" in v.primary_screens_per_persona
        assert "client" in v.primary_screens_per_persona

    def test_pm_gets_projects_and_tasks(self):
        v = _vocab()
        screens = v.primary_screens_per_persona["project_manager"]
        assert "projects" in screens
        assert "tasks" in screens


class TestProjectSectionRecipes:
    def test_tasks_board_columns(self):
        v = _vocab()
        assert v.section_recipes["tasks"] == [
            "todo", "in-progress", "review", "done",
        ]

    def test_projects_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["projects"] == [
            "active", "on-hold", "completed", "archived",
        ]


@pytest.mark.parametrize("entity", [
    "projects", "tasks", "milestones", "timesheets", "team_members",
    "clients", "invoices", "messages",
])
class TestProjectComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None and pref.shape in KNOWN_SHAPES


class TestProjectComponentSemantics:
    def test_tasks_is_kanban(self):
        v = _vocab()
        assert v.component_preferences["tasks"].shape == "kanban"

    def test_projects_is_card_grid(self):
        v = _vocab()
        assert v.component_preferences["projects"].shape == "card-grid"

    def test_timesheets_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["timesheets"].shape == "ledger-list"

    def test_invoices_is_table(self):
        v = _vocab()
        assert v.component_preferences["invoices"].shape == "table"


class TestProjectSignatureStates:
    def test_empty_state_per_board_column(self):
        v = _vocab()
        for section in ("todo", "in_progress", "review", "done"):
            key = f"empty_{section}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestProjectSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, f"section {name!r} has no filter"


class TestProjectStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_done_is_success(self):
        v = _vocab()
        assert v.status_badges["done"]["variant"] == "success"

    def test_blocked_is_danger(self):
        v = _vocab()
        assert v.status_badges["blocked"]["variant"] == "danger"

    def test_review_is_accent(self):
        v = _vocab()
        assert v.status_badges["review"]["variant"] == "accent"

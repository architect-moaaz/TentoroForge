"""Tests for the learning-platform archetype vocabulary."""
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
    v = load_vocabulary("learning-platform")
    assert v is not None
    return v


class TestLearningRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "learning-platform" in known_archetypes()

    def test_load_normalises_input(self):
        for raw in ("Learning Platform", "learning_platform", "LEARNING-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "learning-platform"


class TestLearningPersonas:
    def test_student_aliases_present(self):
        v = _vocab()
        for alias in ("student", "learner"):
            assert alias in v.primary_screens_per_persona

    def test_instructor_aliases_present(self):
        v = _vocab()
        for alias in ("instructor", "teacher"):
            assert alias in v.primary_screens_per_persona

    def test_admin_role_present(self):
        v = _vocab()
        assert "admin" in v.primary_screens_per_persona

    def test_student_gets_my_courses(self):
        v = _vocab()
        assert "my-courses" in v.primary_screens_per_persona["student"]


class TestLearningSectionRecipes:
    def test_my_courses_split(self):
        v = _vocab()
        assert v.section_recipes["my-courses"] == [
            "in-progress", "completed", "not-started",
        ]

    def test_assignments_split(self):
        v = _vocab()
        assert v.section_recipes["assignments"] == [
            "due-soon", "submitted", "graded",
        ]


@pytest.mark.parametrize("entity", [
    "courses", "lessons", "enrollments", "assignments", "quizzes",
    "submissions", "certificates", "students",
])
class TestLearningComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None and pref.shape in KNOWN_SHAPES


class TestLearningComponentSemantics:
    def test_courses_is_card_grid(self):
        v = _vocab()
        assert v.component_preferences["courses"].shape == "card-grid"

    def test_enrollments_is_table(self):
        v = _vocab()
        assert v.component_preferences["enrollments"].shape == "table"

    def test_submissions_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["submissions"].shape == "ledger-list"


class TestLearningSignatureStates:
    def test_empty_state_per_split(self):
        v = _vocab()
        for section in ("in-progress", "completed", "not-started",
                         "due-soon", "submitted", "graded"):
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestLearningSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, f"section {name!r} has no filter"


class TestLearningStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_completed_is_success(self):
        v = _vocab()
        assert v.status_badges["completed"]["variant"] == "success"

    def test_failed_is_danger(self):
        v = _vocab()
        assert v.status_badges["failed"]["variant"] == "danger"

    def test_overdue_is_danger(self):
        v = _vocab()
        assert v.status_badges["overdue"]["variant"] == "danger"

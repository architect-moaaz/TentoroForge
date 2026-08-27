"""Tests for the content-platform archetype vocabulary."""
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
    v = load_vocabulary("content-platform")
    assert v is not None
    return v


class TestContentRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "content-platform" in known_archetypes()

    def test_load_normalises_input(self):
        for raw in ("Content Platform", "content_platform", "CONTENT-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "content-platform"


class TestContentPersonas:
    def test_writer_aliases_present(self):
        v = _vocab()
        for alias in ("writer", "author"):
            assert alias in v.primary_screens_per_persona

    def test_editor_role_present(self):
        v = _vocab()
        assert "editor" in v.primary_screens_per_persona

    def test_admin_role_present(self):
        v = _vocab()
        assert "admin" in v.primary_screens_per_persona

    def test_writer_gets_drafts(self):
        v = _vocab()
        assert "drafts" in v.primary_screens_per_persona["writer"]


class TestContentSectionRecipes:
    def test_articles_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["articles"] == [
            "draft", "in-review", "published", "archived",
        ]

    def test_review_queue_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["review-queue"] == [
            "submitted", "revising", "approved",
        ]


@pytest.mark.parametrize("entity", [
    "articles", "posts", "media", "categories", "tags", "comments", "authors",
])
class TestContentComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None and pref.shape in KNOWN_SHAPES


class TestContentComponentSemantics:
    def test_articles_is_card_list(self):
        v = _vocab()
        assert v.component_preferences["articles"].shape == "card-list"

    def test_tags_is_table(self):
        v = _vocab()
        assert v.component_preferences["tags"].shape == "table"

    def test_comments_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["comments"].shape == "ledger-list"


class TestContentSignatureStates:
    def test_empty_state_per_lifecycle(self):
        v = _vocab()
        for section in ("draft", "in-review", "published", "archived"):
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestContentSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, f"section {name!r} has no filter"


class TestContentStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_published_is_success(self):
        v = _vocab()
        assert v.status_badges["published"]["variant"] == "success"

    def test_scheduled_is_accent(self):
        v = _vocab()
        assert v.status_badges["scheduled"]["variant"] == "accent"

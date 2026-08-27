"""Tests for the messaging-platform archetype vocabulary."""
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
    v = load_vocabulary("messaging-platform")
    assert v is not None
    return v


class TestMessagingRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "messaging-platform" in known_archetypes()

    def test_vocab_loads_via_registry(self):
        v = _vocab()
        assert v.id == "messaging-platform"

    def test_load_normalises_input(self):
        for raw in ("Messaging Platform", "messaging_platform",
                    "MESSAGING-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "messaging-platform"


class TestMessagingPersonas:
    def test_member_aliases_registered(self):
        v = _vocab()
        for alias in ("member", "user"):
            assert alias in v.primary_screens_per_persona, alias

    def test_admin_aliases_registered(self):
        v = _vocab()
        for alias in ("workspace_admin", "admin"):
            assert alias in v.primary_screens_per_persona, alias

    def test_guest_aliases_registered(self):
        v = _vocab()
        for alias in ("guest", "external_member"):
            assert alias in v.primary_screens_per_persona, alias

    def test_member_screens_cover_core_surfaces(self):
        v = _vocab()
        screens = v.primary_screens_per_persona["member"]
        assert "channels" in screens
        assert "dms" in screens
        assert "mentions" in screens


class TestMessagingSectionRecipes:
    def test_channels_split(self):
        v = _vocab()
        assert v.section_recipes["channels"] == [
            "joined", "browse-all", "archived",
        ]

    def test_dms_split(self):
        v = _vocab()
        assert v.section_recipes["dms"] == ["recent", "unread", "muted"]

    def test_mentions_windows(self):
        v = _vocab()
        assert v.section_recipes["mentions"] == ["today", "this-week", "all"]


@pytest.mark.parametrize("entity", [
    "channels", "messages", "dms", "threads", "members", "integrations",
    "audit_log",
])
class TestMessagingComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None, f"{entity} preference missing"
        assert pref.shape in KNOWN_SHAPES


class TestMessagingComponentSemantics:
    def test_channels_is_card_list(self):
        v = _vocab()
        assert v.component_preferences["channels"].shape == "card-list"

    def test_messages_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["messages"].shape == "ledger-list"

    def test_integrations_is_card_grid(self):
        v = _vocab()
        assert v.component_preferences["integrations"].shape == "card-grid"

    def test_members_is_admin_scoped(self):
        v = _vocab()
        pref = v.component_preferences["members"]
        assert pref.context.lower() == "admin"


class TestMessagingSignatureStates:
    def test_empty_state_per_section_split(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for section in union:
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_empty_channels_populated(self):
        v = _vocab()
        assert v.signature_states.get("empty_channels")

    def test_empty_mentions_populated(self):
        v = _vocab()
        assert v.signature_states.get("empty_mentions")

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestMessagingSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, \
                f"section {name!r} has no filter entry"


class TestMessagingStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_online_is_success(self):
        v = _vocab()
        assert v.status_badges["online"]["variant"] == "success"

    def test_dnd_is_danger(self):
        v = _vocab()
        assert v.status_badges["dnd"]["variant"] == "danger"

    def test_installed_is_success(self):
        v = _vocab()
        assert v.status_badges["installed"]["variant"] == "success"

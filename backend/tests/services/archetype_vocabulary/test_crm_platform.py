"""Tests for the crm-platform archetype vocabulary."""
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
    v = load_vocabulary("crm-platform")
    assert v is not None
    return v


class TestCrmRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "crm-platform" in known_archetypes()

    def test_vocab_loads_via_registry(self):
        v = _vocab()
        assert v.id == "crm-platform"

    def test_load_normalises_input(self):
        for raw in ("CRM Platform", "crm_platform", "CRM-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None
            assert v.id == "crm-platform"


class TestCrmPersonas:
    """Sales orgs describe the same role a dozen different ways;
    every alias must land on the same primary-screens list."""

    def test_sales_rep_aliases_all_registered(self):
        v = _vocab()
        for alias in ("salesperson", "sales_rep", "ae", "account_executive",
                       "account_manager"):
            assert alias in v.primary_screens_per_persona, alias

    def test_sales_rep_covers_deals_and_contacts(self):
        v = _vocab()
        for alias in ("salesperson", "sales_rep"):
            screens = v.primary_screens_per_persona[alias]
            assert "deals" in screens
            assert "contacts" in screens

    def test_manager_role_present(self):
        v = _vocab()
        keys = v.primary_screens_per_persona.keys()
        assert any(k in keys for k in ("sales_manager", "manager"))

    def test_admin_role_present(self):
        v = _vocab()
        assert "admin" in v.primary_screens_per_persona


class TestCrmSectionRecipes:
    def test_deals_splits_open_won_lost(self):
        v = _vocab()
        assert v.section_recipes["deals"] == ["open", "won", "lost"]

    def test_activities_splits_today_upcoming_overdue(self):
        v = _vocab()
        assert v.section_recipes["activities"] == ["today", "upcoming", "overdue"]

    def test_contacts_splits_hot_warm_cold(self):
        v = _vocab()
        assert v.section_recipes["contacts"] == ["hot", "warm", "cold"]


@pytest.mark.parametrize("entity", [
    "deals", "contacts", "activities", "tasks", "products", "companies",
])
class TestCrmComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None, f"{entity} preference missing"
        assert pref.shape in KNOWN_SHAPES, f"{entity} shape={pref.shape!r} not in KNOWN_SHAPES"


class TestCrmComponentSemantics:
    def test_deals_shape_is_kanban(self):
        v = _vocab()
        assert v.component_preferences["deals"].shape == "kanban"

    def test_activities_shape_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["activities"].shape == "ledger-list"


class TestCrmSignatureStates:
    def test_empty_state_per_section_split(self):
        v = _vocab()
        # Every section in section_recipes needs an empty_<section> entry
        # so the emit-empty-state pass has copy to reach for.
        for section in ("open", "won", "lost", "today", "upcoming",
                         "overdue", "hot", "warm", "cold"):
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestCrmSectionFilters:
    def test_section_filter_keys_cover_recipe_values(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        # Every section named in a recipe should have a matching filter
        # entry (may be an empty dict for date-driven splits).
        for name in union:
            assert name in v.section_filters, f"section {name!r} has no filter entry"


class TestCrmStatusBadges:
    def test_all_variants_are_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta.get("variant") in _VALID_VARIANTS, \
                f"{status}: variant {meta.get('variant')!r} not valid"

    def test_won_is_success(self):
        v = _vocab()
        assert v.status_badges["won"]["variant"] == "success"

    def test_lost_is_danger(self):
        v = _vocab()
        assert v.status_badges["lost"]["variant"] == "danger"

    def test_hot_is_danger(self):
        v = _vocab()
        assert v.status_badges["hot"]["variant"] == "danger"

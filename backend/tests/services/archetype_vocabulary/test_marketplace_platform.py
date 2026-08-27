"""Tests for the marketplace-platform archetype vocabulary."""
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
    v = load_vocabulary("marketplace-platform")
    assert v is not None
    return v


class TestMarketplaceRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "marketplace-platform" in known_archetypes()

    def test_load_normalises_input(self):
        for raw in ("Marketplace Platform", "marketplace_platform"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "marketplace-platform"


class TestMarketplacePersonas:
    def test_buyer_aliases_present(self):
        v = _vocab()
        for alias in ("buyer", "shopper", "customer"):
            assert alias in v.primary_screens_per_persona

    def test_seller_aliases_present(self):
        v = _vocab()
        for alias in ("seller", "vendor"):
            assert alias in v.primary_screens_per_persona

    def test_admin_aliases_present(self):
        v = _vocab()
        for alias in ("admin", "marketplace_admin"):
            assert alias in v.primary_screens_per_persona

    def test_buyer_gets_browse_and_orders(self):
        v = _vocab()
        screens = v.primary_screens_per_persona["buyer"]
        assert "browse" in screens
        assert "my-orders" in screens


class TestMarketplaceSectionRecipes:
    def test_listings_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["listings"] == [
            "active", "sold", "draft", "flagged",
        ]

    def test_disputes_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["disputes"] == [
            "open", "under-review", "resolved",
        ]


@pytest.mark.parametrize("entity", [
    "listings", "orders", "sellers", "reviews", "messages",
    "disputes",
])
class TestMarketplaceComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None and pref.shape in KNOWN_SHAPES


class TestMarketplaceComponentSemantics:
    def test_listings_is_card_grid(self):
        v = _vocab()
        assert v.component_preferences["listings"].shape == "card-grid"

    def test_orders_is_card_list(self):
        v = _vocab()
        assert v.component_preferences["orders"].shape == "card-list"

    def test_disputes_is_table(self):
        v = _vocab()
        assert v.component_preferences["disputes"].shape == "table"

    def test_buyers_is_admin_scoped(self):
        v = _vocab()
        pref = v.component_preferences["buyers"]
        assert pref.context.lower() == "admin"


class TestMarketplaceSignatureStates:
    def test_empty_state_per_split(self):
        v = _vocab()
        for section in ("active", "sold", "draft", "flagged",
                         "pending", "shipped", "delivered"):
            key = f"empty_{section}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestMarketplaceSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, f"section {name!r} has no filter"


class TestMarketplaceStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_delivered_is_success(self):
        v = _vocab()
        assert v.status_badges["delivered"]["variant"] == "success"

    def test_disputed_is_danger(self):
        v = _vocab()
        assert v.status_badges["disputed"]["variant"] == "danger"

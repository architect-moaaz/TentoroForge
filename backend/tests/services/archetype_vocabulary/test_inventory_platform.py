"""Tests for the inventory-platform archetype vocabulary."""
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
    v = load_vocabulary("inventory-platform")
    assert v is not None
    return v


class TestInventoryRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "inventory-platform" in known_archetypes()

    def test_load_normalises_input(self):
        for raw in ("Inventory Platform", "inventory_platform", "INVENTORY-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "inventory-platform"


class TestInventoryPersonas:
    def test_warehouse_worker_aliases_present(self):
        v = _vocab()
        for alias in ("warehouse_worker", "picker"):
            assert alias in v.primary_screens_per_persona, alias

    def test_warehouse_manager_and_buyer_present(self):
        v = _vocab()
        assert any(k in v.primary_screens_per_persona for k in ("warehouse_manager", "manager"))
        assert "buyer" in v.primary_screens_per_persona

    def test_admin_role_present(self):
        v = _vocab()
        assert "admin" in v.primary_screens_per_persona

    def test_worker_gets_orders_and_receiving(self):
        v = _vocab()
        screens = v.primary_screens_per_persona["warehouse_worker"]
        assert "orders" in screens
        assert "receiving" in screens


class TestInventorySectionRecipes:
    def test_inventory_splits_in_low_out(self):
        v = _vocab()
        assert v.section_recipes["inventory"] == ["in-stock", "low-stock", "out-of-stock"]

    def test_purchase_orders_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["purchase-orders"] == [
            "draft", "submitted", "received", "closed",
        ]


@pytest.mark.parametrize("entity", [
    "products", "skus", "inventory", "orders", "purchase_orders",
    "warehouses", "suppliers", "stock_movements",
])
class TestInventoryComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None, f"{entity} preference missing"
        assert pref.shape in KNOWN_SHAPES


class TestInventoryComponentSemantics:
    def test_products_is_table(self):
        v = _vocab()
        assert v.component_preferences["products"].shape == "table"

    def test_orders_is_card_list(self):
        v = _vocab()
        assert v.component_preferences["orders"].shape == "card-list"

    def test_stock_movements_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["stock_movements"].shape == "ledger-list"


class TestInventorySignatureStates:
    def test_empty_state_per_stock_split(self):
        v = _vocab()
        for section in ("in-stock", "low-stock", "out-of-stock"):
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestInventorySectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, f"section {name!r} has no filter entry"


class TestInventoryStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_low_stock_is_warning(self):
        v = _vocab()
        assert v.status_badges["low_stock"]["variant"] == "warning"

    def test_out_of_stock_is_danger(self):
        v = _vocab()
        assert v.status_badges["out_of_stock"]["variant"] == "danger"

    def test_received_is_success(self):
        v = _vocab()
        assert v.status_badges["received"]["variant"] == "success"

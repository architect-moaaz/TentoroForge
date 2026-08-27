"""Tests for the payment-processing-platform archetype vocabulary."""
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
    v = load_vocabulary("payment-processing-platform")
    assert v is not None
    return v


class TestPaymentProcessingRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "payment-processing-platform" in known_archetypes()

    def test_vocab_loads_via_registry(self):
        v = _vocab()
        assert v.id == "payment-processing-platform"

    def test_load_normalises_input(self):
        for raw in ("Payment Processing Platform",
                    "payment_processing_platform",
                    "PAYMENT-PROCESSING-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "payment-processing-platform"


class TestPaymentProcessingPersonas:
    def test_merchant_aliases_registered(self):
        v = _vocab()
        for alias in ("merchant", "business_owner", "store_owner"):
            assert alias in v.primary_screens_per_persona, alias

    def test_admin_aliases_registered(self):
        v = _vocab()
        for alias in ("payment_admin", "admin"):
            assert alias in v.primary_screens_per_persona, alias

    def test_support_aliases_registered(self):
        v = _vocab()
        for alias in ("support", "payment_support", "agent"):
            assert alias in v.primary_screens_per_persona, alias

    def test_merchant_screens_cover_core_surfaces(self):
        v = _vocab()
        screens = v.primary_screens_per_persona["merchant"]
        assert "payments" in screens
        assert "disputes" in screens
        assert "payouts" in screens


class TestPaymentProcessingSectionRecipes:
    def test_payments_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["payments"] == [
            "succeeded", "pending", "failed", "refunded",
        ]

    def test_disputes_flow(self):
        v = _vocab()
        assert v.section_recipes["disputes"] == [
            "needs-response", "under-review", "won", "lost",
        ]

    def test_payouts_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["payouts"] == [
            "in-transit", "paid", "failed",
        ]


@pytest.mark.parametrize("entity", [
    "payments", "transactions", "charges", "customers", "disputes",
    "chargebacks", "payouts", "settlements", "merchants", "refunds",
    "payment_methods", "cards",
])
class TestPaymentProcessingComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None, f"{entity} preference missing"
        assert pref.shape in KNOWN_SHAPES, \
            f"{entity} shape={pref.shape!r} not in KNOWN_SHAPES"


class TestPaymentProcessingComponentSemantics:
    def test_payments_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["payments"].shape == "ledger-list"

    def test_disputes_is_kanban(self):
        v = _vocab()
        assert v.component_preferences["disputes"].shape == "kanban"

    def test_merchants_is_admin_scoped(self):
        v = _vocab()
        pref = v.component_preferences["merchants"]
        assert pref.context.lower() == "admin"

    def test_cards_is_card_list(self):
        v = _vocab()
        assert v.component_preferences["cards"].shape == "card-list"


class TestPaymentProcessingSignatureStates:
    def test_empty_state_per_section_split(self):
        v = _vocab()
        # Every unique section named in a recipe needs an empty_<section>
        # entry so the emit-empty-state pass has copy to reach for.
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for section in union:
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_empty_payments_populated(self):
        v = _vocab()
        assert v.signature_states.get("empty_payments")

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestPaymentProcessingSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, \
                f"section {name!r} has no filter entry"


class TestPaymentProcessingStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_succeeded_is_success(self):
        v = _vocab()
        assert v.status_badges["succeeded"]["variant"] == "success"

    def test_chargeback_is_danger(self):
        v = _vocab()
        assert v.status_badges["chargeback"]["variant"] == "danger"

    def test_needs_response_is_warning(self):
        v = _vocab()
        assert v.status_badges["needs_response"]["variant"] == "warning"

    def test_blocked_is_danger(self):
        v = _vocab()
        assert v.status_badges["blocked"]["variant"] == "danger"

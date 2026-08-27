"""Tests for the subscription-billing-platform archetype vocabulary."""
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
    v = load_vocabulary("subscription-billing-platform")
    assert v is not None
    return v


class TestSubscriptionBillingRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "subscription-billing-platform" in known_archetypes()

    def test_vocab_loads_via_registry(self):
        v = _vocab()
        assert v.id == "subscription-billing-platform"

    def test_load_normalises_input(self):
        for raw in ("Subscription Billing Platform",
                    "subscription_billing_platform",
                    "SUBSCRIPTION-BILLING-PLATFORM"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "subscription-billing-platform"


class TestSubscriptionBillingPersonas:
    def test_customer_aliases_registered(self):
        v = _vocab()
        for alias in ("customer", "subscriber"):
            assert alias in v.primary_screens_per_persona, alias

    def test_admin_aliases_registered(self):
        v = _vocab()
        for alias in ("billing_admin", "admin"):
            assert alias in v.primary_screens_per_persona, alias

    def test_finance_role_present(self):
        v = _vocab()
        assert "finance" in v.primary_screens_per_persona

    def test_support_aliases_registered(self):
        v = _vocab()
        for alias in ("support", "billing_support"):
            assert alias in v.primary_screens_per_persona, alias

    def test_customer_screens_cover_core_surfaces(self):
        v = _vocab()
        screens = v.primary_screens_per_persona["customer"]
        assert "my-subscription" in screens
        assert "invoices" in screens


class TestSubscriptionBillingSectionRecipes:
    def test_subscriptions_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["subscriptions"] == [
            "active", "trialing", "past-due", "cancelled", "paused",
        ]

    def test_invoices_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["invoices"] == [
            "draft", "sent", "paid", "overdue", "void",
        ]

    def test_dunning_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["dunning"] == [
            "retry-scheduled", "final-notice", "cancelled",
        ]


@pytest.mark.parametrize("entity", [
    "subscriptions", "invoices", "plans", "usage", "payment_methods",
    "dunning", "customers", "subscribers",
])
class TestSubscriptionBillingComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None, f"{entity} preference missing"
        assert pref.shape in KNOWN_SHAPES


class TestSubscriptionBillingComponentSemantics:
    def test_subscriptions_is_table(self):
        v = _vocab()
        assert v.component_preferences["subscriptions"].shape == "table"

    def test_invoices_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["invoices"].shape == "ledger-list"

    def test_plans_is_card_grid(self):
        v = _vocab()
        assert v.component_preferences["plans"].shape == "card-grid"

    def test_customers_is_admin_scoped(self):
        v = _vocab()
        pref = v.component_preferences["customers"]
        assert pref.context.lower() == "admin"


class TestSubscriptionBillingSignatureStates:
    def test_empty_state_per_section_split(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for section in union:
            key = f"empty_{section.replace('-', '_')}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_empty_subscriptions_populated(self):
        v = _vocab()
        assert v.signature_states.get("empty_subscriptions")

    def test_empty_dunning_populated(self):
        v = _vocab()
        assert v.signature_states.get("empty_dunning")

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestSubscriptionBillingSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, \
                f"section {name!r} has no filter entry"


class TestSubscriptionBillingStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_active_is_success(self):
        v = _vocab()
        assert v.status_badges["active"]["variant"] == "success"

    def test_past_due_is_danger(self):
        v = _vocab()
        assert v.status_badges["past_due"]["variant"] == "danger"

    def test_paid_is_success(self):
        v = _vocab()
        assert v.status_badges["paid"]["variant"] == "success"

    def test_grandfathered_is_accent(self):
        v = _vocab()
        assert v.status_badges["grandfathered"]["variant"] == "accent"

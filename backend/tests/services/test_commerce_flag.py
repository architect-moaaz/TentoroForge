"""Tests for services.commerce_flag (CART-P1).

The commerce flag is the planner-side gate that says "this entity is the
saleable one". Downstream deterministic passes (commerce_placement) read this
flag to auto-place AddToCart / CartBadge / CartPage. Keep the flag stable —
downstream code trusts exactly one entity per plan to be flagged.
"""

from __future__ import annotations

from services.commerce_flag import (
    detect_commerce_intent,
    flag_commerce_entity,
)


# ----- detect_commerce_intent ----------------------------------------------

class TestDetectCommerceIntent:
    def test_true_for_sell_verb(self):
        plan = {"brief": "sell products online"}
        assert detect_commerce_intent(plan) is True

    def test_true_for_cart_noun(self):
        plan = {"brief": "app with a shopping cart and checkout"}
        assert detect_commerce_intent(plan) is True

    def test_true_for_marketplace(self):
        plan = {"brief": "a nursery marketplace for customers"}
        assert detect_commerce_intent(plan) is True

    def test_reads_structured_brief(self):
        plan = {"structured_brief": {"summary": "customers buy plants"}}
        assert detect_commerce_intent(plan) is True

    def test_false_for_ops_brief(self):
        plan = {"brief": "internal inventory management for staff"}
        assert detect_commerce_intent(plan) is False

    def test_false_for_empty(self):
        assert detect_commerce_intent({}) is False

    def test_partial_word_does_not_match(self):
        # "shopping" and "shopper" are commerce cues, but "workshop" contains "shop"
        # only as a substring — the module uses word-boundary regex, so ensure it
        # doesn't false-positive.
        plan = {"brief": "an internal workshop scheduler for our team"}
        # workshop contains 'shop' but should not trigger via 'shop' whole-word.
        # dominant_intent should be ambiguous-or-ops, not commerce.
        assert detect_commerce_intent(plan) is False


# ----- flag_commerce_entity ------------------------------------------------

class TestFlagCommerceEntity:
    def test_flags_product_shaped_entity_on_commerce_brief(self):
        plan = {
            "brief": "sell handcrafted goods to customers",
            "entities": {
                "Plant": {"fields": [{"name": "name"}, {"name": "price"}, {"name": "imageUrl"}]},
                "User": {"fields": [{"name": "email"}]},
            },
        }
        r = flag_commerce_entity(plan)
        assert r["entities"]["Plant"]["commerce"] is True
        assert "commerce" not in r["entities"]["User"]

    def test_prefers_canonical_product_name(self):
        plan = {
            "brief": "storefront app",
            "entities": {
                "Product":  {"fields": [{"name": "title"}]},
                "Category": {"fields": [{"name": "slug"}]},
            },
        }
        r = flag_commerce_entity(plan)
        assert r["entities"]["Product"]["commerce"] is True

    def test_no_flag_when_no_commerce_brief(self):
        plan = {
            "brief": "internal inventory tracker for staff",
            "entities": {
                "Plant": {"fields": [{"name": "name"}, {"name": "stock"}]},
            },
        }
        r = flag_commerce_entity(plan)
        assert "commerce" not in r["entities"]["Plant"]

    def test_respects_existing_flag(self):
        plan = {
            "brief": "sell things",
            "entities": {
                "Widget": {"commerce": True, "fields": []},
                "Item": {"fields": [{"name": "price"}, {"name": "imageUrl"}]},
            },
        }
        r = flag_commerce_entity(plan)
        assert r["entities"]["Widget"]["commerce"] is True
        # Second one is not double-flagged.
        assert "commerce" not in r["entities"]["Item"]

    def test_idempotent(self):
        plan = {
            "brief": "sell plants",
            "entities": {
                "Plant": {"fields": [{"name": "price"}, {"name": "description"}]},
            },
        }
        r1 = flag_commerce_entity(plan)
        r2 = flag_commerce_entity(r1)
        assert r1["entities"]["Plant"]["commerce"] is True
        assert r2["entities"]["Plant"]["commerce"] is True

    def test_skips_users_and_orders(self):
        plan = {
            "brief": "customers buy things",
            "entities": {
                "User":  {"fields": [{"name": "email"}]},
                "Order": {"fields": [{"name": "total"}]},
                "Widget": {"fields": [{"name": "name"}, {"name": "price"}, {"name": "description"}]},
            },
        }
        r = flag_commerce_entity(plan)
        assert r["entities"]["Widget"]["commerce"] is True
        assert "commerce" not in r["entities"]["User"]
        assert "commerce" not in r["entities"]["Order"]

    def test_no_error_when_no_entities(self):
        r = flag_commerce_entity({"brief": "sell things"})
        assert r == {"brief": "sell things"}

    def test_no_error_when_no_brief(self):
        plan = {"entities": {"Plant": {"fields": []}}}
        r = flag_commerce_entity(plan)
        assert "commerce" not in r["entities"]["Plant"]

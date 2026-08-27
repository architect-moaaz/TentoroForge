"""Tests for Spec D Wave 2 — planner-authored `entity.needs_payment_methods`
precedence on payment_feature detection.

The regex-based transactional-amount fallback was REMOVED in Spec D W2 —
detection now runs only three signals:

  1. Planner-authored ``needs_payment_methods`` (True wins; False across
     the board opts out).
  2. Structural: an entity literally named ``PaymentMethod``/etc.
  3. Any entity flagged ``commerce: True``.
"""
from __future__ import annotations

from services.payment_feature import detect_payment_intent


class TestPlannerAuthoredWins:
    def test_planner_true_wins_over_no_other_signal(self):
        plan = {"entities": {"Widget": {"needs_payment_methods": True}}}
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is True
        assert r["reason"] == "planner:Widget"

    def test_planner_true_beats_structural_paymentmethod(self):
        # Even with a PaymentMethod entity present, an explicit planner
        # True on a different entity is the reported reason.
        plan = {
            "entities": {
                "PaymentMethod": {"fields": {"id": {}}},
                "Widget": {"needs_payment_methods": True},
            }
        }
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is True
        assert r["reason"] == "planner:Widget"


class TestPlannerOptOut:
    def test_all_false_flags_opt_out(self):
        # A single explicit False (with no True anywhere) opts the app
        # out of the payment surface, even if a structural signal would
        # otherwise have fired.
        plan = {
            "entities": {
                "PaymentMethod": {"needs_payment_methods": False},
            }
        }
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is False
        assert r["reason"] == "planner:opt-out"

    def test_opt_out_beats_commerce_signal(self):
        plan = {
            "entities": {
                "Product":  {"commerce": True},
                "Donation": {"needs_payment_methods": False},
            }
        }
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is False
        assert r["reason"] == "planner:opt-out"


class TestStructuralFallbacksPreserved:
    def test_no_planner_flags_paymentmethod_entity_still_fires(self):
        plan = {"entities": {"PaymentMethod": {}}}
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is True
        assert r["reason"] == "entity:PaymentMethod"

    def test_no_planner_flags_commerce_path_still_wins(self):
        plan = {"entities": {"Widget": {"commerce": True}}}
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is True
        assert r["reason"] == "commerce:Widget"

    def test_transactional_regex_fallback_removed(self):
        # Spec D W2 explicitly dropped the "Order/Booking has amount column"
        # regex fallback. Without an explicit planner signal or structural
        # PaymentMethod/commerce cue, detection is negative.
        plan = {
            "entities": {
                "Order": {"fields": [{"name": "total"}]},
            }
        }
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is False
        assert r["reason"] == "no signal"

    def test_no_signal_stays_false(self):
        plan = {"entities": {"Article": {"fields": [{"name": "title"}]}}}
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is False
        assert r["reason"] == "no signal"


class TestFlagShapeTolerance:
    def test_none_flag_falls_through_to_structural(self):
        # Only literal False triggers opt-out. A missing/None flag lets the
        # structural PaymentMethod signal fire.
        plan = {"entities": {"PaymentMethod": {"needs_payment_methods": None}}}
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is True
        assert r["reason"] == "entity:PaymentMethod"

    def test_truthy_non_bool_not_treated_as_true(self):
        # `needs_payment_methods: "yes"` isn't `True`. We accept only
        # the literal Python bool to avoid ambiguity with JSON quirks.
        plan = {"entities": {"Widget": {"needs_payment_methods": "yes"}}}
        r = detect_payment_intent(plan)
        assert r["needs_payment_methods"] is False
        assert r["reason"] == "no signal"

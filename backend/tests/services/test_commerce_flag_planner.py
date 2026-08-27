"""Tests for Spec D Wave 2 — planner-authored `plan.commerce_intent`
precedence on commerce_flag.detect_commerce_intent. Additive: the
`_has_commerce_vocab` sweep stays intact as the fallback. (The
per-entity ``entity.commerce=True`` respect in `flag_commerce_entity`
is unchanged and covered by test_commerce_flag.py.)
"""
from __future__ import annotations

from services.commerce_flag import detect_commerce_intent, flag_commerce_entity


class TestPlannerIntentWins:
    def test_true_flag_forces_intent(self):
        # No commerce vocab in the brief at all; planner says True.
        plan = {"brief": "A quiet reading log."}
        assert detect_commerce_intent(plan) is False  # sanity
        plan["commerce_intent"] = True
        assert detect_commerce_intent(plan) is True


class TestPlannerOptOut:
    def test_false_flag_silences_vocab_sweep(self):
        # Brief has 'sell' / 'cart' → legacy would fire; planner says No.
        plan = {
            "brief": "We sell handmade goods with a cart and checkout.",
            "commerce_intent": False,
        }
        assert detect_commerce_intent(plan) is False

    def test_false_flag_prevents_flag_commerce_entity(self):
        # Downstream integration: `flag_commerce_entity` calls
        # `detect_commerce_intent` — an opt-out at the plan level should
        # therefore also prevent auto-flagging a product entity.
        plan = {
            "brief": "sell items in a shop with checkout",
            "commerce_intent": False,
            "entities": {"Product": {"fields": [{"name": "price"}]}},
        }
        out = flag_commerce_entity(plan)
        assert out["entities"]["Product"].get("commerce") is not True


class TestLegacyPathPreserved:
    def test_no_flag_still_uses_vocab(self):
        plan = {"brief": "We sell items and take orders."}
        assert detect_commerce_intent(plan) is True

    def test_no_flag_no_vocab_stays_false(self):
        plan = {"brief": "A quiet reading log."}
        assert detect_commerce_intent(plan) is False


class TestFlagShapeTolerance:
    def test_none_flag_falls_through(self):
        # None is neither True nor False by our contract — legacy path runs.
        plan = {"brief": "We sell items.", "commerce_intent": None}
        assert detect_commerce_intent(plan) is True

    def test_string_truthy_falls_through(self):
        # 'yes' isn't literal True — fall through to vocab sweep.
        plan = {"brief": "A quiet reading log.", "commerce_intent": "yes"}
        assert detect_commerce_intent(plan) is False

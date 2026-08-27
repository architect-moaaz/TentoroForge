# backend/tests/services/test_cost_tracker.py
import pytest
from services.cost_tracker import CostTracker, BudgetExhausted


def test_starts_at_zero():
    t = CostTracker(cap_usd=5.0)
    assert t.total == 0.0


def test_add_increments_total():
    t = CostTracker(cap_usd=5.0)
    t.add("vision", tokens_in=4000, tokens_out=400)
    assert t.total > 0
    assert t.total < 1.0  # one vision call should be well under $1


def test_raises_when_cap_exceeded():
    t = CostTracker(cap_usd=0.05)  # tiny cap
    # First call may or may not exceed; keep adding until it does
    with pytest.raises(BudgetExhausted):
        for _ in range(20):
            t.add("vision", tokens_in=4000, tokens_out=400)


def test_raise_includes_cap_in_message():
    t = CostTracker(cap_usd=0.001)
    with pytest.raises(BudgetExhausted, match=r"\$0\.001"):
        t.add("vision", tokens_in=10_000, tokens_out=1000)


def test_unknown_kind_is_estimated_conservatively():
    t = CostTracker(cap_usd=100.0)
    # Unknown kinds shouldn't crash — they should fall back to a default rate
    t.add("schema_reprompt", tokens_in=1000, tokens_out=500)
    assert t.total > 0

"""A retry earns its cost by telling the author something it did not know.

A single-page calculator was declined three times for having no KPI tiles — a
demand it could never meet — at roughly 135 seconds a composition. The second
refusal was word for word the first.
"""

from __future__ import annotations

from services.blueprint.orchestrator import _same_refusal, accumulate_refusals

FLOOR = "composed page failed the dashboard floor: dashboard_no_kpis, dashboard_no_chart"


def test_the_same_words_twice_are_recognised():
    after_one = accumulate_refusals("", 1, FLOOR)
    assert _same_refusal(after_one, FLOOR) is True
    # Spacing is not a difference: it is the same thing to read.
    assert _same_refusal(after_one, "composed page failed the dashboard floor:   "
                                    "dashboard_no_kpis, dashboard_no_chart") is True


def test_a_different_refusal_still_earns_another_attempt():
    after_one = accumulate_refusals("", 1, FLOOR)
    assert _same_refusal(after_one, "binding 'item' has no declared data source") is False
    # Only the LAST refusal counts: a fault that came back after being fixed
    # is news again.
    after_two = accumulate_refusals(after_one, 2, "binding 'item' has no declared data source")
    assert _same_refusal(after_two, FLOOR) is False


def test_the_first_refusal_is_never_a_repeat():
    assert _same_refusal("", FLOOR) is False
    assert _same_refusal(accumulate_refusals("", 1, FLOOR), "") is False


def test_every_refusal_is_still_carried_into_the_feedback():
    """Stopping early must not lose what the author was told — the fallback
    reads the same accumulated text."""
    said = accumulate_refusals(accumulate_refusals("", 1, FLOOR), 2, "and another thing")
    assert "attempt 1" in said and "attempt 2" in said
    assert FLOOR in said and "and another thing" in said


def test_a_crash_still_gets_every_attempt_it_is_allowed():
    """A validator is a function of what was proposed; a crash is not. A
    provider timeout is the same message twice and a third call may well
    succeed, so only a deterministic refusal is curtailed — which is why
    `_rejected` takes `deterministic` rather than deciding from the text."""
    import inspect

    from services.blueprint import orchestrator

    src = inspect.getsource(orchestrator._apply_subject)
    assert "deterministic=True" in src          # the validator path
    assert "_rejected(_reason(outcome))" in src  # the exception path, unchanged

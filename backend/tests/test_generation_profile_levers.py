"""Fast vs Complete profile now controls the REAL speed levers (Task 3).

Previously the profiles differed only in `narrative_expansion` (a 30-180s call)
while the 10-20 min variance (planner revise/V2 retries, the build-review loop)
was profile-blind — which is why Fast could take LONGER than Complete. These
lock in that the profile gates the levers, and that Fast is strictly lighter.
"""
from services.generation_profile import get_profile


def test_fast_profile_is_the_light_one():
    fast = get_profile("fast")
    assert fast.review_cycles == 2
    assert fast.planner_revise is False
    assert fast.planner_v2_retry is False
    assert fast.planner_critic is False
    assert fast.narrative_expansion is False
    # Fast uses the quick one-shot planner, NOT the slow per-unit decomposition.
    assert fast.decomposition is False
    assert fast.eta_minutes == 12


def test_complete_profile_is_the_thorough_one():
    comp = get_profile("complete")
    assert comp.review_cycles == 5
    assert comp.planner_revise is True
    assert comp.planner_v2_retry is True
    assert comp.narrative_expansion is True
    assert comp.eta_minutes == 30


def test_fast_is_strictly_lighter_than_complete():
    fast, comp = get_profile("fast"), get_profile("complete")
    # Fewer build cycles AND fewer planner re-streams AND lower advertised ETA.
    assert fast.review_cycles < comp.review_cycles
    assert fast.eta_minutes < comp.eta_minutes
    fast_retries = sum([fast.planner_revise, fast.planner_v2_retry, fast.planner_critic])
    comp_retries = sum([comp.planner_revise, comp.planner_v2_retry, comp.planner_critic])
    assert fast_retries < comp_retries

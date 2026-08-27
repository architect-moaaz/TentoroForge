"""Fix-Assistant: consent-to-apply detection.

When the user has a pending fix proposal from a prior turn and their next
message reads as consent ("yes / fix it / apply / go ahead"), the FIX handler
must route to APPLY instead of re-diagnosing — otherwise the vague follow-up
message clobbers a perfectly good proposal with a "couldn't pin that down"
clarifying question, which is what happened in the live bug report.
"""
from __future__ import annotations

from routers.generate import _looks_like_apply_intent


AFFIRMATIVE_APPLY = [
    # bare consent
    "yes", "Yes.", "YES!", "yep", "yeah", "sure", "ok", "okay",
    # short apply openers
    "apply", "go ahead", "do it", "proceed",
    # the exact live case + variants
    "Can you fix it?", "Can you please fix it?", "please fix it", "fix it",
    "please apply", "please",
    # with fillers
    "yes please", "please do", "do it please",
]

MUST_NOT_MATCH = [
    "",
    # real symptom sentences (some contain "fix" and shouldn't match)
    "the fix doesn't work",
    "applying the fix broke another thing",
    "Page is Assessment Scheduling",
    "the Schedule button is broken",
    "scheduling fails to save",
    "In Assessment Scheduling, Schedule button is not working",
    "fix the broken button",
    "the pipeline page is empty",
    # feature-add language
    "add a filter to the candidate list",
    "make it dark mode",
]


def test_affirmative_apply_phrases_are_detected():
    misses = [s for s in AFFIRMATIVE_APPLY if not _looks_like_apply_intent(s)]
    assert not misses, f"apply-intent detector missed: {misses}"


def test_symptom_sentences_are_not_confused_with_apply():
    false_positives = [s for s in MUST_NOT_MATCH if _looks_like_apply_intent(s)]
    assert not false_positives, f"apply-intent detector false-positive on: {false_positives}"

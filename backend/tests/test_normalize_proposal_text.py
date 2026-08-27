"""The bot's proposal explanation must read as a PROPOSAL, not as an already-
applied change. A user in the wild read "Both are fixed in the patch above"
as done and never clicked Apply — the bug persisted. Normalize the text so
past-tense fix claims become conditional and every proposal ends with an
explicit Apply hint."""
from __future__ import annotations

from routers.generate import _normalize_proposal_text


def _has_cta(text: str) -> bool:
    lo = text.lower()
    return "apply fix" in lo or "click apply" in lo


def test_past_tense_fix_claims_become_conditional():
    inp = ("Two values in the 'Create Assessment Record' node were wrong:\n"
           "1. candidateId is fixed. 2. status is corrected.\n"
           "Both are fixed in the patch above.")
    out = _normalize_proposal_text(inp)
    # No more misleading past-tense.
    lo = out.lower()
    assert " is fixed" not in lo and " are fixed" not in lo
    assert "is corrected" not in lo
    # Reads as a proposal instead.
    assert "will be fixed" in lo
    # Ends with the CTA.
    assert _has_cta(out)


def test_applied_assertions_become_conditional():
    inp = "The change has been applied — Schedule now works. All done."
    out = _normalize_proposal_text(inp)
    lo = out.lower()
    assert "has been applied" not in lo
    assert "now works" not in lo
    assert "all done" not in lo
    assert "will apply" in lo
    assert _has_cta(out)


def test_neutral_proposal_still_gets_apply_hint():
    inp = "The Schedule button crashes because candidateId is a timestamp; I'll rebind it."
    out = _normalize_proposal_text(inp)
    # Preserved verbatim except for the appended hint.
    assert inp in out
    assert _has_cta(out)


def test_explanation_that_already_mentions_apply_is_not_double_hinted():
    inp = "Ready to fix — click **Apply fix** above."
    out = _normalize_proposal_text(inp)
    # Hint appears exactly once.
    assert out.lower().count("apply fix") == 1


def test_empty_explanation_returns_a_default_proposal_message():
    out = _normalize_proposal_text("")
    assert _has_cta(out) and "Apply" in out

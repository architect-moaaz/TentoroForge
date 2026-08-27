"""Guards the refiner verify-before-claim contract.

Symptom that motivated this: user asked Smith "generate the AI agent",
Smith punted to the code refiner, chat showed "Changes applied
successfully" — but the Agent tab was empty. Root cause was that
``_response_text_for_intent`` emitted the success text based ONLY on
the intent classification, never checking that the refiner actually
produced a diff.

``git_commit`` already returns ``None`` when there's nothing to commit
— that's the truth signal. This test locks the reply text to that
signal for every code-changing intent so a future refactor can't drift
back into unverified success messaging.
"""
from __future__ import annotations

import pytest

from routers.generate import _CODE_CHANGING_INTENTS, _response_text_for_intent


class TestVerifyBeforeClaim:
    """No commit → no 'successfully' wording for code-changing intents."""

    @pytest.mark.parametrize("intent", sorted(_CODE_CHANGING_INTENTS))
    def test_code_intent_without_commit_returns_honest_message(self, intent):
        msg = _response_text_for_intent(intent, commit_hash=None)
        low = msg.lower()
        # Absolutely no success wording.
        assert "successfully" not in low
        assert "applied." not in low
        assert "scaffolded." not in low
        # Must acknowledge the failure so the user knows nothing landed.
        assert "couldn't" in low or "nothing landed" in low
        # Must offer a next step (breaking the ask down) — otherwise the
        # user is stuck at a dead-end honesty message.
        assert (
            "smaller" in low
            or "step" in low
            or "add a page" in low
            or "break" in low
        )

    @pytest.mark.parametrize("intent", sorted(_CODE_CHANGING_INTENTS))
    def test_code_intent_with_commit_returns_success(self, intent):
        msg = _response_text_for_intent(intent, commit_hash="abcdef1234567890")
        low = msg.lower()
        assert "couldn't" not in low
        assert "nothing landed" not in low

    def test_files_count_appears_in_refine_success(self):
        msg = _response_text_for_intent(
            "REFINE", commit_hash="abc123", files_changed=3,
        )
        assert "3 file" in msg

    def test_refine_success_without_count_stays_terse(self):
        msg = _response_text_for_intent("REFINE", commit_hash="abc123")
        # No hallucinated count — just the general "applied" wording.
        assert "0" not in msg
        assert "file" not in msg.lower() or "files" not in msg.lower()


class TestNonCodeIntentsUnchanged:
    """PLAN / EXPLAIN don't produce commits and shouldn't be gated."""

    def test_plan_intent_returns_plan_text(self):
        msg = _response_text_for_intent("PLAN")  # commit_hash defaults to None
        assert "plan" in msg.lower()
        assert "couldn't" not in msg.lower()

    def test_explain_intent_returns_explain_text(self):
        msg = _response_text_for_intent("EXPLAIN")
        assert "explanation" in msg.lower()

    def test_unknown_intent_falls_back_to_done(self):
        msg = _response_text_for_intent("MYSTERY_INTENT")
        assert msg == "Done."


class TestBackwardCompatibleSignature:
    """Callers that don't pass commit_hash still work — used by tests
    and any legacy call site that isn't in a code-changing path."""

    def test_positional_only_intent(self):
        # No kwargs — should not raise, and PLAN should return normally.
        msg = _response_text_for_intent("PLAN")
        assert msg

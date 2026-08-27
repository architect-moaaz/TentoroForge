"""Tests for capability_gate — the entrance-check that stops the
pipeline building a CRUD-shell around an interactive-app prompt."""

from __future__ import annotations

import os

import pytest

from services.capability_gate import (
    InteractiveAppRefused,
    classify_capability,
    enforce_capability_gate,
    is_gate_enabled,
    refusal_message,
)


class TestClassifier:
    def test_empty_prompt_is_unclear(self):
        assert classify_capability("")["shape"] == "unclear"
        assert classify_capability("   ")["shape"] == "unclear"
        assert classify_capability(None)["shape"] == "unclear"  # type: ignore[arg-type]

    def test_pure_crud_asks_pass_through(self):
        r = classify_capability("Build an app for managing customer orders and invoices")
        assert r["shape"] == "crud", r
        assert r["matched"] == []

    def test_calculator_routes_to_computational(self):
        # calculator/converter/quiz are now first-class via the
        # `computational` archetype — gate routes, doesn't refuse.
        r = classify_capability("Build a simple calculator")
        assert r["shape"] == "computational"
        assert r.get("archetype") == "computational"
        assert "calculator" in r["matched"]

    def test_timer_flags_interactive(self):
        r = classify_capability("I need a pomodoro timer app")
        assert r["shape"] == "interactive"
        assert "pomodoro" in r["matched"] or "timer" in r["matched"]

    def test_game_flags_interactive(self):
        assert classify_capability("build me a chess game")["shape"] == "interactive"
        assert classify_capability("sudoku app")["shape"] == "interactive"
        assert classify_capability("wordle clone")["shape"] == "interactive"

    def test_multiword_tokens_match(self):
        r = classify_capability("I want a currency converter")
        assert r["shape"] == "computational"
        assert "currency converter" in r["matched"]

    def test_mixed_ask_with_crud_content_stays_crud(self):
        """Even though 'calculator' appears, presence of user/order/manage
        means the user wants a database app that mentions calculator."""
        r = classify_capability(
            "Log calculator usage per user with per-team stats and manage roles"
        )
        assert r["shape"] == "crud", r
        # But we should have SEEN the interactive keyword — that's the audit trail
        assert "calculator" in r["matched"]

    def test_calculate_verb_does_not_trigger(self):
        """'calculate' as a normal verb inside a CRUD ask must not trip
        the classifier. Whole-word matching guards against this."""
        r = classify_capability(
            "Invoice management app that can calculate totals for each customer"
        )
        assert r["shape"] == "crud", r

    def test_case_insensitive(self):
        # Calculator routes to computational (supported); piano stays
        # in the still-unsupported interactive bucket.
        assert classify_capability("CALCULATOR APP")["shape"] == "computational"
        assert classify_capability("Piano App")["shape"] == "interactive"

    def test_matched_is_sorted_deduped(self):
        r = classify_capability("Calculator calculator CALCULATOR piano")
        assert r["matched"] == sorted(r["matched"])
        assert len(r["matched"]) == len(set(r["matched"]))


class TestGateEnvFlag:
    def test_gate_off_by_default(self, monkeypatch):
        monkeypatch.delenv("FORGE_CAPABILITY_GATE", raising=False)
        assert is_gate_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "strict", "enforce"])
    def test_gate_on_values(self, monkeypatch, value):
        monkeypatch.setenv("FORGE_CAPABILITY_GATE", value)
        assert is_gate_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
    def test_gate_off_values(self, monkeypatch, value):
        monkeypatch.setenv("FORGE_CAPABILITY_GATE", value)
        assert is_gate_enabled() is False


class TestEnforce:
    def test_enforce_never_raises_when_gate_off(self, monkeypatch):
        monkeypatch.delenv("FORGE_CAPABILITY_GATE", raising=False)
        # calculator is now computational (supported), so it wouldn't raise
        # regardless of gate state — use a genuine-interactive prompt.
        r = enforce_capability_gate("build me a piano")
        assert r["shape"] == "interactive"  # classified…
        # …but no exception because gate is off (observe-mode)

    def test_enforce_does_not_raise_for_computational_even_when_gate_on(self, monkeypatch):
        # New shape: computational is a supported archetype, never blocks.
        monkeypatch.setenv("FORGE_CAPABILITY_GATE", "strict")
        r = enforce_capability_gate("build me a calculator")
        assert r["shape"] == "computational"
        assert r.get("archetype") == "computational"


class TestWorkflowIntent:
    """Computational tools that also need a side-effect (email/notify/save)
    are still shape=computational, but classification flips a
    `needs_workflow` hint the router reads to bypass the deterministic
    short-circuit (which can't author the workflow) and route through the
    LLM planner instead."""

    def test_bmi_with_email_flips_needs_workflow(self):
        r = classify_capability("BMI calculator that emails me the result")
        assert r["shape"] == "computational"
        assert r.get("needs_workflow") is True
        # "emails" (plural, 3rd person) is the surface form matched
        assert any(w in r.get("workflow_intent_matched", []) for w in ["email", "emails"])

    def test_plain_calculator_does_not_flip_needs_workflow(self):
        r = classify_capability("build me a simple calculator")
        assert r["shape"] == "computational"
        assert r.get("needs_workflow") is not True

    def test_notify_webhook_variants(self):
        for prompt in [
            "loan calculator that notifies my webhook when the value is above 10 lakh",
            "tip calculator that sends the tip to Slack",
            "unit converter that saves to my Notion page",
            "quiz scorer that alerts me when the score is below 50",
        ]:
            r = classify_capability(prompt)
            assert r["shape"] == "computational", prompt
            assert r.get("needs_workflow") is True, prompt

    def test_workflow_intent_reason_string(self):
        r = classify_capability("BMI calculator that emails the result")
        assert "workflow intent" in r["reason"]

    def test_workflow_intent_alone_without_computational_is_not_workflow_computational(self):
        # "email my customers" is CRUD (customers is a CRUD token) — not
        # a computational-with-workflow ask
        r = classify_capability("app to email my customers")
        assert r["shape"] == "crud"
        assert r.get("needs_workflow") is not True

    def test_enforce_raises_when_gate_on_and_interactive(self, monkeypatch):
        monkeypatch.setenv("FORGE_CAPABILITY_GATE", "on")
        with pytest.raises(InteractiveAppRefused) as ei:
            enforce_capability_gate("build a chess game")
        assert "chess" in str(ei.value)
        assert ei.value.classification["shape"] == "interactive"
        assert "chess" in ei.value.classification["matched"]

    def test_enforce_does_not_raise_for_crud_even_when_gate_on(self, monkeypatch):
        monkeypatch.setenv("FORGE_CAPABILITY_GATE", "on")
        r = enforce_capability_gate("manage customer orders and invoices")
        assert r["shape"] == "crud"

    def test_enforce_does_not_raise_for_mixed_even_when_gate_on(self, monkeypatch):
        monkeypatch.setenv("FORGE_CAPABILITY_GATE", "on")
        # Mixed: calculator + crud content → shape stays crud → no raise
        r = enforce_capability_gate("log calculator usage per user with team stats")
        assert r["shape"] == "crud"


class TestRefusalMessage:
    def test_names_the_concept(self):
        c = classify_capability("build a piano app")
        m = refusal_message("build a piano app", c)
        assert "piano" in m.lower()

    def test_mentions_ways_forward(self):
        c = classify_capability("build a stopwatch")
        m = refusal_message("build a stopwatch", c)
        # The refusal should offer alternatives (reshape/wrap/refuse/proceed)
        assert "reshape" in m.lower() or "wrap" in m.lower()
        assert "proceed" in m.lower()

    def test_handles_empty_matched(self):
        # Belt-and-suspenders — refusal_message is only called on
        # interactive classifications, but if matched somehow arrives
        # empty it should still produce a coherent message.
        m = refusal_message("weird prompt", {"shape": "interactive", "matched": []})
        assert isinstance(m, str) and len(m) > 100

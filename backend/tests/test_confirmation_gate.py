"""Tests for the destructive-action confirmation gate (Phase 1a)."""

from __future__ import annotations

import pytest

from services.confirmation_gate import (
    build_impact_summary,
    needs_confirmation_result,
    parse_confirmation_reply,
)


# --------------------------------------------------------------------------- #
# parse_confirmation_reply                                                    #
# --------------------------------------------------------------------------- #

class TestParseConfirmation:
    @pytest.mark.parametrize("msg", [
        "yes",
        "yes please",
        "Yes",
        "yep",
        "yeah go ahead",
        "confirm",
        "go ahead",
        "proceed",
        "do it",
        "remove it",
        "okay",
        "ok",
        "sure",
    ])
    def test_yes_variants(self, msg):
        assert parse_confirmation_reply(msg) == "yes"

    @pytest.mark.parametrize("msg", [
        "no",
        "nope",
        "nah",
        "cancel",
        "abort",
        "actually no",
        "don't remove that",
        "dont delete",
        "never mind",
        "forget it",
        "keep it",
    ])
    def test_no_variants(self, msg):
        assert parse_confirmation_reply(msg) == "no"

    def test_no_wins_over_yes_when_both_present(self):
        # "yes but no thanks" is ambiguous — NO wins for safety.
        assert parse_confirmation_reply("yes but actually no thanks") == "no"

    def test_unclear_prose(self):
        assert parse_confirmation_reply("hmm let me think") == "unclear"
        assert parse_confirmation_reply("what does that even mean") == "unclear"

    def test_empty_and_whitespace(self):
        assert parse_confirmation_reply("") == "unclear"
        assert parse_confirmation_reply("   ") == "unclear"

    def test_non_string_safe(self):
        assert parse_confirmation_reply(None) == "unclear"  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# build_impact_summary + needs_confirmation_result                            #
# --------------------------------------------------------------------------- #

class TestImpactSummary:
    def test_bare_target_no_dependents(self):
        s = build_impact_summary("page", "Pricing")
        assert "Pricing" in s
        assert "yes" in s.lower() and "no" in s.lower()

    def test_lists_dependents(self):
        s = build_impact_summary(
            "page", "Home",
            dependents=["nav edge Home→About", "form contact.submit"],
        )
        assert "2 thing" in s or "2 things" in s
        assert "nav edge Home→About" in s
        assert "form contact.submit" in s

    def test_truncates_long_dependent_list(self):
        deps = [f"dep-{i}" for i in range(25)]
        s = build_impact_summary("entity", "User", dependents=deps)
        assert "25 thing" in s
        assert "…and 15 more" in s


class TestNeedsConfirmationResult:
    def test_shape(self):
        r = needs_confirmation_result("page", "Pricing", dependents=["nav"])
        assert r["status"] == "needs_confirmation"
        assert r["kind"] == "page"
        assert r["target"] == "Pricing"
        assert r["dependents"] == ["nav"]
        assert "Pricing" in r["summary"]

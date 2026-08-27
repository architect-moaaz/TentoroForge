"""Tests for services/auto_generate_gate.py (Phase 2).

Covers UAT rows 70-77: auto-trigger the generative pipeline on
milestone / idle / farewell; block during rapid iteration, plan
in-flight, validation errors, or pending confirmation.
"""

from __future__ import annotations

import pytest

from services.auto_generate_gate import (
    IDLE_MIN_TIME_SINCE_EDIT_SEC,
    IDLE_STABLE_THRESHOLD_SEC,
    RAPID_ITERATION_LIMIT,
    Signals,
    decide,
)


# --------------------------------------------------------------------------- #
# BLOCKERS — must always win, even over explicit "build now"                  #
# --------------------------------------------------------------------------- #

class TestBlockers:
    def test_validation_errors_block_explicit_build(self):
        d = decide(Signals(user_intent="explicit_build", validation_errors=1))
        assert d["trigger"] is False
        assert d["reason"] == "blocked_validation"
        assert "validation" in d["message"].lower()

    def test_plan_in_flight_blocks_explicit_build(self):
        d = decide(Signals(user_intent="explicit_build", plan_in_flight=True))
        assert d["trigger"] is False
        assert d["reason"] == "blocked_plan"

    def test_pending_confirmation_blocks_farewell(self):
        d = decide(Signals(
            user_intent="farewell",
            pending_confirmation=True,
        ))
        assert d["trigger"] is False
        assert d["reason"] == "blocked_pending_confirm"

    def test_rapid_iteration_blocks_idle_trigger(self):
        d = decide(Signals(
            user_intent="edit",
            seconds_since_edit=IDLE_STABLE_THRESHOLD_SEC + 10,
            recent_edits_to_same_target=RAPID_ITERATION_LIMIT,
        ))
        assert d["trigger"] is False
        assert d["reason"] == "blocked_rapid_iter"


# --------------------------------------------------------------------------- #
# TRIGGERS                                                                     #
# --------------------------------------------------------------------------- #

class TestExplicitBuild:
    def test_explicit_build_triggers_when_clean(self):
        d = decide(Signals(user_intent="explicit_build"))
        assert d["trigger"] is True
        assert d["reason"] == "explicit"


class TestFarewell:
    def test_farewell_triggers_when_clean(self):
        d = decide(Signals(user_intent="farewell"))
        assert d["trigger"] is True
        assert d["reason"] == "farewell"


class TestIdleStable:
    def test_triggers_after_threshold(self):
        d = decide(Signals(
            user_intent="edit",
            seconds_since_edit=IDLE_STABLE_THRESHOLD_SEC + 10,
        ))
        assert d["trigger"] is True
        assert d["reason"] == "idle_stable"

    def test_does_not_trigger_before_threshold(self):
        d = decide(Signals(
            user_intent="edit",
            seconds_since_edit=IDLE_STABLE_THRESHOLD_SEC - 60,
        ))
        assert d["trigger"] is False
        # milestone_complete is intentionally NOT fired here since a
        # never-built app would trigger. We differentiate them below.

    def test_skips_when_no_change_since_last_build(self):
        # Idle 6 minutes ago the last edit; last build was 3 minutes ago.
        # Nothing changed since — no need to rebuild.
        d = decide(Signals(
            user_intent="edit",
            seconds_since_edit=360,
            seconds_since_last_build=180,
        ))
        assert d["trigger"] is False
        assert d["reason"] == "no_change_since_last_build"


class TestMilestoneComplete:
    def test_explicit_milestone_signal_triggers(self):
        d = decide(Signals(
            user_intent="edit",
            milestone_just_reached=True,
            seconds_since_edit=IDLE_MIN_TIME_SINCE_EDIT_SEC + 5,
        ))
        assert d["trigger"] is True
        assert d["reason"] == "milestone_complete"

    def test_milestone_signal_ignored_when_edit_too_fresh(self):
        # Milestone signaled but the last patch is still settling.
        d = decide(Signals(
            user_intent="edit",
            milestone_just_reached=True,
            seconds_since_edit=IDLE_MIN_TIME_SINCE_EDIT_SEC - 5,
        ))
        assert d["trigger"] is False

    def test_no_milestone_signal_no_trigger(self):
        # Even a stable-looking state without the explicit signal
        # doesn't fire milestone_complete.
        d = decide(Signals(
            user_intent="edit",
            milestone_just_reached=False,
            seconds_since_edit=IDLE_MIN_TIME_SINCE_EDIT_SEC + 5,
        ))
        assert d["trigger"] is False


class TestPriority:
    def test_validation_blocker_beats_explicit(self):
        d = decide(Signals(
            user_intent="explicit_build",
            validation_errors=3,
        ))
        assert d["reason"] == "blocked_validation"

    def test_explicit_beats_farewell(self):
        # If the LLM classifier tagged intent as explicit_build,
        # farewell doesn't preempt.
        d = decide(Signals(user_intent="explicit_build"))
        assert d["reason"] == "explicit"

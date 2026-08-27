"""Auto-trigger heuristics for the generative pipeline (Phase 2).

Purpose
-------
Today the generative pipeline runs only on explicit user request. The
UAT spec (rows 70-77) wants Smith to proactively trigger a build when
the app is in a stable milestone state — and refuse when it isn't.

Design
------
Pure decision function. Callers hand in the current signals and get
back a decision + reason string Smith can relay. No IO, no side
effects — makes it trivial to unit test and reason about.

Signals in::

    {
      "user_intent":          "chat" | "farewell" | "explicit_build" | "edit",
      "seconds_since_edit":   float,   # last patch → now
      "plan_in_flight":       bool,    # a plan_and_apply sequence not yet done
      "validation_errors":    int,     # unresolved errors on the app
      "pending_confirmation": bool,    # remove_page etc. awaiting yes/no
      "recent_edits_to_same_target": int,  # rapid-iteration signal
      "seconds_since_last_build": Optional[float],  # None if never built
    }

Decision out::

    {
      "trigger":  True | False,
      "reason":   "milestone_complete" | "idle_stable" | "farewell" |
                  "explicit" | "blocked_validation" | "blocked_plan" |
                  "blocked_rapid_iter" | "blocked_pending_confirm" |
                  "no_change_since_last_build",
      "message":  "one-line explanation Smith can relay",
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

IDLE_STABLE_THRESHOLD_SEC = 300           # 5 minutes
IDLE_MIN_TIME_SINCE_EDIT_SEC = 30         # last patch settled
RAPID_ITERATION_LIMIT = 3                 # patches to same target within 60s
REBUILD_AFTER_EDIT_THRESHOLD_SEC = 30     # skip if last build was < 30s ago


@dataclass
class Signals:
    user_intent: str = "edit"
    seconds_since_edit: float = 0.0
    plan_in_flight: bool = False
    validation_errors: int = 0
    pending_confirmation: bool = False
    recent_edits_to_same_target: int = 0
    seconds_since_last_build: Optional[float] = None
    # Set to True by the caller ONLY when a composite (plan_and_apply,
    # a fix cycle, an add_page macro) has JUST completed cleanly. It's
    # the explicit "we hit a milestone" signal — never inferred from
    # elapsed time alone, since a plain long-idle-then-mid-edit
    # shouldn't count as a milestone.
    milestone_just_reached: bool = False


def decide(signals: Signals) -> dict:
    """Return the auto-generate decision.

    Blocker checks come first — they always win, even for explicit
    "build the app now" (test 75/76: "build (while validation error
    open)" → refused). The user can override manually via the toolbar
    Publish button; ``publish`` (deploy) is a distinct flow.
    """
    # ---- BLOCKERS (win over everything) --------------------------------- #
    if signals.validation_errors > 0:
        return {
            "trigger": False,
            "reason":  "blocked_validation",
            "message": (
                f"There are {signals.validation_errors} outstanding "
                "validation error(s). Fix them first — running the "
                "build now would only surface the same errors."
            ),
        }

    if signals.plan_in_flight:
        return {
            "trigger": False,
            "reason":  "blocked_plan",
            "message": (
                "A multi-step plan is still in flight. I'll trigger "
                "the build automatically once the remaining steps land."
            ),
        }

    if signals.pending_confirmation:
        return {
            "trigger": False,
            "reason":  "blocked_pending_confirm",
            "message": (
                "There's a pending confirmation ('yes'/'no') from an "
                "earlier destructive action. Resolve it before building."
            ),
        }

    if signals.recent_edits_to_same_target >= RAPID_ITERATION_LIMIT:
        return {
            "trigger": False,
            "reason":  "blocked_rapid_iter",
            "message": (
                "You've been iterating rapidly on the same target — "
                "I won't auto-build during active iteration. Ask "
                "explicitly when you're ready."
            ),
        }

    # ---- TRIGGERS (in priority order) ----------------------------------- #
    # Explicit user ask — always run (past all blockers above).
    if signals.user_intent == "explicit_build":
        return {
            "trigger": True,
            "reason":  "explicit",
            "message": "Building the app now — you asked for it.",
        }

    # Farewell — user is closing the session.
    if signals.user_intent == "farewell":
        return {
            "trigger": True,
            "reason":  "farewell",
            "message": "Running the build before we wrap up.",
        }

    # Idle + stable state — user has stopped editing and the last
    # patch has had a chance to settle.
    if (
        signals.seconds_since_edit >= IDLE_STABLE_THRESHOLD_SEC
        and signals.seconds_since_edit >= IDLE_MIN_TIME_SINCE_EDIT_SEC
    ):
        # But skip if nothing has changed since the last build.
        if (
            signals.seconds_since_last_build is not None
            and signals.seconds_since_last_build < signals.seconds_since_edit
        ):
            return {
                "trigger": False,
                "reason":  "no_change_since_last_build",
                "message": (
                    "The app is already up to date with your latest "
                    "edits — no need to rebuild."
                ),
            }
        return {
            "trigger": True,
            "reason":  "idle_stable",
            "message": (
                "You've been idle for a while and the app is in a "
                "stable state — running the build."
            ),
        }

    # Milestone complete: EXPLICITLY signaled by the caller when a
    # composite (plan_and_apply / fix cycle / add_page macro) finished
    # cleanly. Never inferred from elapsed time alone — a mid-session
    # user who paused isn't a milestone.
    if (
        signals.milestone_just_reached
        and signals.seconds_since_edit >= IDLE_MIN_TIME_SINCE_EDIT_SEC
    ):
        return {
            "trigger": True,
            "reason":  "milestone_complete",
            "message": (
                "Composite step landed cleanly — running the build so "
                "the deployed app catches up."
            ),
        }

    return {
        "trigger": False,
        "reason":  "no_trigger_condition",
        "message": "",
    }

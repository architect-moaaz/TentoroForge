"""The two result shapes the platform still shares: `TurnResult`, which the chat
surfaces read, and `IterationMove`, which a tree edit returns. Everything else
that was here — the session, its bootstrap and its iteration — is Smith v4
(`services.smith4`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional



logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Result shapes
# --------------------------------------------------------------------------- #

@dataclass
class IterationMove:
    """What the iteration move function returns to the session.

    Not a self-report of what changed — a *label* naming the move
    Smith intended. The actual "what changed" comes from git."""
    move_name: str
    touched_paths: list[str] = field(default_factory=list)


@dataclass
class TurnResult:
    """Everything a chat turn produces for the caller.

    ``status`` in {"resolved", "asked", "needs_user", "no_op"}:
      * ``resolved``   — move landed, verified, blueprint updated.
      * ``asked``      — Smith emitted a clarifying question.
      * ``needs_user`` — a hard failure that the user must resolve
                         (choose from ``options``). No silent
                         rollback.
      * ``no_op``      — Smith read but didn't need to change
                         anything.

    ``finding`` separates the two things ``needs_user`` had come to mean. A
    FINDING is something the platform PROVED about the work it just did — git
    says the diff did not touch the file that was named, the composer laid the
    page out without what it was told to put on it, a guard that passed now
    fails. A question for the person is not a finding: "I do not recognise
    that", "building runs from the card", "are you sure — this deletes a
    column" are asks, and no amount of thinking makes them answerable without
    them.

    The distinction is the whole of `2026-09-24-smith-as-a-loop` §4.4. A
    finding is evidence, and evidence is exactly what a second step can act on:
    "I edited X but you asked about Y" is the sentence that makes a model try
    the other reading. Handed to the person instead, with three chips, it is a
    dead end at the end of four minutes' work. The text is written for the
    thing that reads it next, not for the chat bubble — ``answer`` is still
    what the person sees.
    """
    status: str
    answer: str
    options: list[str] = field(default_factory=list)
    diff_summary: str = ""
    touched_paths: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    #: What an oracle proved about this step, in its own words. "" when the
    #: outcome is a question rather than a proof.
    finding: str = ""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

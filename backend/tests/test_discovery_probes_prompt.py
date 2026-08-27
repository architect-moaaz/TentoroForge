"""JT-T8 — pin the actors + journeys probe pattern into the discovery prompt.

Same guard style as the planner-prompt test: assert every rule keyword
is present, so a future edit that drops one fails loudly.
"""
from __future__ import annotations

import re

from agents.discovery import DISCOVERY_SYSTEM_PROMPT


def _prompt() -> str:
    return re.sub(r"\s+", " ", DISCOVERY_SYSTEM_PROMPT)


def test_actors_probe_section_present():
    p = _prompt()
    assert "Actors + Journeys" in p
    assert "who uses the app and how each gets in" in p


def test_actor_vocabulary_mirror_instruction():
    """The whole point of moving actor elicitation into discovery is
    to capture the USER'S vocabulary, not the LLM's default."""
    p = _prompt()
    assert "Mirror the user's vocabulary" in p or "mirror the user's vocabulary" in p.lower()


def test_industry_specific_examples_mentioned():
    """The prompt names real domain actors so the LLM knows not to
    default to 'User/Admin'."""
    p = _prompt()
    assert "Candidate" in p and "Recruiter" in p and "Interviewer" in p


def test_onboarding_source_probe_present():
    p = _prompt()
    assert "sign themselves up" in p
    assert "someone add them" in p


def test_journey_walkthrough_probe_present():
    p = _prompt()
    assert "Walk me through" in p
    assert "step by step" in p


def test_termination_marker_defined():
    """The `[READY_FOR_STRUCTURE]` marker is the transformer's cue to
    run — must appear verbatim in the prompt."""
    p = _prompt()
    assert "[READY_FOR_STRUCTURE]" in p


def test_termination_criteria_named():
    """The prompt spells out what "ready" means so the LLM doesn't
    emit the marker prematurely."""
    p = _prompt()
    assert "at least 2 actors" in p
    assert "at least 1 primary journey" in p
    assert "domain vocabulary" in p

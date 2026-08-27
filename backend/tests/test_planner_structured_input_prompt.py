"""JT-T5 — pin the STRUCTURED-INPUT MODE section into the planner prompt.

Prompts fade under revision pressure. This test asserts the five rules
we introduced are present verbatim in the system prompt. If a future
edit removes any of them, this test fails loudly and the reviewer has to
consciously accept the drift.

The specific keywords come straight from the design contract with
:mod:`services.planner_input_render` — the planner reads that block, and
these rules interpret it. Keep them in sync.
"""
from __future__ import annotations

import re

from agents.planner import _ONESHOT_SYSTEM_PROMPT


def _prompt() -> str:
    """Return the prompt with runs of whitespace (incl. newlines) collapsed
    to a single space, so phrase-level assertions don't false-fail on the
    source-code line-wrapping."""
    return re.sub(r"\s+", " ", _ONESHOT_SYSTEM_PROMPT)


def test_section_header_present():
    assert "STRUCTURED-INPUT MODE" in _prompt()


def test_authoritative_inputs_trigger_string_matches_renderer():
    """The prompt tells the LLM "look for THIS exact string in your
    user message." Renderer must emit the same string. If either drifts,
    the LLM will silently miss the block."""
    from services.planner_input_render import render_authoritative_block
    from services.structured_brief import (
        StructuredBrief, Actor, ActorOnboarding,
    )
    brief = StructuredBrief(actors=[
        Actor(name="A", role="a", onboarding=ActorOnboarding(source="platform_org")),
    ])
    rendered = re.sub(r"\s+", " ", render_authoritative_block(brief))
    trigger = "AUTHORITATIVE INPUTS — preserve verbatim, build around them"
    assert trigger in rendered, "renderer must emit the trigger string"
    assert trigger in _prompt(), "prompt must reference the same trigger string"


def test_rule_1_actors_frozen():
    p = _prompt()
    assert "Actors are frozen" in p
    assert "VERBATIM" in p
    assert "Do not add actors" in p


def test_rule_2_journey_pages_required():
    p = _prompt()
    assert "Journey pages are required" in p
    assert "pages[]" in p


def test_rule_3_journey_workflows_required():
    p = _prompt()
    assert "Journey workflows are required" in p
    assert "workflows[]" in p


def test_rule_4_user_role_enum():
    p = _prompt()
    assert "User.role enum" in p


def test_rule_5_open_questions_resolved():
    p = _prompt()
    assert "Open questions" in p
    assert "assumptions[]" in p


def test_rule_6_dont_re_derive():
    p = _prompt()
    assert "Do NOT re-derive" in p


def test_fallback_clause_present():
    """The prompt must explicitly say "no block ⇒ normal path" so that
    legacy prompt paths keep working after this addition."""
    p = _prompt()
    assert "no structured-input contract applies" in p

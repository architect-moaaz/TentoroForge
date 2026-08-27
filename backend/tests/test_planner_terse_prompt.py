"""Lockdown for the terse-plan instruction that keeps per-unit and
one-shot planner outputs from ballooning past the max_tokens cap.

Without the terseness section, the model happily fills its whole
output budget with prose descriptions that carry NO downstream
capability — every field's ``description`` and every entity's
``description`` costs output tokens without adding schema. Streaming
throughput is ~50-100 tok/s, so 6K wasted tokens = ~60-120 seconds of
wall-clock the user waits on."""
from __future__ import annotations

from agents.planner import _ONESHOT_SYSTEM_PROMPT


def test_prompt_teaches_terseness():
    """The prompt must explicitly tell the model to be concise. Absent
    the instruction, Claude will pad every field with descriptions."""
    lower = _ONESHOT_SYSTEM_PROMPT.lower()
    assert (
        "terse" in lower
        or "concise" in lower
        or "no redundant" in lower
        or "no description" in lower
    ), (
        "planner prompt must include a terseness instruction so plans "
        "fit within the max_tokens budget"
    )


def test_prompt_names_output_tokens_as_the_wall_clock_bottleneck():
    """The model should know WHY it needs to be concise — output
    tokens are streamed one at a time and are the wall-clock
    bottleneck. Absent this framing, "concise" reads as an aesthetic
    preference the model may ignore for a big domain."""
    lower = _ONESHOT_SYSTEM_PROMPT.lower()
    assert (
        "output tokens" in lower
        or "wall-clock" in lower
        or "streaming" in lower
        or "token budget" in lower
        or "24000" in lower
    )


def test_prompt_names_a_specific_hard_cap():
    """A number in the prompt anchors the model. A vague "don't be
    verbose" doesn't; a "you have 24000 tokens" does."""
    assert "24000" in _ONESHOT_SYSTEM_PROMPT or "24K" in _ONESHOT_SYSTEM_PROMPT


def test_prompt_still_documents_platform_primitive_slots():
    """Terseness must not remove the primitive-slot documentation
    from Slice 12 — that's what makes plans domain-rich. Regression
    guard against a well-meaning cleanup pass that strips the
    primitive-slot section along with description prose."""
    for slot in (
        "audit_trail",
        "immutability",
        "field_visibility",
        "capacity_constraints",
        "wizards",
    ):
        assert slot in _ONESHOT_SYSTEM_PROMPT, (
            f"terseness section removed the {slot!r} primitive-slot doc; "
            "the two sections must coexist"
        )


def test_prompt_still_teaches_authoritative_inputs_contract():
    """Regression guard: STRUCTURED-INPUT MODE (JT-T5) must survive
    the terseness edit."""
    assert "AUTHORITATIVE INPUTS" in _ONESHOT_SYSTEM_PROMPT
    assert "STRUCTURED-INPUT MODE" in _ONESHOT_SYSTEM_PROMPT

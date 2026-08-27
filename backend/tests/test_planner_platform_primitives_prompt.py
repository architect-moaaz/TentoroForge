"""Lock down the planner prompt's platform-primitive slots + the
discovery-agent confidence rubric. If someone edits the prompt and
removes these instructions the model stops emitting the new plan
slots or reverts to confidence=0.0 — silently breaking every wire
pass and downstream throttling. Fail loudly instead.
"""
from __future__ import annotations

from agents.planner import _ONESHOT_SYSTEM_PROMPT
from agents.domain_agent import _SYSTEM_PROMPT as DISCOVERY_PROMPT


# ── planner prompt: platform-primitive slots ──────────────────────

def test_prompt_names_all_five_primitive_slots():
    for slot in (
        "audit_trail",
        "immutability",
        "field_visibility",
        "capacity_constraints",
        "wizards",
    ):
        assert slot in _ONESHOT_SYSTEM_PROMPT, (
            f"planner prompt must document the {slot!r} plan slot; "
            "removing it silently disables the corresponding wire pass"
        )


def test_prompt_marks_primitives_section_clearly():
    assert "PLATFORM PRIMITIVES" in _ONESHOT_SYSTEM_PROMPT


def test_audit_trail_example_has_valid_structure():
    """The audit_trail example must include the ``on`` array with the
    three legal actions — otherwise the model authors wrong shape."""
    assert "\"on\": [\"create\",\"update\",\"delete\"]" in _ONESHOT_SYSTEM_PROMPT \
        or "\"on\": [\"create\", \"update\", \"delete\"]" in _ONESHOT_SYSTEM_PROMPT


def test_immutability_example_uses_after_submit_lifecycle():
    assert "after_submit" in _ONESHOT_SYSTEM_PROMPT
    assert "exception_roles" in _ONESHOT_SYSTEM_PROMPT


def test_field_visibility_example_shows_role_scoping():
    assert "hide_from_roles" in _ONESHOT_SYSTEM_PROMPT


def test_capacity_constraints_example_names_scope_and_limit():
    assert "scope_field" in _ONESHOT_SYSTEM_PROMPT
    assert "limit" in _ONESHOT_SYSTEM_PROMPT


def test_wizard_example_names_steps_and_fields():
    assert "wizards" in _ONESHOT_SYSTEM_PROMPT
    # Steps with title + fields shape must be shown so the model doesn't
    # invent its own step format.
    assert "\"title\":" in _ONESHOT_SYSTEM_PROMPT
    assert "\"fields\":" in _ONESHOT_SYSTEM_PROMPT


def test_primitives_are_opt_in_not_default():
    """The prompt must tell the model NOT to fabricate primitives when
    the brief doesn't call for them — otherwise every ATS gets an
    audit-trail whether or not the user asked."""
    assert "OPT-IN" in _ONESHOT_SYSTEM_PROMPT \
        or "opt-in" in _ONESHOT_SYSTEM_PROMPT \
        or "omit" in _ONESHOT_SYSTEM_PROMPT


# ── discovery prompt: confidence rubric ───────────────────────────

def test_discovery_prompt_example_confidence_is_not_zero():
    """The prior bug was ``\"confidence\": 0.0`` in the example schema —
    the LLM copied it verbatim on every run. The example must show a
    non-zero placeholder so 'model copied the example' still yields a
    useful value."""
    assert "\"confidence\":     0.0," not in DISCOVERY_PROMPT
    assert "\"confidence\": 0.0" not in DISCOVERY_PROMPT


def test_discovery_prompt_has_confidence_rubric():
    """A rubric — not just an example value — teaches the model to
    calibrate self-assessment."""
    # Rubric mentions the tiers so the model has anchors to reason with.
    assert "0.9" in DISCOVERY_PROMPT
    assert "0.7" in DISCOVERY_PROMPT
    assert "0.5" in DISCOVERY_PROMPT
    assert "0.3" in DISCOVERY_PROMPT


def test_discovery_prompt_flags_confidence_as_real_self_assessment():
    """Explicit anti-cargo-cult instruction: the model must not just
    copy whatever number appeared in the example."""
    lower = DISCOVERY_PROMPT.lower()
    assert "self-assessment" in lower or "self assess" in lower

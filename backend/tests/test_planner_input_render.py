"""JT-T3 — render StructuredBrief → AUTHORITATIVE INPUTS block."""
from __future__ import annotations

from services.structured_brief import (
    Actor, ActorOnboarding, Journey, JourneyStep, JourneyVariation,
    StructuredBrief,
)
from services.planner_input_render import (
    render_authoritative_block,
    SEPARATOR,
)


def _sample_brief() -> StructuredBrief:
    return StructuredBrief(
        overview="Applicant tracking system for aviation cabin crew.",
        domain="aviation.recruitment",
        actors=[
            Actor(name="Admin", role="admin",
                  onboarding=ActorOnboarding(source="platform_org")),
            Actor(name="Recruiter", role="recruiter",
                  onboarding=ActorOnboarding(source="invited_by", invited_by="Admin")),
            Actor(name="Candidate", role="candidate",
                  onboarding=ActorOnboarding(source="self_signup", gate="public")),
        ],
        user_journeys=[Journey(
            name="Hire a cabin crew candidate",
            primary_actor="Candidate",
            trigger="Role opens on a Drive",
            steps=[
                JourneyStep(actor="Candidate", action="Apply for a role",
                            page="/apply", outcome="Application(pending)"),
                JourneyStep(actor="Recruiter", action="Review CV",
                            page="/pipeline/[id]", workflow="ShortlistCandidate",
                            outcome="status=shortlisted"),
            ],
            variations=[
                JourneyVariation(at_step=2, condition="no fit",
                                 outcome="Application(rejected)"),
            ],
        )],
        domain_terms=["Drive", "CV", "Shortlist"],
        open_questions=["Is there a screening stage between pending and shortlisted?"],
    )


# --------------------------------------------------------------------------- #
# Empty / fallback
# --------------------------------------------------------------------------- #

def test_empty_brief_renders_nothing():
    """A brief with no actors + no journeys returns the empty string so
    the planner router can concatenate it without a nullness check."""
    assert render_authoritative_block(StructuredBrief()) == ""


def test_non_brief_input_renders_nothing():
    """Defensive: bad input types don't crash; they render empty."""
    assert render_authoritative_block(None) == ""  # type: ignore[arg-type]
    assert render_authoritative_block("garbage") == ""  # type: ignore[arg-type]


def test_dict_payload_is_parsed_and_rendered():
    """The router occasionally passes a JSON dict directly from the DB."""
    payload = {
        "actors": [{"name": "A", "role": "a",
                    "onboarding": {"source": "platform_org"}}],
        "user_journeys": [],
    }
    out = render_authoritative_block(payload)  # type: ignore[arg-type]
    assert "AUTHORITATIVE INPUTS" in out
    assert "role=a" in out


# --------------------------------------------------------------------------- #
# Full-shape rendering
# --------------------------------------------------------------------------- #

def test_full_brief_renders_every_section():
    out = render_authoritative_block(_sample_brief())
    assert "AUTHORITATIVE INPUTS" in out
    assert "## Overview" in out
    assert "aviation cabin crew" in out
    assert "## Actors  (3)" in out
    assert "## User Journeys  (1)" in out
    assert "## Domain vocabulary" in out
    assert "## Open questions  (1)" in out
    # Trailer instructions
    assert "Emit the plan in your normal JSON output schema." in out


def test_actor_rows_show_onboarding_source():
    out = render_authoritative_block(_sample_brief())
    assert "role=admin" in out and "onboarding=platform_org" in out
    assert "role=recruiter" in out and "onboarding=invited_by:Admin" in out
    assert "role=candidate" in out and "onboarding=self_signup" in out
    assert "(public)" in out  # gate rendered


def test_journey_steps_render_page_workflow_outcome():
    out = render_authoritative_block(_sample_brief())
    assert "/apply" in out
    assert "/pipeline/[id]" in out
    assert "via ShortlistCandidate" in out
    assert "Application(pending)" in out
    assert "status=shortlisted" in out


def test_journey_trigger_rendered_when_present():
    out = render_authoritative_block(_sample_brief())
    assert "trigger: Role opens on a Drive" in out


def test_journey_variation_rendered_when_present():
    out = render_authoritative_block(_sample_brief())
    assert "variation at step 2" in out
    assert "no fit" in out


def test_open_questions_rendered_as_bullets():
    out = render_authoritative_block(_sample_brief())
    assert "- Is there a screening stage" in out


# --------------------------------------------------------------------------- #
# Empty-section skipping — LLMs pattern-match on structure; absent section is
# meaningfully different from "(none)".
# --------------------------------------------------------------------------- #

def test_missing_overview_omits_section_header():
    brief = _sample_brief()
    brief.overview = ""
    out = render_authoritative_block(brief)
    assert "## Overview" not in out
    # Actors must still render — omitting overview shouldn't nuke everything.
    assert "## Actors" in out


def test_missing_domain_terms_omits_section():
    brief = _sample_brief()
    brief.domain_terms = []
    out = render_authoritative_block(brief)
    assert "## Domain vocabulary" not in out


def test_no_open_questions_omits_section():
    brief = _sample_brief()
    brief.open_questions = []
    out = render_authoritative_block(brief)
    assert "## Open questions" not in out


def test_separator_line_appears_bookending_the_block():
    out = render_authoritative_block(_sample_brief())
    # Both opening and closing separators
    assert out.count(SEPARATOR) >= 2


# --------------------------------------------------------------------------- #
# Snapshot-lite — pin the exact shape so drift is loud
# --------------------------------------------------------------------------- #

def test_actor_row_shape_is_stable():
    """The actor row format is part of the contract with the planner
    prompt. If we change it here, the prompt example needs to change
    too — pin the shape."""
    a = Actor(name="Recruiter", role="recruiter",
              onboarding=ActorOnboarding(source="invited_by", invited_by="Admin"))
    from services.planner_input_render import _render_actor_row
    row = _render_actor_row(a)
    assert row == "- Recruiter      role=recruiter      onboarding=invited_by:Admin"


def test_journey_step_shape_is_stable():
    step = JourneyStep(actor="Recruiter", action="Schedule interview",
                       page="/interviews/new", workflow="ScheduleInterview",
                       outcome="Interview + notify")
    from services.planner_input_render import _render_journey_step
    line = _render_journey_step(step, index=3)
    assert line.startswith("    3. Recruiter")
    assert "page=/interviews/new" in line
    assert "via ScheduleInterview" in line
    assert "→ Interview + notify" in line

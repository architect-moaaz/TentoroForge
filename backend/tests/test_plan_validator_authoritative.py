"""JT-T2 — authoritative-brief contract check.

Every commitment the discovery→transformer StructuredBrief made must
appear in the plan the planner produced. This test file exercises the
rule against a small library of plan/brief pairs; each case pins one
class of violation so a regression names itself precisely.
"""
from __future__ import annotations

from services.plan_validator import (
    validate_plan_against_brief,
    _rule_authoritative_inputs_honored,
)
from services.structured_brief import (
    Actor, ActorOnboarding, Journey, JourneyStep, StructuredBrief,
)


def _check(plan, brief):
    """Run ONLY the new rule so unrelated plan-shape violations don't
    contaminate these tests. The wrapper (``validate_plan_against_brief``)
    that composes with the rest of ``validate_plan`` gets its own smoke
    test at the bottom of this file."""
    return _rule_authoritative_inputs_honored(plan, brief)


# --------------------------------------------------------------------------- #
# Canonical clean plan + brief — every negative test drifts one field.
# --------------------------------------------------------------------------- #

def _brief() -> StructuredBrief:
    return StructuredBrief(
        overview="ATS",
        domain="recruitment",
        actors=[
            Actor(name="Admin",     role="admin",
                  onboarding=ActorOnboarding(source="platform_org")),
            Actor(name="Recruiter", role="recruiter",
                  onboarding=ActorOnboarding(source="invited_by", invited_by="Admin")),
            Actor(name="Candidate", role="candidate",
                  onboarding=ActorOnboarding(source="self_signup")),
        ],
        user_journeys=[Journey(
            name="Apply", primary_actor="Candidate",
            steps=[
                JourneyStep(actor="Candidate", action="apply", page="/apply",
                            outcome="Application created"),
                JourneyStep(actor="Recruiter", action="review", page="/pipeline/[id]",
                            workflow="ShortlistCandidate", outcome="shortlisted"),
            ],
        )],
    )


def _plan_that_honors(brief: StructuredBrief) -> dict:
    """A plan that satisfies every commitment in the brief."""
    return {
        "actors": [a.to_dict() for a in brief.actors],
        "pages": [
            {"route": s.page, "name": s.action, "type": "form"}
            for j in brief.user_journeys for s in j.steps
        ],
        "workflows": [
            {"name": s.workflow, "steps": []}
            for j in brief.user_journeys for s in j.steps if s.workflow
        ],
        "data_models": [
            {"name": "User", "fields": [
                {"name": "role", "type": "varchar",
                 "enum_values": [a.role for a in brief.actors]},
            ]},
        ],
        "assumptions": [],
    }


# --------------------------------------------------------------------------- #
# Positive: clean plan against brief validates
# --------------------------------------------------------------------------- #

def test_clean_plan_against_brief_passes():
    brief = _brief()
    plan = _plan_that_honors(brief)
    vs = _check(plan, brief)
    assert vs == []


def test_empty_brief_is_effectively_ignored():
    """A brief with no actors + no journeys is the 'no discovery ran'
    signal. Every plan should validate against it as if no brief was
    supplied."""
    empty = StructuredBrief()
    plan = {"pages": [], "workflows": [], "actors": [], "data_models": []}
    vs = validate_plan_against_brief(plan, empty)
    assert not any(v["rule"].startswith("authoritative_") for v in vs)


def test_none_brief_is_a_noop():
    """The wrapper degrades to core validation only. Core rules may still
    fire on an incomplete plan; the key guarantee is that no
    ``authoritative_*`` rule fires when the brief is absent."""
    plan = {"pages": [], "workflows": [], "actors": []}
    vs = validate_plan_against_brief(plan, None)
    assert not any(v["rule"].startswith("authoritative_") for v in vs)


# --------------------------------------------------------------------------- #
# Actor commitments
# --------------------------------------------------------------------------- #

def test_missing_actor_flagged():
    brief = _brief()
    plan = _plan_that_honors(brief)
    plan["actors"] = [a for a in plan["actors"] if a["name"] != "Recruiter"]
    vs = _check(plan, brief)
    rules = {v["rule"] for v in vs}
    assert "authoritative_actor_missing" in rules


def test_actor_role_mismatch_flagged():
    brief = _brief()
    plan = _plan_that_honors(brief)
    for a in plan["actors"]:
        if a["name"] == "Recruiter":
            a["role"] = "sourcer"  # renamed
    vs = _check(plan, brief)
    rules = {v["rule"] for v in vs}
    assert "authoritative_actor_role_mismatch" in rules


def test_actor_onboarding_source_mismatch_flagged():
    brief = _brief()
    plan = _plan_that_honors(brief)
    for a in plan["actors"]:
        if a["name"] == "Candidate":
            a["onboarding"] = {"source": "invited_by", "invited_by": "Admin"}
    vs = _check(plan, brief)
    rules = {v["rule"] for v in vs}
    assert "authoritative_actor_onboarding_mismatch" in rules


def test_actor_inviter_mismatch_flagged():
    brief = _brief()
    plan = _plan_that_honors(brief)
    for a in plan["actors"]:
        if a["name"] == "Recruiter":
            a["onboarding"] = {"source": "invited_by", "invited_by": "Recruiter"}  # self-invite nonsense
    vs = _check(plan, brief)
    rules = {v["rule"] for v in vs}
    assert "authoritative_actor_inviter_mismatch" in rules


# --------------------------------------------------------------------------- #
# Journey page/workflow commitments — the core value-add
# --------------------------------------------------------------------------- #

def test_missing_journey_page_flagged():
    brief = _brief()
    plan = _plan_that_honors(brief)
    plan["pages"] = [p for p in plan["pages"] if p["route"] != "/pipeline/[id]"]
    vs = _check(plan, brief)
    hits = [v for v in vs if v["rule"] == "authoritative_journey_page_missing"]
    assert hits, "expected a page-missing violation"
    assert "/pipeline/[id]" in hits[0]["message"]


def test_missing_journey_workflow_flagged():
    brief = _brief()
    plan = _plan_that_honors(brief)
    plan["workflows"] = []
    vs = _check(plan, brief)
    hits = [v for v in vs if v["rule"] == "authoritative_journey_workflow_missing"]
    assert hits
    assert "ShortlistCandidate" in hits[0]["message"]


def test_journey_step_without_workflow_field_doesnt_require_one():
    """The Candidate 'apply' step has no `workflow` — the check MUST NOT
    invent a requirement."""
    brief = _brief()
    plan = _plan_that_honors(brief)
    # Remove all workflows entirely; only the Recruiter step referenced one
    # so the loss must produce exactly ONE violation, not one per step.
    plan["workflows"] = []
    vs = _check(plan, brief)
    wf_misses = [v for v in vs if v["rule"] == "authoritative_journey_workflow_missing"]
    assert len(wf_misses) == 1


# --------------------------------------------------------------------------- #
# User.role enum coverage
# --------------------------------------------------------------------------- #

def test_missing_user_role_enum_value_flagged():
    brief = _brief()
    plan = _plan_that_honors(brief)
    for e in plan["data_models"]:
        if e["name"] == "User":
            for f in e["fields"]:
                if f["name"] == "role":
                    f["enum_values"] = ["admin", "recruiter"]  # missing candidate
    vs = _check(plan, brief)
    hits = [v for v in vs if v["rule"] == "authoritative_user_role_enum_missing"]
    assert hits
    assert "candidate" in hits[0]["message"]


def test_no_user_entity_skips_enum_check():
    """If the plan doesn't yet declare a User entity, don't emit an enum
    violation — the auto-actor-model pass (Slice B) will add it. Otherwise
    we'd get spurious violations on plans mid-processing."""
    brief = _brief()
    plan = _plan_that_honors(brief)
    plan["data_models"] = []  # no User
    vs = _check(plan, brief)
    assert not any(v["rule"] == "authoritative_user_role_enum_missing" for v in vs)


# --------------------------------------------------------------------------- #
# Open questions
# --------------------------------------------------------------------------- #

def test_open_question_unresolved_flagged():
    brief = StructuredBrief(
        actors=[Actor(name="A", role="a", onboarding=ActorOnboarding(source="platform_org"))],
        open_questions=["Is there a screening stage between pending and shortlisted?"],
    )
    plan = {
        "actors": [a.to_dict() for a in brief.actors],
        "assumptions": [],
        "data_models": [{"name": "User", "fields": [
            {"name": "role", "enum_values": ["a"]}]}],
    }
    vs = _check(plan, brief)
    rules = {v["rule"] for v in vs}
    assert "authoritative_open_question_unresolved" in rules


def test_open_question_resolved_by_assumption_passes():
    brief = StructuredBrief(
        actors=[Actor(name="A", role="a", onboarding=ActorOnboarding(source="platform_org"))],
        open_questions=["Is there a screening stage between pending and shortlisted?"],
    )
    plan = {
        "actors": [a.to_dict() for a in brief.actors],
        "assumptions": [
            "Added a screening stage between pending and shortlisted so "
            "recruiters can triage before shortlist."
        ],
        "data_models": [{"name": "User", "fields": [
            {"name": "role", "enum_values": ["a"]}]}],
    }
    vs = _check(plan, brief)
    assert not any(v["rule"] == "authoritative_open_question_unresolved" for v in vs)


# --------------------------------------------------------------------------- #
# Robustness — bad brief input degrades to warning, doesn't crash
# --------------------------------------------------------------------------- #

def test_unparseable_brief_degrades_to_warning():
    """A malformed brief attached to a project shouldn't crash the
    validator — surface a warning and fall through. Uses the wrapper
    intentionally: parse-failure handling lives at that layer."""
    plan = {"actors": [], "pages": [], "workflows": []}
    vs = validate_plan_against_brief(plan, {"actors": "not-a-list"})
    warns = [v for v in vs if v["rule"] == "authoritative_brief_parse_failed"]
    assert warns
    assert warns[0]["severity"] == "warning"

"""JT-T1 — parse + serialize + round-trip the discovery→planner contract."""
from __future__ import annotations

import json

import pytest

from services.structured_brief import (
    Actor,
    ActorOnboarding,
    BriefParseError,
    Journey,
    JourneyStep,
    JourneyVariation,
    StructuredBrief,
    VALID_ONBOARDING_SOURCES,
)


# --------------------------------------------------------------------------- #
# The shape we expect the transformer to emit — one canonical fixture that
# every test builds from. If this drifts, downstream tests break loudly.
# --------------------------------------------------------------------------- #

def _canonical_brief_dict() -> dict:
    return {
        "overview": "Applicant Tracking System for cabin crew recruitment.",
        "domain":   "aviation.recruitment",
        "actors": [
            {
                "name": "Admin", "role": "admin",
                "onboarding": {"source": "platform_org"},
                "responsibilities": ["Invite recruiters", "Manage org"],
            },
            {
                "name": "Recruiter", "role": "recruiter",
                "onboarding": {"source": "invited_by", "invited_by": "Admin"},
                "responsibilities": ["Shortlist", "Schedule interviews"],
            },
            {
                "name": "Candidate", "role": "candidate",
                "onboarding": {"source": "self_signup", "gate": "public"},
                "responsibilities": ["Apply", "Upload CV"],
            },
        ],
        "user_journeys": [
            {
                "name": "Hire a cabin crew candidate",
                "primary_actor": "Candidate",
                "trigger": "New role opens on a Drive",
                "steps": [
                    {"actor": "Candidate", "action": "Apply for a role",
                     "page": "/apply",
                     "outcome": "Application(status=pending) created"},
                    {"actor": "Recruiter", "action": "Review CV",
                     "page": "/pipeline/[id]", "workflow": "ShortlistCandidate",
                     "outcome": "status=shortlisted"},
                    {"actor": "Recruiter", "action": "Schedule interview",
                     "page": "/interviews/new", "workflow": "ScheduleInterview",
                     "outcome": "Interview + notify"},
                ],
                "variations": [
                    {"at_step": 2, "condition": "no fit",
                     "outcome": "Application(status=rejected)"},
                ],
            },
        ],
        "domain_terms":   ["Drive", "CV", "Shortlist"],
        "open_questions": ["Is there a screening stage between pending and shortlisted?"],
    }


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #

def test_parse_from_dict_round_trips_verbatim():
    """to_dict(parse(x)) == x for a well-formed brief. Guarantees the
    transformer can emit → we parse → we serialize → we hand off, all
    with no loss."""
    src = _canonical_brief_dict()
    brief = StructuredBrief.parse(src)
    assert brief.to_dict() == src


def test_parse_from_json_string():
    src = _canonical_brief_dict()
    brief = StructuredBrief.parse(json.dumps(src))
    assert brief.to_dict() == src


def test_parse_empty_dict_gives_empty_brief():
    brief = StructuredBrief.parse({})
    assert brief.is_empty()
    assert brief.overview == ""
    assert brief.actors == []
    assert brief.user_journeys == []


# --------------------------------------------------------------------------- #
# is_empty — the fallback signal for the planner router
# --------------------------------------------------------------------------- #

def test_is_empty_true_when_no_actors_and_no_journeys():
    """The router uses is_empty() to decide whether to render an
    AUTHORITATIVE INPUTS block. Overview alone isn't enough — without
    actors/journeys the planner has nothing structural to honor."""
    brief = StructuredBrief(overview="just prose")
    assert brief.is_empty()


def test_is_empty_false_when_actors_present():
    brief = StructuredBrief(actors=[
        Actor(name="A", role="a", onboarding=ActorOnboarding(source="platform_org")),
    ])
    assert not brief.is_empty()


def test_is_empty_false_when_journeys_present_even_without_actors():
    """Some briefs may capture the journey shape before the actor list is
    finalised — the block is still worth emitting."""
    brief = StructuredBrief(user_journeys=[
        Journey(name="X", steps=[JourneyStep(actor="A", action="do", page="/")]),
    ])
    assert not brief.is_empty()


# --------------------------------------------------------------------------- #
# Actor parsing
# --------------------------------------------------------------------------- #

def test_actor_missing_onboarding_defaults_cleanly():
    brief = StructuredBrief.parse({"actors": [{"name": "A", "role": "a"}]})
    assert brief.actors[0].onboarding.source == ""
    assert brief.actors[0].onboarding.invited_by is None


def test_actor_onboarding_invited_by_survives_parse():
    brief = StructuredBrief.parse({
        "actors": [{"name": "R", "role": "recruiter",
                    "onboarding": {"source": "invited_by", "invited_by": "Admin"}}],
    })
    assert brief.actors[0].onboarding.source == "invited_by"
    assert brief.actors[0].onboarding.invited_by == "Admin"


def test_actor_responsibilities_defaults_to_empty():
    brief = StructuredBrief.parse({"actors": [{"name": "A", "role": "a"}]})
    assert brief.actors[0].responsibilities == []


# --------------------------------------------------------------------------- #
# Journey parsing
# --------------------------------------------------------------------------- #

def test_journey_step_workflow_optional():
    brief = StructuredBrief.parse({
        "user_journeys": [{
            "name": "X", "primary_actor": "A",
            "steps": [
                {"actor": "A", "action": "apply", "page": "/apply", "outcome": "created"},
            ],
        }],
    })
    step = brief.user_journeys[0].steps[0]
    assert step.workflow is None
    # Serialisation drops the workflow key when absent
    assert "workflow" not in step.to_dict()


def test_journey_step_workflow_preserved():
    brief = StructuredBrief.parse({
        "user_journeys": [{
            "name": "X", "primary_actor": "A",
            "steps": [{"actor": "A", "action": "do", "page": "/x",
                       "workflow": "DoThing", "outcome": "done"}],
        }],
    })
    assert brief.user_journeys[0].steps[0].workflow == "DoThing"


def test_journey_variation_at_step_coerces_to_int():
    """Discovery LLMs sometimes stringify step numbers. Coerce."""
    brief = StructuredBrief.parse({
        "user_journeys": [{
            "name": "X", "primary_actor": "A", "steps": [],
            "variations": [{"at_step": "2", "condition": "c", "outcome": "o"}],
        }],
    })
    assert brief.user_journeys[0].variations[0].at_step == 2


def test_journey_variation_at_step_defaults_zero_on_garbage():
    brief = StructuredBrief.parse({
        "user_journeys": [{
            "name": "X", "primary_actor": "A", "steps": [],
            "variations": [{"at_step": "not-a-number", "condition": "c", "outcome": "o"}],
        }],
    })
    assert brief.user_journeys[0].variations[0].at_step == 0


def test_journey_missing_variations_serializes_without_the_key():
    """Journey with no variations must NOT emit an empty ``variations``
    list in the dict — the round-trip test asserts equality, and the
    canonical fixture only includes variations on the journey that has
    them."""
    brief = StructuredBrief.parse({
        "user_journeys": [{
            "name": "X", "primary_actor": "A",
            "steps": [{"actor": "A", "action": "do", "page": "/x", "outcome": "ok"}],
        }],
    })
    j = brief.user_journeys[0].to_dict()
    assert "variations" not in j


# --------------------------------------------------------------------------- #
# Error paths — only truly malformed input raises
# --------------------------------------------------------------------------- #

def test_parse_non_dict_raises():
    with pytest.raises(BriefParseError, match="must be a JSON object"):
        StructuredBrief.parse([1, 2, 3])


def test_parse_invalid_json_string_raises():
    with pytest.raises(BriefParseError, match="not valid JSON"):
        StructuredBrief.parse("{not-json")


def test_parse_actors_wrong_shape_raises():
    with pytest.raises(BriefParseError, match=r"`actors` must be a list"):
        StructuredBrief.parse({"actors": "recruiter, candidate"})


def test_parse_actor_not_object_raises():
    with pytest.raises(BriefParseError, match=r"actors\[0\]"):
        StructuredBrief.parse({"actors": ["Admin"]})


def test_parse_actor_onboarding_wrong_shape_raises():
    with pytest.raises(BriefParseError, match="onboarding"):
        StructuredBrief.parse({"actors": [{"name": "A", "role": "a",
                                            "onboarding": "public"}]})


def test_parse_journeys_wrong_shape_raises():
    with pytest.raises(BriefParseError, match="user_journeys"):
        StructuredBrief.parse({"user_journeys": "apply then interview"})


def test_parse_journey_step_wrong_shape_raises():
    with pytest.raises(BriefParseError, match=r"user_journeys\[0\]\.steps\[1\]"):
        StructuredBrief.parse({
            "user_journeys": [{"name": "X", "primary_actor": "A", "steps": [
                {"actor": "A", "action": "x", "page": "/x", "outcome": "y"},
                "just a string",
            ]}],
        })


# --------------------------------------------------------------------------- #
# Contract exposure — VALID_ONBOARDING_SOURCES must match the plan validator's
# set. Duplicating the constant here would let the two drift silently; import
# it and assert its content, so a rename in one place breaks this test loudly.
# --------------------------------------------------------------------------- #

def test_onboarding_sources_match_plan_validator_contract():
    from services.plan_validator import _VALID_ONBOARDING_SOURCES as v
    assert VALID_ONBOARDING_SOURCES == v


# --------------------------------------------------------------------------- #
# Smoke — the string coercion actually strips whitespace
# --------------------------------------------------------------------------- #

def test_whitespace_stripped_from_strings():
    brief = StructuredBrief.parse({
        "overview": "  padded  ",
        "actors": [{"name": " A ", "role": " a ",
                    "onboarding": {"source": " platform_org "}}],
    })
    assert brief.overview == "padded"
    assert brief.actors[0].name == "A"
    assert brief.actors[0].role == "a"
    assert brief.actors[0].onboarding.source == "platform_org"

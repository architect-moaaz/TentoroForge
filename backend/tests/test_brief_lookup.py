"""JT-T10 — brief lookup for the planner router.

The async DB fetch is exercised by the router integration tests; here we
lock down the sync helper's contract so the wrapper's fallback signals
are stable no matter what discovery stored.
"""
from __future__ import annotations

import pytest

from services.brief_lookup import parse_structured_brief_from_dict


def test_none_input_returns_none():
    assert parse_structured_brief_from_dict(None) is None


def test_empty_dict_returns_none():
    """An empty dict parses successfully but is_empty() → True, so the
    lookup returns None. The planner router treats None as "no
    authoritative inputs" and skips the block."""
    assert parse_structured_brief_from_dict({}) is None


def test_bare_overview_without_structure_returns_none():
    """A brief that has prose but no actors + no journeys has nothing
    structural to hand off. The router should NOT render an
    AUTHORITATIVE INPUTS block for it."""
    assert parse_structured_brief_from_dict({"overview": "some prose"}) is None


def test_brief_with_actors_returns_parsed_brief():
    """A brief with even one actor produces a StructuredBrief and passes
    the empty check. Router will render the block."""
    from services.structured_brief import StructuredBrief
    brief = parse_structured_brief_from_dict({
        "actors": [{
            "name": "Recruiter", "role": "recruiter",
            "onboarding": {"source": "invited_by", "invited_by": "Admin"},
        }],
    })
    assert isinstance(brief, StructuredBrief)
    assert brief.actors[0].name == "Recruiter"


def test_brief_with_only_journeys_returns_parsed_brief():
    """Rare — but a discovery that captured journeys before finalising
    actors is still worth handing off. is_empty() returns False on
    journey-only briefs."""
    from services.structured_brief import StructuredBrief
    brief = parse_structured_brief_from_dict({
        "user_journeys": [{
            "name": "X", "primary_actor": "Anyone",
            "steps": [{"actor": "A", "action": "do", "page": "/x",
                       "outcome": "ok"}],
        }],
    })
    assert isinstance(brief, StructuredBrief)


def test_unparseable_payload_returns_none():
    """A malformed brief (wrong type on a required field) doesn't crash
    the planner — the lookup returns None and the router falls through."""
    assert parse_structured_brief_from_dict({"actors": "not-a-list"}) is None


def test_non_dict_payload_returns_none():
    assert parse_structured_brief_from_dict("not a dict") is None
    assert parse_structured_brief_from_dict([1, 2, 3]) is None


def test_round_trip_shape_preservation():
    """The lookup preserves fields verbatim so the router+renderer see
    what discovery emitted, byte-for-byte."""
    payload = {
        "overview": "ATS",
        "actors": [{
            "name": "Recruiter", "role": "recruiter",
            "onboarding": {"source": "invited_by", "invited_by": "Admin"},
        }],
        "user_journeys": [{
            "name": "hire", "primary_actor": "Candidate",
            "steps": [
                {"actor": "Candidate", "action": "apply", "page": "/apply",
                 "outcome": "applied"},
            ],
        }],
        "domain_terms":   ["Drive"],
        "open_questions": ["screening?"],
    }
    brief = parse_structured_brief_from_dict(payload)
    assert brief is not None
    # Parser fills in optional fields (e.g. responsibilities=[]) — assert
    # the input fields survived rather than full-shape equality.
    got_actor = brief.to_dict()["actors"][0]
    for k, v in payload["actors"][0].items():
        assert got_actor[k] == v
    assert brief.to_dict()["user_journeys"][0]["steps"] == payload["user_journeys"][0]["steps"]

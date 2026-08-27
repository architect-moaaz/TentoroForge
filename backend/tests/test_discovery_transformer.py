"""JT-T7 — discovery transformer.

Uses stubbed LLM callables to keep the tests deterministic. The transformer
itself never talks to Anthropic in this file.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from services.discovery_transformer import (
    transform_discovery,
    _extract_json,
    _normalize_transcript,
)
from services.structured_brief import StructuredBrief


def _canned_brief_json() -> str:
    return json.dumps({
        "overview": "ATS for cabin crew.",
        "domain":   "aviation.recruitment",
        "actors": [
            {"name": "Admin", "role": "admin",
             "onboarding": {"source": "platform_org"}},
            {"name": "Recruiter", "role": "recruiter",
             "onboarding": {"source": "invited_by", "invited_by": "Admin"}},
            {"name": "Candidate", "role": "candidate",
             "onboarding": {"source": "self_signup", "gate": "public"}},
        ],
        "user_journeys": [{
            "name": "Hire a candidate", "primary_actor": "Candidate",
            "steps": [
                {"actor": "Candidate", "action": "Apply", "page": "/apply",
                 "outcome": "Application(pending) created"},
                {"actor": "Recruiter", "action": "Review CV",
                 "page": "/pipeline/[id]", "workflow": "ShortlistCandidate",
                 "outcome": "status=shortlisted"},
            ],
        }],
        "domain_terms":   ["Drive", "CV"],
        "open_questions": [],
    })


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #

def test_transforms_a_transcript_into_structured_brief():
    calls: list[tuple[str, str]] = []
    async def stub(system, user):
        calls.append((system, user))
        return _canned_brief_json()

    brief = asyncio.run(transform_discovery(
        "recruiter: build me an ATS for cabin crew...",
        query_fn=stub,
    ))
    assert not brief.is_empty()
    assert len(brief.actors) == 3
    assert brief.actors[1].name == "Recruiter"
    assert brief.actors[1].onboarding.source == "invited_by"
    assert brief.actors[1].onboarding.invited_by == "Admin"
    # LLM was called exactly once — no retry needed
    assert len(calls) == 1


def test_transcript_is_included_in_the_user_prompt():
    captured_prompts: list[str] = []
    async def stub(system, user):
        captured_prompts.append(user)
        return _canned_brief_json()

    asyncio.run(transform_discovery(
        "the actor Recruiter kicks off a hiring drive",
        query_fn=stub,
    ))
    assert "kicks off a hiring drive" in captured_prompts[0]


# --------------------------------------------------------------------------- #
# Robustness — bad LLM output triggers retry, empty on final failure
# --------------------------------------------------------------------------- #

def test_retries_on_invalid_json_then_succeeds():
    """The transformer forgives one bad output. It emits the transcript
    plus a hint about the last error on the retry."""
    responses = iter([
        "sure! here's the json: ```{not-json",
        _canned_brief_json(),
    ])
    async def stub(system, user):
        return next(responses)

    brief = asyncio.run(transform_discovery(
        "transcript",
        query_fn=stub,
        max_retries=1,
    ))
    assert not brief.is_empty()
    assert brief.actors[0].name == "Admin"


def test_returns_empty_brief_when_llm_keeps_failing():
    """After max retries with no valid output, the transformer returns
    an empty brief. The planner router falls through to legacy authoring."""
    async def bad(system, user):
        return "not json"
    brief = asyncio.run(transform_discovery(
        "transcript",
        query_fn=bad,
        max_retries=1,
    ))
    assert isinstance(brief, StructuredBrief)
    assert brief.is_empty()


def test_llm_crash_falls_back_to_retry_then_empty():
    async def crash(system, user):
        raise RuntimeError("network")
    brief = asyncio.run(transform_discovery(
        "transcript",
        query_fn=crash,
        max_retries=1,
    ))
    assert brief.is_empty()


def test_empty_transcript_short_circuits_before_llm():
    called = False
    async def stub(system, user):
        nonlocal called
        called = True
        return _canned_brief_json()
    brief = asyncio.run(transform_discovery("", query_fn=stub))
    assert brief.is_empty()
    assert not called, "no LLM call for empty transcript"


# --------------------------------------------------------------------------- #
# Retry prompt carries the error hint
# --------------------------------------------------------------------------- #

def test_retry_prompt_includes_prior_error():
    prompts: list[str] = []
    responses = iter([
        "totally not json",
        _canned_brief_json(),
    ])
    async def stub(system, user):
        prompts.append(user)
        return next(responses)

    asyncio.run(transform_discovery(
        "transcript",
        query_fn=stub,
        max_retries=1,
    ))
    assert len(prompts) == 2
    # Retry prompt names the previous failure so the LLM can course-correct
    assert "previous attempt failed" in prompts[1]


# --------------------------------------------------------------------------- #
# Helpers — transcript normalization + JSON extraction
# --------------------------------------------------------------------------- #

def test_normalize_list_of_turns():
    turns = [
        {"role": "user",      "content": "build me an ATS"},
        {"role": "assistant", "content": "great — who uses it?"},
        {"role": "user",      "content": "candidates and recruiters"},
    ]
    out = _normalize_transcript(turns)
    assert "user: build me an ATS" in out
    assert "assistant: great" in out


def test_normalize_dict_source_stringified():
    out = _normalize_transcript({"app_name": "ATS", "domain": "recruitment"})
    assert "app_name" in out
    assert "recruitment" in out


def test_extract_json_peels_off_prose():
    raw = "Sure! ```json\n{\"a\": 1}\n```\nCheers"
    assert _extract_json(raw) == {"a": 1}


def test_extract_json_raises_on_no_object():
    with pytest.raises(ValueError, match="no JSON object"):
        _extract_json("just prose")


def test_extract_json_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        _extract_json("")

"""JT-T6 — post-planner brief-contract validation triggers a REVISE retry.

We stub the LLM to return a violating plan on turn 1 and a passing plan
on turn 2. When ``FORGE_PLANNER_V2`` is on, the router's Layer-A gate
must detect the authoritative-brief violation, retry, and emit the
clean plan.

WHY THE CALL COUNT IS NOT THE ASSERTION ANY MORE. `produce_plan` carries three
retry layers, and the brief gate is one of them: the same Layer A also runs a
deterministic structural validator, and an IRF revise follows it. The fixture
plans here are written to exercise the BRIEF contract and are incomplete by
those other rules — eight violations on the "honoring" plan (no field types, no
nav, no submit) — so a clean-brief plan still took two extra turns and the
count read as the gate misfiring. Filling the fixtures in to satisfy every
structural rule would make them rot again the next time one is added.

So each test asserts what its gate DOES: which plan comes back, and whether a
retry prompt carried a brief hint. `_brief_hints` is the observable the gate
owns; the other layers cannot produce one.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from routers.generate import produce_plan
from services.structured_brief import (
    Actor, ActorOnboarding, Journey, JourneyStep, StructuredBrief,
)


def _brief() -> StructuredBrief:
    # Admin is included as an actor so the Slice-B ``_rule_actors``
    # inviter-existence check is satisfied for the clean-plan case; the
    # authoritative-rule under test doesn't need it.
    return StructuredBrief(
        actors=[
            Actor(name="Admin", role="admin",
                  onboarding=ActorOnboarding(source="platform_org")),
            Actor(name="Recruiter", role="recruiter",
                  onboarding=ActorOnboarding(source="invited_by", invited_by="Admin")),
        ],
        user_journeys=[Journey(
            name="hire", primary_actor="Candidate",
            steps=[JourneyStep(actor="Candidate", action="apply",
                               page="/apply", outcome="applied")],
        )],
    )


def _violating_plan() -> dict:
    """Plan that dishonors the brief: missing actor, missing journey page."""
    return {
        "module_name": "bad",
        "actors": [],  # missing Recruiter
        "pages":  [],  # missing /apply
        "workflows": [],
        "data_models": [{"name": "User", "fields": [
            {"name": "role", "enum_values": ["recruiter"]}]}],
        "relations": [],
        "assumptions": [],
    }


def _honoring_plan(brief: StructuredBrief) -> dict:
    return {
        "module_name": "good",
        "actors": [a.to_dict() for a in brief.actors],
        "pages":  [{"route": s.page, "name": s.action, "type": "form"}
                   for j in brief.user_journeys for s in j.steps],
        "workflows": [],
        "data_models": [{"name": "User", "fields": [
            {"name": "role", "enum_values": [a.role for a in brief.actors]}]}],
        "relations": [],
        "assumptions": [],
    }


#: The rules only the brief gate emits. Matched by NAME, not by the word
#: "authoritative": every prompt carries an "AUTHORITATIVE INPUTS" block of its
#: own, so a substring test counts the original prompt as a violation hint.
_BRIEF_RULES = (
    "authoritative_actor_missing",
    "authoritative_actor_role_mismatch",
    "authoritative_actor_inviter_mismatch",
    "authoritative_actor_onboarding_mismatch",
    "authoritative_journey_page_missing",
    "authoritative_journey_workflow_missing",
)


def _brief_hints(prompts: list[str]) -> list[str]:
    """RETRY prompts carrying a brief violation, in the order they were sent.

    Only the brief gate names these rules, so this counts ITS retries and
    ignores the structural validator's and the IRF revise's, which run on the
    same plans for their own reasons. The first prompt is the original ask and
    is never a retry.
    """
    return [p for p in prompts[1:] if any(r in p for r in _BRIEF_RULES)]


class _RetryStub:
    """Returns violating plan first, honoring plan on the second call.
    Records every prompt so we can assert the retry prompt contains
    a violation hint."""
    def __init__(self, brief: StructuredBrief):
        self.brief = brief
        self.calls = 0
        self.prompts: list[str] = []

    async def __call__(self, prompt_text: str) -> dict:
        self.prompts.append(prompt_text)
        self.calls += 1
        return _violating_plan() if self.calls == 1 else _honoring_plan(self.brief)


def test_v2_gate_retries_on_authoritative_violation(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_PLANNER_V2", "1")
    monkeypatch.delenv("FORGE_PLANNER_CRITIC", raising=False)
    brief = _brief()
    stub = _RetryStub(brief)
    plan = asyncio.run(produce_plan(
        prompt="build me an ATS",
        output_dir=str(tmp_path),
        structured_brief=brief,
        _should_decompose=lambda p: False,
        _oneshot=stub,
    ))
    # The gate retried, and the retry carried the brief violation with it.
    assert stub.calls >= 2, f"expected a retry, got {stub.calls} call(s)"
    retry_prompt = stub.prompts[1]
    assert "validation errors" in retry_prompt or "authoritative_" in retry_prompt
    # Final plan is the honoring one
    assert plan.get("module_name") == "good"


def test_v2_gate_noop_when_plan_honors_brief(monkeypatch, tmp_path):
    """Positive case: brief passes on turn 1 → no retry needed."""
    monkeypatch.setenv("FORGE_PLANNER_V2", "1")
    monkeypatch.delenv("FORGE_PLANNER_CRITIC", raising=False)
    brief = _brief()

    class _CleanStub:
        def __init__(self):
            self.calls = 0
            self.prompts: list[str] = []
        async def __call__(self, prompt):
            self.prompts.append(prompt)
            self.calls += 1
            return _honoring_plan(brief)

    stub = _CleanStub()
    plan = asyncio.run(produce_plan(
        prompt="build me an ATS",
        output_dir=str(tmp_path),
        structured_brief=brief,
        _should_decompose=lambda p: False,
        _oneshot=stub,
    ))
    # The BRIEF gate found nothing to say. Other layers may still have asked
    # for a revision — this plan is thin by their rules — but none of their
    # prompts can carry a brief violation.
    assert _brief_hints(stub.prompts) == [], stub.prompts
    assert plan.get("module_name") == "good"


def test_v2_gate_disabled_lets_bad_plan_through(monkeypatch, tmp_path):
    """With the gate off, a plan that dishonours the brief is returned as-is.

    UNSETTING THE VARIABLE NO LONGER TURNS IT OFF. `FORGE_PLANNER_V2` defaults
    to "on" now — `os.getenv("FORGE_PLANNER_V2", "on")` — so `delenv` left the
    gate running, it found the brief violations it is supposed to find, the
    stub answered the retry with the honoring plan, and this test read "good"
    where it wanted "bad". Off is now something you say, not something you
    omit; the line that reads the flag says `Set FORGE_PLANNER_V2=off`.
    """
    monkeypatch.setenv("FORGE_PLANNER_V2", "off")
    monkeypatch.delenv("FORGE_PLANNER_CRITIC", raising=False)
    brief = _brief()
    stub = _RetryStub(brief)
    plan = asyncio.run(produce_plan(
        prompt="build me an ATS",
        output_dir=str(tmp_path),
        structured_brief=brief,
        _should_decompose=lambda p: False,
        _oneshot=stub,
    ))
    assert _brief_hints(stub.prompts) == [], "the gate is off and must say nothing"
    # And the bad plan flowed through, which is what "off" means.
    assert plan.get("module_name") == "bad"

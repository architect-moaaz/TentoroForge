"""JT-T6 — post-planner brief-contract validation triggers a REVISE retry.

We stub the LLM to return a violating plan on turn 1 and a passing plan
on turn 2. When ``FORGE_PLANNER_V2`` is on, the router's Layer-A gate
must detect the authoritative-brief violation, retry, and emit the
clean plan.
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
    # Two LLM calls happened: initial + retry
    assert stub.calls == 2, f"expected 2 calls (initial + retry), got {stub.calls}"
    # The retry prompt contains a hint referencing the violations
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
        def __init__(self): self.calls = 0
        async def __call__(self, prompt):
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
    assert stub.calls == 1, "no retry expected for a clean plan"
    assert plan.get("module_name") == "good"


def test_v2_gate_disabled_lets_bad_plan_through(monkeypatch, tmp_path):
    """When both FORGE_PLANNER_V2 and _CRITIC are off, validation
    is skipped entirely (legacy behaviour). Ensures we don't turn on
    validation by accident."""
    monkeypatch.delenv("FORGE_PLANNER_V2", raising=False)
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
    assert stub.calls == 1, "no retry when V2 gate is off"
    # Bad plan flowed through
    assert plan.get("module_name") == "bad"

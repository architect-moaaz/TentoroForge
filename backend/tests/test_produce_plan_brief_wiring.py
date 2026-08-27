"""JT-T4 — the AUTHORITATIVE INPUTS block prepends when a brief is present.

We stub out the LLM call via ``_oneshot`` so this stays fast + deterministic.
The test asserts the prompt the planner LLM WOULD SEE contains the rendered
block. The block itself is unit-tested elsewhere; here we only pin that the
plumbing between ``produce_plan(structured_brief=…)`` and ``_oneshot(prompt)``
actually splices the two together.
"""
from __future__ import annotations

import asyncio
import pytest

from routers.generate import produce_plan
from services.structured_brief import (
    Actor, ActorOnboarding, Journey, JourneyStep, StructuredBrief,
)


def _make_brief() -> StructuredBrief:
    return StructuredBrief(
        overview="ATS",
        actors=[
            Actor(name="Recruiter", role="recruiter",
                  onboarding=ActorOnboarding(source="invited_by", invited_by="Admin")),
        ],
        user_journeys=[Journey(
            name="hire", primary_actor="Candidate",
            steps=[JourneyStep(actor="Candidate", action="apply",
                               page="/apply", outcome="applied")],
        )],
    )


class _StubOneshot:
    """Records the prompt actually passed to the LLM so the test can
    assert the block was prepended."""
    def __init__(self):
        self.captured_prompts: list[str] = []

    async def __call__(self, prompt_text: str) -> dict:
        self.captured_prompts.append(prompt_text)
        # Minimum plan that avoids the validator's noisier rules — we're
        # NOT testing validation here, just the prompt wiring.
        return {
            "module_name": "test", "data_models": [], "pages": [],
            "workflows": [], "relations": [],
        }


def test_brief_is_prepended_to_planner_prompt(tmp_path):
    stub = _StubOneshot()
    brief = _make_brief()
    asyncio.run(produce_plan(
        prompt="build me an ATS",
        output_dir=str(tmp_path),
        structured_brief=brief,
        _should_decompose=lambda p: False,  # force one-shot path
        _oneshot=stub,
    ))
    assert stub.captured_prompts, "planner LLM was never called"
    prompt_seen = stub.captured_prompts[0]
    # The block's trigger phrase MUST appear before the user's original ask.
    assert "AUTHORITATIVE INPUTS" in prompt_seen
    assert "build me an ATS" in prompt_seen
    assert prompt_seen.index("AUTHORITATIVE INPUTS") < prompt_seen.index("build me an ATS")


def test_no_brief_leaves_prompt_unchanged(tmp_path):
    """Legacy path: no brief → prompt goes to the LLM byte-unchanged.
    This is the guarantee that lets us ship without gating."""
    stub = _StubOneshot()
    asyncio.run(produce_plan(
        prompt="build me an ATS",
        output_dir=str(tmp_path),
        structured_brief=None,
        _should_decompose=lambda p: False,
        _oneshot=stub,
    ))
    assert stub.captured_prompts[0] == "build me an ATS"


def test_empty_brief_renders_nothing_and_prompt_unchanged(tmp_path):
    """A brief with no actors + no journeys is signalled by
    ``is_empty()`` — the renderer returns '' and the prompt is
    unchanged, same as if no brief were passed."""
    stub = _StubOneshot()
    asyncio.run(produce_plan(
        prompt="build me an ATS",
        output_dir=str(tmp_path),
        structured_brief=StructuredBrief(overview="just prose"),
        _should_decompose=lambda p: False,
        _oneshot=stub,
    ))
    assert stub.captured_prompts[0] == "build me an ATS"


def test_actor_role_makes_it_into_the_prompt(tmp_path):
    """One end-to-end check that the actor block reaches the LLM
    verbatim — protects against future refactors accidentally
    stripping fields between the brief and the render."""
    stub = _StubOneshot()
    asyncio.run(produce_plan(
        prompt="prompt",
        output_dir=str(tmp_path),
        structured_brief=_make_brief(),
        _should_decompose=lambda p: False,
        _oneshot=stub,
    ))
    prompt_seen = stub.captured_prompts[0]
    assert "role=recruiter" in prompt_seen
    assert "invited_by:Admin" in prompt_seen
    assert "page=/apply" in prompt_seen

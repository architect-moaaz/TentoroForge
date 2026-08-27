"""JT-T12+ — bootstrap path also injects the AUTHORITATIVE INPUTS block.

The classic discover→convert flow persists a StructuredBrief on a
DiscoverySession row; the bootstrap flow never touches that table, so
the produce_plan-side brief_lookup returns None. The fix wires the
transformer + block-prepend into run_bootstrap_stage itself. This test
locks that wiring down by intercepting the description that reaches
orchestrate_planner.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def canned_transformer_output():
    return {
        "overview": "ATS for cabin crew.",
        "domain":   "aviation.recruitment",
        "actors": [
            {"name": "Admin",     "role": "admin",
             "onboarding": {"source": "platform_org"}},
            {"name": "Recruiter", "role": "recruiter",
             "onboarding": {"source": "invited_by", "invited_by": "Admin"}},
        ],
        "user_journeys": [{
            "name": "Hire", "primary_actor": "Candidate",
            "steps": [
                {"actor": "Candidate", "action": "apply", "page": "/apply",
                 "outcome": "created"},
            ],
        }],
        "domain_terms":   ["Drive"],
        "open_questions": [],
    }


def test_bootstrap_prepends_authoritative_block(canned_transformer_output):
    """When run_bootstrap_stage enters the planning branch, it should
    (1) run the transformer, (2) render the AUTHORITATIVE INPUTS block,
    (3) prepend it to the description passed into orchestrate_planner."""
    captured: dict = {}

    async def stub_query(system, user):
        # discovery_transformer sees this call; returns a valid brief JSON
        return json.dumps(canned_transformer_output)

    async def stub_orchestrate_planner(*, description, domain_context=None,
                                        emit_fn=None, **kwargs):
        captured["description"] = description
        return SimpleNamespace(
            title="test", summary="test", entities=[], pages=[],
            workflows=[],
        )

    from services import smith_architect_wire as saw
    from services import discovery_transformer as dt

    from services import blueprint_pipeline_hooks as bph
    from services import smith_narrator as sn
    with patch.object(saw, "orchestrate_planner", stub_orchestrate_planner), \
         patch.object(bph, "record_plan", lambda **kw: None), \
         patch.object(bph, "record_discovery", lambda **kw: None), \
         patch.object(saw, "_load_blueprint_safe", lambda *_a, **_k: None), \
         patch.object(saw, "_blueprint_slice_or_empty", lambda *_a, **_k: ""), \
         patch.object(sn, "narrate", lambda **kw: "ok"), \
         patch.object(dt, "_default_query", stub_query):
        asyncio.run(saw.run_bootstrap_stage(
            project_id="proj",
            output_dir="/tmp/nowhere",
            user_message="build me an ATS",
            is_discovery_approve=True,
            is_plan_approve=False,
            pending_dossier={"user_prompt": "build me an ATS",
                             "summary": "cabin crew ATS"},
        ))

    desc = captured.get("description") or ""
    # The AUTHORITATIVE INPUTS block prefix must be present, ahead of the
    # original user description.
    assert "AUTHORITATIVE INPUTS" in desc, (
        f"expected authoritative block in orchestrate_planner description; got: {desc[:200]}"
    )
    assert desc.index("AUTHORITATIVE INPUTS") < desc.index("build me an ATS")
    # Sanity — the actual actor rows made it through
    assert "role=admin" in desc
    assert "role=recruiter" in desc
    assert "page=/apply" in desc


def test_bootstrap_falls_through_when_transformer_produces_empty():
    """When the transformer can't extract structure (LLM returns garbage),
    the bootstrap MUST still call orchestrate_planner with the unmodified
    description. Empty brief → empty block → prompt unchanged."""
    captured: dict = {}

    async def bad_query(system, user):
        return "sorry no json today"

    async def stub_orchestrate_planner(*, description, **kwargs):
        captured["description"] = description
        return SimpleNamespace(
            title="", summary="", entities=[], pages=[], workflows=[],
        )

    from services import smith_architect_wire as saw
    from services import discovery_transformer as dt

    from services import blueprint_pipeline_hooks as bph
    from services import smith_narrator as sn
    with patch.object(saw, "orchestrate_planner", stub_orchestrate_planner), \
         patch.object(bph, "record_plan", lambda **kw: None), \
         patch.object(bph, "record_discovery", lambda **kw: None), \
         patch.object(saw, "_load_blueprint_safe", lambda *_a, **_k: None), \
         patch.object(saw, "_blueprint_slice_or_empty", lambda *_a, **_k: ""), \
         patch.object(sn, "narrate", lambda **kw: "ok"), \
         patch.object(dt, "_default_query", bad_query):
        asyncio.run(saw.run_bootstrap_stage(
            project_id="proj",
            output_dir="/tmp/nowhere",
            user_message="build",
            is_discovery_approve=True,
            is_plan_approve=False,
            pending_dossier={"user_prompt": "build"},
        ))

    # No AUTHORITATIVE INPUTS block — legacy prompt intact
    assert "AUTHORITATIVE INPUTS" not in (captured.get("description") or "")
    assert captured.get("description") == "build"

"""Phase C — bootstrap wire tests.

Locks the state-machine behavior of `run_bootstrap_stage`:

  * fresh project + no signal → discovery stage
  * [APPROVE_DISCOVERY] + saved dossier → planning stage
  * [APPROVE_PLAN] → generation stage (caller runs the pipeline)
  * exception in Phase B → stage="not_enabled" (caller falls back)

Phase B orchestrators are mocked so tests never hit the LLM.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services.narrator_artifacts import (
    DiscoveryArtifact, PlannerArtifact, ProposedEntitySpec,
    ProposedWorkflow, ProposedPage,
)
from services.smith_architect_wire import (
    BootstrapStageResult,
    run_bootstrap_stage,
)


def _stub_discovery_artifact() -> DiscoveryArtifact:
    return DiscoveryArtifact.from_dict({
        "domain_name": "Cabin Crew ATS",
        "actors": ["recruiter", "candidate"],
        "verbs": ["apply", "schedule"],
        "distinctive_shape": "kanban pipeline",
        "proposed_entities": [{"name": "Candidate", "why": "the applicant"}],
        "open_questions": [],
        "confidence": 0.9,
    })


def _stub_plan_artifact() -> PlannerArtifact:
    return PlannerArtifact(
        entities=[ProposedEntitySpec(
            name="Candidate", table="candidates", purpose="applicant",
            key_fields=["email"], why_shaped_this_way="MVP",
        )],
        workflows=[ProposedWorkflow(
            name="CreateCandidate", purpose="capture applicant",
            trigger="form_submit", why="manual add",
        )],
        pages=[ProposedPage(
            route="/candidates", schema_path="src/schemas/candidates/index.json",
            role="list",
        )],
    )


# --------------------------------------------------------------------------- #
# State-machine branches
# --------------------------------------------------------------------------- #

def test_first_message_no_signal_runs_discovery(tmp_path, monkeypatch):
    """No dossier + no approval signal ⇒ discovery stage."""
    async def _fake_discovery(**kwargs):
        return _stub_discovery_artifact()
    monkeypatch.setattr(
        "services.smith_architect_wire.orchestrate_discovery",
        _fake_discovery,
    )

    result = asyncio.run(run_bootstrap_stage(
        project_id="p1", output_dir=str(tmp_path),
        user_message="Build me an ATS for cabin crew recruitment",
        is_discovery_approve=False, is_plan_approve=False,
        pending_dossier=None,
    ))
    assert result.stage == "discovery"
    assert result.dossier is not None
    assert result.dossier["domain_name"] == "Cabin Crew ATS"
    assert result.dossier["user_prompt"].startswith("Build me an ATS")
    assert "Cabin Crew ATS" in result.narrator


def test_approve_discovery_with_dossier_runs_planning(tmp_path, monkeypatch):
    """[APPROVE_DISCOVERY] + saved dossier ⇒ planning stage."""
    async def _fake_planner(**kwargs):
        return _stub_plan_artifact()
    monkeypatch.setattr(
        "services.smith_architect_wire.orchestrate_planner",
        _fake_planner,
    )

    result = asyncio.run(run_bootstrap_stage(
        project_id="p1", output_dir=str(tmp_path),
        user_message="[APPROVE_DISCOVERY]",
        is_discovery_approve=True, is_plan_approve=False,
        pending_dossier={"user_prompt": "Build me an ATS", "domain_name": "ATS"},
    ))
    assert result.stage == "planning"
    assert result.plan is not None
    assert result.plan["models"][0]["name"] == "Candidate"
    assert "entit" in result.narrator.lower()  # narrator mentions entities count


def test_approve_plan_hands_off_to_generator(tmp_path):
    """[APPROVE_PLAN] ⇒ stage='generation'; caller runs the pipeline.
    No LLM call inside this branch."""
    result = asyncio.run(run_bootstrap_stage(
        project_id="p1", output_dir=str(tmp_path),
        user_message="[APPROVE_PLAN]",
        is_discovery_approve=False, is_plan_approve=True,
        pending_dossier=None,
    ))
    assert result.stage == "generation"
    assert "hand" in result.narrator.lower() or "generat" in result.narrator.lower()
    assert result.dossier is None
    assert result.plan is None


def test_orchestrator_exception_becomes_not_enabled(tmp_path, monkeypatch):
    """If Phase B raises, the wire converts to 'not_enabled' with
    the error message so the caller falls back cleanly."""
    async def _boom(**kwargs):
        raise RuntimeError("simulated LLM crash")
    monkeypatch.setattr(
        "services.smith_architect_wire.orchestrate_discovery",
        _boom,
    )

    result = asyncio.run(run_bootstrap_stage(
        project_id="p1", output_dir=str(tmp_path),
        user_message="build",
        is_discovery_approve=False, is_plan_approve=False,
        pending_dossier=None,
    ))
    assert result.stage == "not_enabled"
    assert result.error and "simulated LLM crash" in result.error


def test_discovery_writes_blueprint_domain(tmp_path, monkeypatch):
    """Phase A hook fires — Blueprint records the domain."""
    from services.smith_blueprint import Blueprint

    async def _fake_discovery(**kwargs):
        return _stub_discovery_artifact()
    monkeypatch.setattr(
        "services.smith_architect_wire.orchestrate_discovery",
        _fake_discovery,
    )

    asyncio.run(run_bootstrap_stage(
        project_id="p1", output_dir=str(tmp_path),
        user_message="build the ATS",
        is_discovery_approve=False, is_plan_approve=False,
        pending_dossier=None,
    ))
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.domain is not None
    assert bp.domain["name"] == "Cabin Crew ATS"


def test_planning_writes_blueprint_entities(tmp_path, monkeypatch):
    from services.smith_blueprint import Blueprint

    async def _fake_planner(**kwargs):
        return _stub_plan_artifact()
    monkeypatch.setattr(
        "services.smith_architect_wire.orchestrate_planner",
        _fake_planner,
    )

    asyncio.run(run_bootstrap_stage(
        project_id="p1", output_dir=str(tmp_path),
        user_message="[APPROVE_DISCOVERY]",
        is_discovery_approve=True, is_plan_approve=False,
        pending_dossier={"user_prompt": "build", "domain_name": "ATS"},
    ))
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    entity_names = {e["name"] for e in bp.entities}
    assert entity_names == {"Candidate"}

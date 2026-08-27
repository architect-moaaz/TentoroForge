"""Phase D — replan seam tests.

The replan seam is invoked when the user asks for a capability that
can't be built by an in-place edit (e.g. "add authentication",
"add payments", "add role-based access"). It runs the planner with
the existing blueprint as prior_plan + the user's new ask, then
saves the produced plan via the Phase A `record_plan` hook.

It does NOT trigger regeneration — that's a separate step the user
initiates. The seam returns an IterationMove summarizing what changed
so the SmithSession can narrate it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.narrator_artifacts import (
    PlannerArtifact, ProposedEntitySpec, ProposedWorkflow, ProposedPage,
)
from services.smith_blueprint import Blueprint


def _stub_plan_artifact() -> PlannerArtifact:
    return PlannerArtifact(
        entities=[
            ProposedEntitySpec(
                name="User", table="users", purpose="auth subject",
                key_fields=["email", "password_hash"],
                why_shaped_this_way="auth requirement",
            ),
            ProposedEntitySpec(
                name="Candidate", table="candidates", purpose="applicant",
                key_fields=["email"], why_shaped_this_way="pre-existing",
            ),
        ],
        workflows=[
            ProposedWorkflow(
                name="Login", purpose="authenticate a user",
                trigger="form_submit", why="new auth capability",
            ),
        ],
        pages=[
            ProposedPage(
                route="/login", schema_path="src/schemas/login.json",
                role="form",
            ),
        ],
    )


def _seed_bp(tmp_path, project_id: str = "pX") -> Blueprint:
    """Seed a blueprint with pre-existing structure so the seam thinks
    it's iterating on a real app."""
    bp = Blueprint.load(project_id=project_id, output_dir=str(tmp_path))
    bp.domain = {"name": "ATS"}
    bp.entities = [{"name": "Candidate", "table": "candidates"}]
    bp.pages = [{"route": "/candidates", "role": "list"}]
    bp.save()
    return bp


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #

def test_replan_seam_calls_planner_and_records_new_plan(tmp_path, monkeypatch):
    """The seam invokes orchestrate_planner and hands the resulting
    plan to record_plan (Phase A hook). A file appears on disk."""
    from services import smith_architect_wire as wire

    _seed_bp(tmp_path)

    async def _fake_planner(**kwargs):
        return _stub_plan_artifact()

    monkeypatch.setattr(wire, "orchestrate_planner", _fake_planner)

    understanding = {
        "screen": "app-wide",
        "desired_behavior": "add authentication with login page",
        "target_file": "",
        "wants_replan": True,
    }
    move = wire._seam_replan(understanding, str(tmp_path), project_id="pX")

    assert move is not None
    assert move.move_name.startswith("replan(")
    # Blueprint has entities merged (Candidate pre-existing + User new).
    bp = Blueprint.load(project_id="pX", output_dir=str(tmp_path))
    names = {e["name"] for e in bp.entities}
    assert "User" in names
    assert "Candidate" in names  # pre-existing preserved


def test_replan_seam_touched_paths_names_the_plan(tmp_path, monkeypatch):
    from services import smith_architect_wire as wire
    _seed_bp(tmp_path)

    async def _fake_planner(**kwargs):
        return _stub_plan_artifact()
    monkeypatch.setattr(wire, "orchestrate_planner", _fake_planner)

    move = wire._seam_replan(
        {"desired_behavior": "add auth", "wants_replan": True},
        str(tmp_path), project_id="pX",
    )
    assert move is not None
    assert any("plan" in p.lower() or "blueprint" in p.lower()
               for p in move.touched_paths)


def test_replan_seam_narrator_summary_names_the_change(tmp_path, monkeypatch):
    """move_name mentions the count of new entities/workflows/pages
    so Smith can narrate what happened."""
    from services import smith_architect_wire as wire
    _seed_bp(tmp_path)

    async def _fake_planner(**kwargs):
        return _stub_plan_artifact()
    monkeypatch.setattr(wire, "orchestrate_planner", _fake_planner)

    move = wire._seam_replan(
        {"desired_behavior": "add auth", "wants_replan": True},
        str(tmp_path), project_id="pX",
    )
    assert move is not None
    # Names one of the added things.
    name_l = move.move_name.lower()
    assert "user" in name_l or "login" in name_l or "entit" in name_l or "workflow" in name_l


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #

def test_replan_seam_returns_none_on_planner_failure(tmp_path, monkeypatch):
    from services import smith_architect_wire as wire
    _seed_bp(tmp_path)

    async def _boom(**kwargs):
        raise RuntimeError("planner crashed")
    monkeypatch.setattr(wire, "orchestrate_planner", _boom)

    move = wire._seam_replan(
        {"desired_behavior": "add auth", "wants_replan": True},
        str(tmp_path), project_id="pX",
    )
    assert move is None


def test_replan_seam_returns_none_when_planner_produces_empty(tmp_path, monkeypatch):
    from services import smith_architect_wire as wire
    _seed_bp(tmp_path)

    async def _empty(**kwargs):
        return PlannerArtifact(entities=[], workflows=[], pages=[])
    monkeypatch.setattr(wire, "orchestrate_planner", _empty)

    move = wire._seam_replan(
        {"desired_behavior": "add auth", "wants_replan": True},
        str(tmp_path), project_id="pX",
    )
    assert move is None

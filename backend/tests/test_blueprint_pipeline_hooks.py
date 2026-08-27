"""Blueprint pipeline hooks — Phase A of the "adhere to the full
Smith-as-architect spec" work.

Spec §6.3: Discovery / Planner / Generator populate the Blueprint as
they produce artifacts, so Smith's later claim "I authored this app"
is literal — not a post-hoc backfill from a registry snapshot.

These are pure functions: given a dict from the agent, they update
the Blueprint on disk. Every hook wraps its work in try/except so a
Blueprint write failure NEVER breaks generation (the log gets the
exception; the pipeline continues).

Tests exercise the three hooks with agent-shaped dicts, confirm
Blueprint gets populated, and confirm that a corrupt input is
survivable (no crash, blueprint unchanged).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_blueprint import Blueprint
from services.blueprint_pipeline_hooks import (
    record_discovery,
    record_plan,
    record_generation_complete,
)


# --------------------------------------------------------------------------- #
# record_discovery
# --------------------------------------------------------------------------- #

def test_record_discovery_sets_domain_from_dossier(tmp_path: Path):
    dossier = {
        "domain_name": "Cabin Crew ATS",
        "actors": ["recruiter", "candidate"],
        "verbs": ["apply", "schedule"],
        "distinctive_shape": "kanban pipeline",
        "user_prompt": "airline recruitment ATS",
    }
    record_discovery(output_dir=str(tmp_path), project_id="p1", dossier=dossier)

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.domain is not None
    assert bp.domain["name"] == "Cabin Crew ATS"
    assert bp.domain["primary_actors"] == ["recruiter", "candidate"]
    assert bp.domain["core_verbs"] == ["apply", "schedule"]


def test_record_discovery_appends_change_log_with_discovery_source(tmp_path: Path):
    record_discovery(
        output_dir=str(tmp_path), project_id="p1",
        dossier={"domain_name": "X", "actors": [], "verbs": []},
    )
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.change_log
    entry = bp.change_log[-1]
    assert entry["source"] == "smith"
    assert "discovery" in entry["smith_move"].lower()


def test_record_discovery_captures_open_questions_as_design_decisions(tmp_path: Path):
    """Open questions in the dossier become design_decisions with a
    'pending' topic prefix so Smith can revisit them later."""
    dossier = {
        "domain_name": "ATS",
        "actors": [],
        "verbs": [],
        "open_questions": ["how are assessments scheduled?"],
    }
    record_discovery(output_dir=str(tmp_path), project_id="p1", dossier=dossier)
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.design_decisions
    d = bp.design_decisions[-1]
    assert "assessments" in d["choice"].lower() or "assessments" in d["why"].lower()


def test_record_discovery_survives_missing_fields(tmp_path: Path):
    """A dossier without domain_name should not crash the pipeline —
    the hook logs and returns, blueprint stays as-is."""
    record_discovery(output_dir=str(tmp_path), project_id="p1", dossier={})
    # Should not raise; blueprint file may or may not exist.
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.domain is None


# --------------------------------------------------------------------------- #
# record_plan
# --------------------------------------------------------------------------- #

def test_record_plan_adds_entities_workflows_pages(tmp_path: Path):
    plan = {
        "models": [
            {"name": "Candidate", "fields": [{"name": "email"}, {"name": "firstName"}]},
            {"name": "Assessor", "fields": [{"name": "email"}]},
        ],
        "workflows": [
            {"name": "CreateCandidate", "trigger": {"type": "form_submit"}},
        ],
        "pages": [
            {"route": "/candidates", "type": "list"},
            {"route": "/candidates/new", "type": "form"},
        ],
    }
    record_plan(output_dir=str(tmp_path), project_id="p1", plan=plan)

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    entity_names = {e["name"] for e in bp.entities}
    assert entity_names == {"Candidate", "Assessor"}
    workflow_names = {w["name"] for w in bp.workflows}
    assert workflow_names == {"CreateCandidate"}
    routes = {p["route"] for p in bp.pages}
    assert routes == {"/candidates", "/candidates/new"}


def test_record_plan_marks_entries_as_smith_authored(tmp_path: Path):
    """Distinguishes Smith-authored entries from backfilled ones: the
    `why_shaped_this_way` field should NOT contain the 'backfilled'
    marker that the backfill script uses."""
    plan = {
        "models": [{"name": "Candidate", "fields": [{"name": "email"}]}],
        "pages": [], "workflows": [],
    }
    record_plan(output_dir=str(tmp_path), project_id="p1", plan=plan)
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    entity = bp.entities[0]
    assert "backfilled" not in entity["why_shaped_this_way"].lower()
    assert entity["why_shaped_this_way"]  # non-empty


def test_record_plan_survives_empty_plan(tmp_path: Path):
    record_plan(output_dir=str(tmp_path), project_id="p1", plan={})
    # Blueprint may not even exist after this — no crash is the contract.
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.entities == []


def test_record_plan_is_idempotent_for_the_same_entity(tmp_path: Path):
    """If the planner runs twice (revise flow), we don't want duplicate
    entities in the blueprint. Second call with the same entity name
    updates in place rather than appending."""
    plan = {"models": [{"name": "Candidate", "fields": [{"name": "email"}]}]}
    record_plan(output_dir=str(tmp_path), project_id="p1", plan=plan)
    record_plan(output_dir=str(tmp_path), project_id="p1", plan=plan)

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    names = [e["name"] for e in bp.entities]
    assert names.count("Candidate") == 1


# --------------------------------------------------------------------------- #
# record_generation_complete
# --------------------------------------------------------------------------- #

def test_record_generation_complete_writes_change_log_entry(tmp_path: Path):
    record_generation_complete(
        output_dir=str(tmp_path), project_id="p1",
        files=["src/db/schema.ts", "src/schemas/candidates/index.json"],
        user_ask="Build me an ATS for cabin crew",
    )
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.change_log
    entry = bp.change_log[-1]
    assert entry["source"] == "smith"
    assert "generation" in entry["smith_move"].lower()
    assert "2 file" in entry["diff_summary"]
    assert entry["user_ask"] == "Build me an ATS for cabin crew"


def test_record_generation_complete_bounded_file_preview(tmp_path: Path):
    """A generation touches ~50-200 files; the change_log summary must
    stay compact, not dump every path."""
    many_files = [f"src/schemas/p{i}.json" for i in range(50)]
    record_generation_complete(
        output_dir=str(tmp_path), project_id="p1",
        files=many_files, user_ask="build",
    )
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    summary = bp.change_log[-1]["diff_summary"]
    assert "50 file" in summary
    # No path dump — count only.
    assert summary.count("src/schemas/") <= 6


def test_record_generation_complete_survives_write_error(monkeypatch, tmp_path: Path):
    """A hook failure never breaks the pipeline — the try/except swallows
    it and logs, and the caller keeps going."""
    def _bad_save(self):
        raise OSError("simulated disk-full")
    monkeypatch.setattr(Blueprint, "save", _bad_save)
    # Should not raise.
    record_generation_complete(
        output_dir=str(tmp_path), project_id="p1",
        files=["a.json"], user_ask="x",
    )

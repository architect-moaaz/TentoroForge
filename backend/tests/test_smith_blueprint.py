"""Smith Blueprint — the per-project persistent memory that lets Smith
reason as the architect of an app he built.

The Blueprint lives in ``<output_dir>/.forge/blueprint.json`` inside
the generated app's git repo, so it versions alongside the code and
travels with the project.

Contract tests target the operations Smith's future code paths will
depend on:
  * ``load`` returns an empty blueprint for a project that has none
  * ``load`` returns the persisted blueprint for one that does
  * writes are atomic (crash mid-write leaves the file intact)
  * ``append_change_log`` grows the log without touching other sections
  * ``add_entity`` / ``add_page`` / ``add_workflow`` / ``set_domain`` /
    ``add_design_decision`` each land in the right section
  * ``fingerprint`` returns a stable hash of the content (drives the
    staleness check in §6.6 of the spec)
  * unknown-shape files load without crashing (forwards-compat)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_blueprint import (
    Blueprint,
    BlueprintPath,
)


# --------------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------------- #

def test_blueprint_path_lives_in_dot_forge_directory(tmp_path: Path):
    p = BlueprintPath(str(tmp_path))
    assert p.file.parent == tmp_path / ".forge"
    assert p.file.name == "blueprint.json"


# --------------------------------------------------------------------------- #
# load — first-time + round-trip
# --------------------------------------------------------------------------- #

def test_load_returns_empty_blueprint_when_file_missing(tmp_path: Path):
    """A project that Smith hasn't built yet has no blueprint. Load
    returns a well-shaped empty one instead of crashing."""
    bp = Blueprint.load(project_id="pXYZ", output_dir=str(tmp_path))
    assert bp.project_id == "pXYZ"
    assert bp.domain is None
    assert bp.entities == []
    assert bp.workflows == []
    assert bp.pages == []
    assert bp.design_decisions == []
    assert bp.change_log == []


def test_load_round_trips_a_saved_blueprint(tmp_path: Path):
    """Save, then load — every field round-trips byte-identical."""
    bp = Blueprint.load(project_id="pATS", output_dir=str(tmp_path))
    bp.set_domain(
        name="Cabin Crew ATS",
        primary_actors=["recruiter", "candidate"],
        core_verbs=["apply", "schedule"],
        distinctive_shape="kanban pipeline",
        why="user asked for an airline cabin-crew recruitment system",
    )
    bp.add_entity(
        name="Candidate",
        table="candidates",
        purpose="the person applying",
        key_fields=["fullName", "email", "latestCvAttachmentId"],
        why_shaped_this_way="CV required to enter the pipeline",
    )
    bp.add_page(
        route="/candidates/new",
        schema_path="src/schemas/candidates/new.json",
        role="primary intake — must include CV upload",
        notable_choices=[{"choice": "FileUpload for CV", "why": "PDF upload flow"}],
    )
    bp.save()

    loaded = Blueprint.load(project_id="pATS", output_dir=str(tmp_path))
    assert loaded.domain is not None
    assert loaded.domain["name"] == "Cabin Crew ATS"
    assert loaded.domain["primary_actors"] == ["recruiter", "candidate"]
    assert len(loaded.entities) == 1
    assert loaded.entities[0]["name"] == "Candidate"
    assert loaded.pages[0]["route"] == "/candidates/new"


# --------------------------------------------------------------------------- #
# Atomic write — partial write cannot corrupt an existing blueprint
# --------------------------------------------------------------------------- #

def test_save_is_atomic_via_temp_file_and_replace(tmp_path: Path, monkeypatch):
    """If ``os.replace`` never runs (simulating a crash after the temp
    file was written), the original blueprint file must be untouched."""
    bp = Blueprint.load(project_id="pATS", output_dir=str(tmp_path))
    bp.set_domain(name="v1", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()

    original = (tmp_path / ".forge" / "blueprint.json").read_text()

    bp.set_domain(name="v2", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")

    import os
    real_replace = os.replace

    def _boom(src, dst):
        raise RuntimeError("simulated crash between write and replace")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(RuntimeError):
        bp.save()
    monkeypatch.setattr(os, "replace", real_replace)

    # The on-disk file is still v1; the crashed write left no dangling state
    # the next reader can see.
    assert (tmp_path / ".forge" / "blueprint.json").read_text() == original


# --------------------------------------------------------------------------- #
# append_change_log — the growing history of Smith moves
# --------------------------------------------------------------------------- #

def test_append_change_log_grows_the_log_and_preserves_order(tmp_path: Path):
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.append_change_log(
        at="2026-07-17 12:00",
        user_ask="add a Candidate entity",
        smith_move="add_entity(Candidate, …)",
        diff_summary="src/db/schema.ts | 12 +",
        verified_by=["git diff", "guard delta green"],
        why="user asked for it during discovery",
    )
    bp.append_change_log(
        at="2026-07-17 12:05",
        user_ask="In Add Candidate, upload CV is the drop down",
        smith_move="edit_page(candidates/new.json)",
        diff_summary="Select → FileUpload on latestCvAttachmentId",
        verified_by=["git diff", "form re-render probe"],
        why="label says Upload; picker was wrong from the start",
    )
    bp.save()

    loaded = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert len(loaded.change_log) == 2
    assert loaded.change_log[0]["user_ask"] == "add a Candidate entity"
    assert loaded.change_log[1]["smith_move"].startswith("edit_page")


def test_append_change_log_defaults_source_to_smith(tmp_path: Path):
    """Editor / external / self-heal writers pass ``source=`` explicitly.
    Anyone who forgets is Smith by default (the common case)."""
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.append_change_log(
        at="2026-07-17 12:00", user_ask="x", smith_move="y",
        diff_summary="z", verified_by=[], why="w",
    )
    assert bp.change_log[0]["source"] == "smith"


def test_append_change_log_records_editor_source_when_asked(tmp_path: Path):
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.append_change_log(
        at="2026-07-17 13:00", user_ask="",
        smith_move="editor: renamed field firstName → givenName",
        diff_summary="src/schemas/candidates/new.json | 2 +",
        verified_by=["editor save-handler"],
        why="user renamed in the visual editor",
        source="editor",
    )
    assert bp.change_log[0]["source"] == "editor"


# --------------------------------------------------------------------------- #
# Additive section writers
# --------------------------------------------------------------------------- #

def test_add_entity_appends_and_survives_reload(tmp_path: Path):
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.add_entity(
        name="Candidate", table="candidates",
        purpose="applicants", key_fields=["email"],
        why_shaped_this_way="MVP shape",
    )
    bp.add_entity(
        name="Assessor", table="assessors",
        purpose="interviewers", key_fields=["email"],
        why_shaped_this_way="needed to schedule",
    )
    bp.save()

    reloaded = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert [e["name"] for e in reloaded.entities] == ["Candidate", "Assessor"]


def test_add_workflow_and_add_page_persist(tmp_path: Path):
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.add_workflow(
        name="CreateCandidate", purpose="capture applicant with CV",
        trigger="CandidateCreateForm submit",
        why="recruiters add manually before bulk import exists",
    )
    bp.add_page(
        route="/candidates/new",
        schema_path="src/schemas/candidates/new.json",
        role="primary intake",
        notable_choices=[],
    )
    bp.save()

    reloaded = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert reloaded.workflows[0]["name"] == "CreateCandidate"
    assert reloaded.pages[0]["route"] == "/candidates/new"


def test_add_design_decision_records_authored_at_and_why(tmp_path: Path):
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.add_design_decision(
        topic="auth model",
        choice="email/password + role gating",
        why="MVP; SSO deferred",
        authored_at="2026-07-15 during discovery",
    )
    bp.save()

    reloaded = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    d = reloaded.design_decisions[0]
    assert d["topic"] == "auth model"
    assert d["authored_at"] == "2026-07-15 during discovery"


# --------------------------------------------------------------------------- #
# fingerprint — drives staleness detection in §6.6
# --------------------------------------------------------------------------- #

def test_fingerprint_changes_when_content_changes(tmp_path: Path):
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    fp0 = bp.fingerprint()
    bp.add_entity(name="X", table="xs", purpose="", key_fields=[], why_shaped_this_way="")
    fp1 = bp.fingerprint()
    assert fp0 != fp1


def test_fingerprint_stable_across_reload(tmp_path: Path):
    """Saving and reloading the same content yields the same fingerprint —
    the check §6.6 uses to detect external edits."""
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.add_entity(name="X", table="xs", purpose="", key_fields=[], why_shaped_this_way="")
    bp.save()
    fp_before = bp.fingerprint()

    reloaded = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert reloaded.fingerprint() == fp_before


# --------------------------------------------------------------------------- #
# Forwards-compat — unknown fields don't crash the loader
# --------------------------------------------------------------------------- #

def test_load_tolerates_unknown_top_level_fields(tmp_path: Path):
    """Someone (a later slice, an editor version) may add fields we don't
    know about yet. Loading must not crash; unknown fields are preserved
    on save so we don't corrupt them."""
    forge = tmp_path / ".forge"
    forge.mkdir()
    (forge / "blueprint.json").write_text(json.dumps({
        "project_id": "p1",
        "domain": None,
        "entities": [],
        "workflows": [],
        "pages": [],
        "design_decisions": [],
        "change_log": [],
        "future_field": {"invented_later": True},
    }))
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.save()

    reloaded_raw = json.loads((forge / "blueprint.json").read_text())
    assert reloaded_raw.get("future_field") == {"invented_later": True}

"""AM-1 — build_app_map: pure extractor over a generated app's contracts.

Uses the bpxr6hsv fixture app (real generated app on disk) copied into a
tmp_path so the tests are hermetic — they don't depend on future edits
to the source app.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from services.app_map import build_app_map


_FIXTURE_SRC = Path("/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv")


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    """Copy the bpxr6hsv contracts + src/schemas into tmp_path.

    We copy the minimum surface build_app_map needs — no runtime code,
    no db, no vendored packages — so the fixture stays small and the
    tests fail loudly if the extractor starts reading anything else.
    """
    if not _FIXTURE_SRC.exists():
        pytest.skip("bpxr6hsv fixture app not present")
    (tmp_path / "contracts").mkdir()
    for name in (
        "resource-registry.json",
        "action-contract.json",
        "generation-dossier.json",
    ):
        shutil.copy(_FIXTURE_SRC / "contracts" / name, tmp_path / "contracts" / name)
    shutil.copy(_FIXTURE_SRC / "registry.json", tmp_path / "registry.json")
    shutil.copytree(_FIXTURE_SRC / "src" / "schemas", tmp_path / "src" / "schemas")
    return tmp_path


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #

def test_all_seven_entities_extracted(app_root):
    m = build_app_map(str(app_root))
    assert set(m["entities"].keys()) == {
        "Application", "CVUpload", "Candidate", "CommunicationLog",
        "Interview", "RecruitmentDrive", "User",
    }


def test_entity_metadata_shape(app_root):
    m = build_app_map(str(app_root))
    cand = m["entities"]["Candidate"]
    assert cand["table"] == "candidates"
    assert cand["slug"] == "candidates"
    assert cand["columns_count"] == 24


def test_candidate_fk_out_to_cvupload(app_root):
    m = build_app_map(str(app_root))
    outs = m["entities"]["Candidate"]["fks_out"]
    assert any(fk["col"] == "cvUploadId" and fk["target_entity"] == "CVUpload"
               for fk in outs)


def test_interview_has_four_outbound_fks(app_root):
    m = build_app_map(str(app_root))
    outs = m["entities"]["Interview"]["fks_out"]
    assert len(outs) == 4
    cols = {fk["col"] for fk in outs}
    assert cols == {"applicationId", "candidateId", "recruitmentDriveId", "interviewerId"}


def test_user_is_a_sink_no_outbound(app_root):
    m = build_app_map(str(app_root))
    assert m["entities"]["User"]["fks_out"] == []


def test_user_has_four_inbound_fks(app_root):
    m = build_app_map(str(app_root))
    ins = m["entities"]["User"]["fks_in"]
    sources = {fk["from_entity"] for fk in ins}
    assert sources == {"Application", "Interview", "RecruitmentDrive", "CommunicationLog"}


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

def test_all_pages_present(app_root):
    m = build_app_map(str(app_root))
    routes = {p["route"] for p in m["pages"]}
    # Ensure the well-known routes for Candidate/Interview/Drive show up.
    assert "/candidates" in routes
    assert "/candidates/new" in routes
    assert "/candidates/[id]" in routes
    assert "/candidates/:id/edit" in routes


def test_page_archetype_inference(app_root):
    m = build_app_map(str(app_root))
    by_route = {p["route"]: p for p in m["pages"]}
    assert by_route["/candidates/new"]["archetype"] == "form"
    assert by_route["/candidates/:id/edit"]["archetype"] == "form"
    assert by_route["/candidates/[id]"]["archetype"] == "detail"
    assert by_route["/candidates"]["archetype"] == "list"


def test_page_entity_binding(app_root):
    m = build_app_map(str(app_root))
    by_route = {p["route"]: p for p in m["pages"]}
    assert by_route["/candidates/new"]["entity"] == "Candidate"
    assert by_route["/candidates/[id]"]["entity"] == "Candidate"


def test_page_form_submit_workflow_resolved(app_root):
    m = build_app_map(str(app_root))
    by_route = {p["route"]: p for p in m["pages"]}
    assert by_route["/candidates/new"]["form_submit_workflow"] == "create-candidate"
    assert by_route["/candidates/:id/edit"]["form_submit_workflow"] == "update-candidate"
    # A list page has no form submit.
    assert by_route["/candidates"]["form_submit_workflow"] is None


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #

def test_all_expected_workflows_present(app_root):
    m = build_app_map(str(app_root))
    wfs = m["workflows"]
    # Auto CRUD — one create + one update per entity (except CVUpload which
    # this app doesn't expose a CRUD workflow for).
    assert "create-candidate" in wfs
    assert "update-candidate" in wfs
    # Domain workflows — hand-authored by the planner.
    assert "ShortlistingWorkflow" in wfs
    assert "InterviewSchedulingWorkflow" in wfs
    assert "InterviewFeedbackWorkflow" in wfs


def test_workflow_kind_and_op(app_root):
    m = build_app_map(str(app_root))
    wfs = m["workflows"]
    assert wfs["create-candidate"]["kind"] == "auto-crud"
    assert wfs["create-candidate"]["op"] == "create"
    assert wfs["update-candidate"]["op"] == "update"
    assert wfs["ShortlistingWorkflow"]["kind"] == "domain"


def test_workflow_target_entity_resolved(app_root):
    m = build_app_map(str(app_root))
    wfs = m["workflows"]
    assert wfs["create-candidate"]["target"] == "Candidate"
    # Domain workflow target comes from interactions.targetEntityId
    assert wfs["InterviewSchedulingWorkflow"]["target"] == "Interview"


# --------------------------------------------------------------------------- #
# Intent
# --------------------------------------------------------------------------- #

def test_intent_carries_prompt_first_line(app_root):
    m = build_app_map(str(app_root))
    intent = m["intent"]
    assert isinstance(intent, str)
    assert "Applicant Tracking System" in intent
    # Single line (whitespace collapsed).
    assert "\n" not in intent


# --------------------------------------------------------------------------- #
# Graceful degradation on missing files
# --------------------------------------------------------------------------- #

def test_missing_contracts_returns_empty_map(tmp_path):
    m = build_app_map(str(tmp_path))
    assert m == {"intent": "", "entities": {}, "pages": [], "workflows": {}}


def test_missing_dossier_still_extracts_entities(app_root):
    (app_root / "contracts" / "generation-dossier.json").unlink()
    m = build_app_map(str(app_root))
    assert m["intent"] == ""
    assert len(m["entities"]) == 7  # entities came from resource-registry

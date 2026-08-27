"""Tests for the symptom→diagnosis agent (agents/fix_diagnoser).

No real model is ever called: the capable-patch step goes through an injected
`query_fn` that returns canned structured output. The cheap-locate step is
purely deterministic and unit-tested WITHOUT any model at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.fix_diagnoser import (
    cheap_locate,
    diagnose,
    parse_error,
    validate_workflow_patch,
)


# --------------------------------------------------------------------------- #
# Fixture — a compact mc2xgclv-shaped output dir on disk.
# --------------------------------------------------------------------------- #

_REGISTRY = {
    "entities": {
        "Assessment": {
            "id": "assessment",
            "name": "Assessment",
            "slug": "assessments",
            "table": "assessments",
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "applicationId", "type": "uuid", "fk": "application"},
                {"name": "candidateId", "type": "uuid", "fk": "candidate"},
                {"name": "assessmentType", "type": "varchar"},
                {"name": "scheduledAt", "type": "timestamp"},
                {"name": "location", "type": "varchar"},
                {"name": "assignedAssessorId", "type": "uuid"},
                {"name": "status", "type": "varchar"},
            ],
        },
        "Candidate": {
            "id": "candidate",
            "name": "Candidate",
            "slug": "candidates",
            "table": "candidates",
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "fullName", "type": "varchar"},
                {"name": "email", "type": "varchar"},
                {"name": "cvUrl", "type": "text"},
                {"name": "status", "type": "varchar"},
            ],
        },
    },
    "interactions": [],
    "relationships": [],
    "roles": [],
    "version": 1,
}


def _assessment_workflow() -> dict:
    """The real assessmentschedulingworkflow shape with the two known bugs:
    candidateId=CURRENT_TIMESTAMP (uuid) and status=<node label>."""
    node = {
        "id": "create_assessment_record",
        "type": "action",
        "data": {
            "label": "Create Assessment Record",
            "nodeType": "action",
            "config": {
                "table": "assessments",
                "actionType": "db_insert",
                "values": {
                    "applicationId": "{{applicationId}}",
                    "candidateId": "CURRENT_TIMESTAMP",
                    "assessmentType": "{{assessmentType}}",
                    "scheduledAt": "CURRENT_TIMESTAMP",
                    "location": "{{location}}",
                    "assignedAssessorId": "{{assignedAssessorId}}",
                    "status": "Create Assessment Record",
                },
                "nodeType": "action",
            },
        },
    }
    return {
        "id": "assessmentschedulingworkflow",
        "name": "AssessmentSchedulingWorkflow",
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [node],
            "edges": [],
        },
    }


def _create_assessment_workflow() -> dict:
    """A generic CreateAssessment CRUD workflow — also a db_insert into
    `assessments`, but not the domain scheduling workflow."""
    return {
        "id": "CreateAssessment",
        "name": "CreateAssessment",
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [
                {
                    "id": "insert_assessment",
                    "type": "action",
                    "data": {
                        "label": "Insert Assessment",
                        "config": {
                            "table": "assessments",
                            "actionType": "db_insert",
                            "values": {"candidateId": "{{candidateId}}"},
                        },
                    },
                }
            ],
            "edges": [],
        },
    }


def _candidate_new_form() -> dict:
    """Candidate create form whose cvUrl field is a plain Input (the bug: it
    should be a FileUpload so users can actually upload a CV)."""
    return {
        "schemaVersion": 1,
        "id": "candidates-new",
        "route": "/candidates/new",
        "root": {
            "type": "Form",
            "props": {"dataSource": "candidates"},
            "children": [
                {"type": "Input", "props": {"name": "fullName", "label": "Full Name"}},
                {"type": "Input", "props": {"name": "email", "label": "Email"}},
                {"type": "Input", "props": {"name": "cvUrl", "label": "CV Upload (URL)"}},
                {"type": "Select", "props": {"name": "status", "label": "Status"}},
            ],
        },
    }


@pytest.fixture()
def app_dir(tmp_path: Path) -> Path:
    out = tmp_path / "app"
    (out / "contracts").mkdir(parents=True)
    (out / "workflows").mkdir(parents=True)
    (out / "src" / "schemas" / "candidates").mkdir(parents=True)

    (out / "contracts" / "resource-registry.json").write_text(json.dumps(_REGISTRY))
    (out / "workflows" / "assessmentschedulingworkflow.json").write_text(
        json.dumps(_assessment_workflow())
    )
    (out / "workflows" / "CreateAssessment.json").write_text(
        json.dumps(_create_assessment_workflow())
    )
    (out / "src" / "schemas" / "candidates" / "new.json").write_text(
        json.dumps(_candidate_new_form())
    )
    return out


# --------------------------------------------------------------------------- #
# Cheap-locate — deterministic, NO model.
# --------------------------------------------------------------------------- #

def test_cheap_locate_save_fails_shortlists_scheduling_workflow(app_dir):
    loc = cheap_locate("scheduling an assessment fails to save", str(app_dir))

    assert loc["category"] == "save_create_fails"
    paths = [a["path"] for a in loc["artifacts"]]
    assert "workflows/assessmentschedulingworkflow.json" in paths

    top = loc["artifacts"][0]
    # The domain scheduling workflow ranks above the generic CRUD one.
    assert top["path"] == "workflows/assessmentschedulingworkflow.json"
    assert top["kind"] == "workflow"
    assert top["nodeId"] == "create_assessment_record"


def test_cheap_locate_upload_shortlists_candidate_form_cv_field(app_dir):
    loc = cheap_locate("I can't upload a CV", str(app_dir))

    assert loc["category"] == "cant_upload"
    top = loc["artifacts"][0]
    assert top["kind"] in ("page", "schema")
    assert top["path"] == "src/schemas/candidates/new.json"
    assert top["column"] == "cvUrl"
    # The pointer locates the cvUrl control inside the form tree.
    assert top["jsonPointer"] and "cvUrl" not in top["jsonPointer"]  # it's a path, not a name


def test_cheap_locate_no_model_needed(app_dir):
    # Sanity: cheap_locate takes no query_fn and never imports the SDK.
    loc = cheap_locate("scheduling an assessment fails to save", str(app_dir))
    assert isinstance(loc["artifacts"], list) and loc["artifacts"]


# --------------------------------------------------------------------------- #
# validate_workflow_patch — the analyze-clean check.
# --------------------------------------------------------------------------- #

def test_validate_workflow_patch_clean_after_fix(app_dir):
    wf_path = str(app_dir / "workflows" / "assessmentschedulingworkflow.json")
    good_patch = {
        "values": {
            "applicationId": "{{applicationId}}",
            "candidateId": "{{candidateId}}",
            "assessmentType": "{{assessmentType}}",
            "scheduledAt": "CURRENT_TIMESTAMP",
            "location": "{{location}}",
            "assignedAssessorId": "{{assignedAssessorId}}",
        },
    }
    res = validate_workflow_patch(
        str(app_dir), wf_path, "create_assessment_record", good_patch
    )
    assert res["clean"] is True
    assert res["remaining"] == []


def test_validate_workflow_patch_dirty_when_bug_remains(app_dir):
    wf_path = str(app_dir / "workflows" / "assessmentschedulingworkflow.json")
    bad_patch = {"values": {"candidateId": "CURRENT_TIMESTAMP"}}
    res = validate_workflow_patch(
        str(app_dir), wf_path, "create_assessment_record", bad_patch
    )
    assert res["clean"] is False
    assert any(f["column"] == "candidateId" for f in res["remaining"])


# --------------------------------------------------------------------------- #
# diagnose — two-step, capable-patch via an injected query_fn (NO real model).
# --------------------------------------------------------------------------- #

def _canned_workflow_query(system_prompt: str, user_prompt: str) -> str:
    """Fake capable-patch: returns the corrected candidate_id diagnosis."""
    return json.dumps(
        {
            "feature": "Schedule an assessment for a shortlisted candidate",
            "rootCause": (
                "The Create Assessment Record node writes CURRENT_TIMESTAMP into "
                "candidateId (a uuid) and leaks its node label into status."
            ),
            "artifact": {
                "kind": "workflow",
                "path": "workflows/assessmentschedulingworkflow.json",
            },
            "locator": {"nodeId": "create_assessment_record", "jsonPointer": None},
            "proposedFix": {
                "seam": "workflow_node_config",
                "patch": {
                    "values": {
                        "applicationId": "{{applicationId}}",
                        "candidateId": "{{candidateId}}",
                        "assessmentType": "{{assessmentType}}",
                        "scheduledAt": "CURRENT_TIMESTAMP",
                        "location": "{{location}}",
                        "assignedAssessorId": "{{assignedAssessorId}}",
                    }
                },
            },
            "confidence": 0.9,
            "explanation": (
                "The scheduling workflow was saving the current time into the "
                "candidate field, which the database rejects. I'll bind it to the "
                "selected candidate instead."
            ),
        }
    )


def test_diagnose_candidate_id_workflow(app_dir):
    diag = diagnose(
        "scheduling an assessment fails to save",
        str(app_dir),
        query_fn=_canned_workflow_query,
    )

    assert diag["symptom"] == "scheduling an assessment fails to save"
    assert diag["artifact"]["kind"] == "workflow"
    assert diag["artifact"]["path"] == "workflows/assessmentschedulingworkflow.json"
    assert diag["locator"]["nodeId"] == "create_assessment_record"
    assert diag["proposedFix"]["seam"] == "workflow_node_config"
    # The proposed values fix analyzes CLEAN and confidence stays high.
    assert diag["validation"]["clean"] is True
    assert diag["confidence"] >= 0.8
    # candidateId is rebound off CURRENT_TIMESTAMP.
    assert diag["proposedFix"]["patch"]["values"]["candidateId"] == "{{candidateId}}"


def test_diagnose_lowers_confidence_when_patch_dirty(app_dir):
    def _bad_query(system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {
                "rootCause": "candidateId wrong",
                "artifact": {
                    "kind": "workflow",
                    "path": "workflows/assessmentschedulingworkflow.json",
                },
                "locator": {"nodeId": "create_assessment_record"},
                "proposedFix": {
                    "seam": "workflow_node_config",
                    # still leaves CURRENT_TIMESTAMP in the uuid column
                    "patch": {"values": {"candidateId": "CURRENT_TIMESTAMP"}},
                },
                "confidence": 0.9,
                "explanation": "…",
            }
        )

    diag = diagnose(
        "scheduling an assessment fails to save", str(app_dir), query_fn=_bad_query
    )
    assert diag["validation"]["clean"] is False
    assert diag["confidence"] < 0.5


def _canned_upload_query(system_prompt: str, user_prompt: str) -> str:
    return json.dumps(
        {
            "feature": "Upload a candidate's CV on the create form",
            "rootCause": "cvUrl is a plain text Input, not a FileUpload control.",
            "artifact": {"kind": "page", "path": "src/schemas/candidates/new.json"},
            "locator": {
                "nodeId": None,
                "jsonPointer": "/root/children/2/type",
            },
            "proposedFix": {
                "seam": "page_schema_patch",
                "patch": [
                    {"op": "replace", "path": "/root/children/2/type", "value": "FileUpload"}
                ],
            },
            "confidence": 0.75,
            "explanation": "The CV field is a text box; I'll switch it to a file upload.",
        }
    )


def test_diagnose_cant_upload_cv(app_dir):
    diag = diagnose("I can't upload a CV", str(app_dir), query_fn=_canned_upload_query)

    assert diag["symptom"] == "I can't upload a CV"
    assert diag["artifact"]["kind"] in ("page", "schema")
    assert diag["proposedFix"]["seam"] == "page_schema_patch"
    assert isinstance(diag["proposedFix"]["patch"], list)  # RFC-6902 ops
    # Locator points at the cvUrl field.
    assert diag["locator"]["jsonPointer"]


# --------------------------------------------------------------------------- #
# Task 2-A — pasted raw error → parse_error + higher-precision locate.
# --------------------------------------------------------------------------- #

_CANDIDATE_ID_PG_ERROR = (
    '[workflow:assessmentschedulingworkflow] Create Assessment Record: '
    'PostgresError: column "candidate_id" is of type uuid but expression is '
    'of type timestamp with time zone'
)

_NEXT_STACK = (
    "TypeError: Cannot read properties of undefined (reading 'map')\n"
    "    at CandidateForm (../src/components/CandidateForm.tsx:42:15)\n"
    "    at renderWithHooks (../node_modules/react-dom/cjs/react-dom.development.js:16305:18)\n"
    "    at mountIndeterminateComponent (../node_modules/react-dom/cjs/react-dom.development.js:20074:13)"
)


def test_parse_error_candidate_id_postgres():
    parsed = parse_error(_CANDIDATE_ID_PG_ERROR)
    assert parsed is not None
    assert parsed["kind"] == "postgres_type_mismatch"
    assert parsed["workflow"] == "assessmentschedulingworkflow"
    assert parsed["column"] == "candidate_id"
    assert parsed["columnType"] == "uuid"
    assert parsed["rawType"] == "timestamp with time zone"
    assert parsed["nodeLabel"] == "Create Assessment Record"


def test_parse_error_next_component_stack():
    parsed = parse_error(_NEXT_STACK)
    assert parsed is not None
    assert parsed["kind"] == "component_stack"
    # The first APP frame (src/…), not the node_modules react-dom frames.
    assert parsed["componentPath"] == "src/components/CandidateForm.tsx"
    assert parsed["component"] == "CandidateForm"


def test_parse_error_generic_workflow_prefix():
    parsed = parse_error(
        "[workflow:approvalworkflow] Notify Approver: Error: something went wrong"
    )
    assert parsed is not None
    assert parsed["kind"] == "workflow_error"
    assert parsed["workflow"] == "approvalworkflow"
    assert parsed["nodeLabel"] == "Notify Approver"


def test_parse_error_plain_symptom_is_none():
    # A plain NL symptom must NOT be mistaken for a raw error (falls through to
    # the taxonomy).
    assert parse_error("scheduling an assessment fails to save") is None
    assert parse_error("") is None
    assert parse_error(None) is None  # type: ignore[arg-type]


def test_cheap_locate_postgres_error_pinpoints_node_and_column(app_dir):
    loc = cheap_locate(_CANDIDATE_ID_PG_ERROR, str(app_dir))

    assert loc["category"] == "postgres_type_mismatch"
    top = loc["artifacts"][0]
    assert top["kind"] == "workflow"
    assert top["path"] == "workflows/assessmentschedulingworkflow.json"
    assert top["nodeId"] == "create_assessment_record"
    # snake_case candidate_id resolved to the real camelCase node-values key.
    assert top["column"] == "candidateId"
    # Bonus: the value↔type analyzer pre-confirms the same mismatch.
    assert any(f["column"] == "candidateId" for f in top.get("analysis", []))


def test_cheap_locate_component_stack_returns_page_artifact(app_dir):
    loc = cheap_locate(_NEXT_STACK, str(app_dir))

    assert loc["category"] == "component_stack"
    top = loc["artifacts"][0]
    assert top["kind"] == "page"
    assert top["path"] == "src/components/CandidateForm.tsx"
    assert top["component"] == "CandidateForm"


def test_diagnose_from_postgres_error_uses_workflow_seam(app_dir):
    # An error string routes through parse_error → the workflow node; the capable
    # step (injected) returns the corrected values → seam workflow_node_config,
    # analyzes clean.
    diag = diagnose(
        _CANDIDATE_ID_PG_ERROR, str(app_dir), query_fn=_canned_workflow_query
    )
    assert diag["artifact"]["path"] == "workflows/assessmentschedulingworkflow.json"
    assert diag["locator"]["nodeId"] == "create_assessment_record"
    assert diag["proposedFix"]["seam"] == "workflow_node_config"
    assert diag["validation"]["clean"] is True


def test_diagnose_no_artifact_low_confidence(app_dir):
    # A symptom the taxonomy can't localize → a low-confidence, code_edit fallback
    # WITHOUT ever calling the model.
    def _never(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("query_fn must not be called when nothing is located")

    diag = diagnose("everything feels slow and janky", str(app_dir), query_fn=_never)
    assert diag["confidence"] <= 0.3
    assert diag["proposedFix"]["seam"] == "code_edit"

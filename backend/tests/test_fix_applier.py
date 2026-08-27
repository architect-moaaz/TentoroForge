"""Tests for the deterministic fix-applier (Task 1-C).

Given a structured Diagnosis, apply_fix routes through the correct deterministic
seam, heals the whole app, RE-VERIFIES honestly, and reports. Git is skipped
(``git=False``) so the tests stay hermetic.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from services import fix_applier


REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_WORKFLOW = REPO_ROOT / "output" / "mc2xgclv" / "workflows" / "assessmentschedulingworkflow.json"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _minimal_registry() -> dict:
    """A resource-registry with just the `assessments` table so the value↔column
    verify has real column types to check against."""
    return {
        "version": 1,
        "entities": {
            "Assessment": {
                "table": "assessments",
                "columns": [
                    {"name": "id", "type": "uuid"},
                    {"name": "applicationId", "type": "uuid"},
                    {"name": "candidateId", "type": "uuid"},
                    {"name": "assessmentType", "type": "varchar"},
                    {"name": "scheduledAt", "type": "timestamp"},
                    {"name": "location", "type": "varchar"},
                    {"name": "assignedAssessorId", "type": "uuid"},
                    {"name": "status", "type": "varchar"},
                ],
            },
        },
    }


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    """A temp output dir carrying a copy of the real scheduling workflow + a
    minimal registry."""
    out = tmp_path / "app"
    (out / "workflows").mkdir(parents=True)
    (out / "contracts").mkdir(parents=True)
    shutil.copy(REAL_WORKFLOW, out / "workflows" / "assessmentschedulingworkflow.json")
    (out / "contracts" / "resource-registry.json").write_text(
        json.dumps(_minimal_registry(), indent=2)
    )
    return out


@pytest.fixture(autouse=True)
def spy_post_generate(monkeypatch):
    """Replace the whole-app heal with a spy — keeps tests fast/hermetic while
    proving apply_fix invokes it after a structured apply."""
    calls: list[str] = []

    def _spy(output_dir: str) -> int:
        calls.append(output_dir)
        return 0

    monkeypatch.setattr(fix_applier, "apply_post_generate_fixes", _spy)
    return calls


def _node_values(app_dir: Path, node_id: str) -> dict:
    data = json.loads((app_dir / "workflows" / "assessmentschedulingworkflow.json").read_text())
    for n in data["definition"]["nodes"]:
        if n.get("id") == node_id:
            return n["data"]["config"]["values"]
    raise AssertionError(f"node {node_id} not found")


# --------------------------------------------------------------------------- #
# workflow_node_config seam
# --------------------------------------------------------------------------- #

def test_workflow_node_config_fix_resolves(app_dir, spy_post_generate):
    """The candidate_id fix: rebind candidateId to {{candidateId}}, fix the leaked
    status label → after apply the node is corrected, post-gen heal ran, and the
    value↔column verify comes back clean."""
    corrected_values = {
        "applicationId": "{{applicationId}}",
        "candidateId": "{{candidateId}}",
        "assessmentType": "{{assessmentType}}",
        "scheduledAt": "CURRENT_TIMESTAMP",
        "location": "{{location}}",
        "assignedAssessorId": "{{assignedAssessorId}}",
        "status": "scheduled",
    }
    diagnosis = {
        "symptom": "Scheduling an assessment fails to save.",
        "feature": "Schedule Assessment",
        "rootCause": "candidateId (uuid) is written CURRENT_TIMESTAMP; status leaked the node label.",
        "artifact": {"kind": "workflow", "path": "workflows/assessmentschedulingworkflow.json"},
        "locator": {"nodeId": "create_assessment_record", "jsonPointer": None},
        "proposedFix": {"seam": "workflow_node_config", "patch": {"values": corrected_values}},
        "confidence": 0.9,
        "explanation": "Bind the candidate field and fix the status.",
    }

    result = fix_applier.apply_fix(str(app_dir), diagnosis, git=False)

    assert result["applied"] is True
    assert result["seam"] == "workflow_node_config"
    # The node on disk is corrected.
    values = _node_values(app_dir, "create_assessment_record")
    assert values["candidateId"] == "{{candidateId}}"
    assert values["status"] == "scheduled"
    # The whole-app heal ran.
    assert spy_post_generate == [str(app_dir)]
    # Honest verify: no remaining type mismatches.
    assert result["verify"]["resolved"] is True
    assert result["verify"]["remaining"] == []
    assert result["committed"] is False


def test_workflow_node_config_unfixed_reports_unresolved(app_dir):
    """A patch that does NOT actually fix the mismatch must NOT claim resolved —
    the verify still finds candidateId (a timestamp literal into a uuid)."""
    bad_values = {
        "applicationId": "{{applicationId}}",
        "candidateId": "CURRENT_TIMESTAMP",  # still wrong
        "assessmentType": "{{assessmentType}}",
        "scheduledAt": "CURRENT_TIMESTAMP",
        "location": "{{location}}",
        "assignedAssessorId": "{{assignedAssessorId}}",
        "status": "scheduled",
    }
    diagnosis = {
        "symptom": "Scheduling an assessment fails to save.",
        "feature": "Schedule Assessment",
        "rootCause": "candidateId type mismatch",
        "artifact": {"kind": "workflow", "path": "workflows/assessmentschedulingworkflow.json"},
        "locator": {"nodeId": "create_assessment_record", "jsonPointer": None},
        "proposedFix": {"seam": "workflow_node_config", "patch": {"values": bad_values}},
        "confidence": 0.5,
        "explanation": "",
    }

    result = fix_applier.apply_fix(str(app_dir), diagnosis, git=False)

    assert result["applied"] is True
    assert result["verify"]["resolved"] is False
    remaining = result["verify"]["remaining"]
    assert remaining, "expected a remaining finding"
    assert any(f["column"] == "candidateId" for f in remaining)


def test_missing_node_does_not_corrupt_artifact(app_dir):
    """An unknown nodeId is a safe no-op — applied False, artifact untouched."""
    original = (app_dir / "workflows" / "assessmentschedulingworkflow.json").read_text()
    diagnosis = {
        "symptom": "x",
        "feature": "x",
        "rootCause": "x",
        "artifact": {"kind": "workflow", "path": "workflows/assessmentschedulingworkflow.json"},
        "locator": {"nodeId": "no_such_node", "jsonPointer": None},
        "proposedFix": {"seam": "workflow_node_config", "patch": {"values": {"x": "y"}}},
        "confidence": 0.1,
        "explanation": "",
    }

    result = fix_applier.apply_fix(str(app_dir), diagnosis, git=False)

    assert result["applied"] is False
    assert (app_dir / "workflows" / "assessmentschedulingworkflow.json").read_text() == original


# --------------------------------------------------------------------------- #
# code_edit seam — out of slice-1 scope
# --------------------------------------------------------------------------- #

def test_code_edit_seam_is_safe_noop(app_dir):
    diagnosis = {
        "symptom": "x",
        "feature": "x",
        "rootCause": "x",
        "artifact": {"kind": "page", "path": "src/app/page.tsx"},
        "locator": {"nodeId": None, "jsonPointer": None},
        "proposedFix": {"seam": "code_edit", "patch": {"replace": "..."}},
        "confidence": 0.2,
        "explanation": "",
    }

    result = fix_applier.apply_fix(str(app_dir), diagnosis, git=False)

    assert result["applied"] is False
    assert "code_edit" in result["reason"]
    assert result["verify"]["resolved"] is False


# --------------------------------------------------------------------------- #
# page_schema_patch seam
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# apply_fix_with_retry — bounded re-diagnose-on-failure loop (Task 2-B)
# --------------------------------------------------------------------------- #

def _wf_diagnosis(values: dict) -> dict:
    return {
        "symptom": "Scheduling an assessment fails to save.",
        "feature": "Schedule Assessment",
        "rootCause": "candidateId type mismatch",
        "artifact": {"kind": "workflow", "path": "workflows/assessmentschedulingworkflow.json"},
        "locator": {"nodeId": "create_assessment_record", "jsonPointer": None},
        "proposedFix": {"seam": "workflow_node_config", "patch": {"values": values}},
        "confidence": 0.7,
        "explanation": "",
    }


_BAD_VALUES = {
    "applicationId": "{{applicationId}}",
    "candidateId": "CURRENT_TIMESTAMP",  # still wrong → leaves a residual
    "assessmentType": "{{assessmentType}}",
    "scheduledAt": "CURRENT_TIMESTAMP",
    "location": "{{location}}",
    "assignedAssessorId": "{{assignedAssessorId}}",
    "status": "scheduled",
}
_GOOD_VALUES = dict(_BAD_VALUES, candidateId="{{candidateId}}")


def test_retry_resolves_on_second_attempt(app_dir, spy_post_generate):
    """First patch leaves candidateId broken → residual fed back to diagnose_fn →
    corrected patch → resolved. Exactly one re-diagnosis."""
    seen_residuals: list[dict] = []

    def _diagnose_fn(residual):
        seen_residuals.append(residual)
        return _wf_diagnosis(_GOOD_VALUES)

    result = fix_applier.apply_fix_with_retry(
        str(app_dir), _wf_diagnosis(_BAD_VALUES),
        diagnose_fn=_diagnose_fn, git=False,
    )

    assert result["resolved"] is True
    assert result["verify"]["resolved"] is True
    assert result["retries"] == 1
    # diagnose_fn was called exactly once, with a residual describing the leftover.
    assert len(seen_residuals) == 1
    remaining = seen_residuals[0]["remaining"]
    assert any(f.get("column") == "candidateId" for f in remaining)
    # The node on disk is corrected.
    assert _node_values(app_dir, "create_assessment_record")["candidateId"] == "{{candidateId}}"


def test_retry_bounded_stop_reports_unresolved(app_dir, spy_post_generate):
    """Both attempts fail → bounded stop after exactly one retry, resolved False,
    residual reported, never a silent loop / false success."""
    calls = {"n": 0}

    def _diagnose_fn(residual):
        calls["n"] += 1
        return _wf_diagnosis(_BAD_VALUES)  # still broken

    result = fix_applier.apply_fix_with_retry(
        str(app_dir), _wf_diagnosis(_BAD_VALUES),
        diagnose_fn=_diagnose_fn, max_retries=1, git=False,
    )

    assert result["resolved"] is False
    assert result["verify"]["resolved"] is False
    assert result["retries"] == 1
    # Exactly one re-diagnosis — never loops.
    assert calls["n"] == 1
    # A clear residual + message is surfaced (no false "resolved").
    assert result["residual"]["remaining"]
    assert any(f.get("column") == "candidateId" for f in result["residual"]["remaining"])
    assert "couldn't" in result["message"].lower() or "remain" in result["message"].lower()


def test_retry_returns_immediately_when_first_apply_resolves(app_dir, spy_post_generate):
    """When the first apply already resolves, diagnose_fn is never called."""
    def _must_not_call(residual):  # pragma: no cover - must not run
        raise AssertionError("diagnose_fn called despite a resolved first apply")

    result = fix_applier.apply_fix_with_retry(
        str(app_dir), _wf_diagnosis(_GOOD_VALUES),
        diagnose_fn=_must_not_call, git=False,
    )

    assert result["resolved"] is True
    assert result["retries"] == 0


def test_page_schema_patch_applies(tmp_path, spy_post_generate):
    out = tmp_path / "app"
    pages = out / "src" / "pages"
    pages.mkdir(parents=True)
    schema = {
        "schemaVersion": 2,
        "id": "candidates",
        "route": "/candidates",
        "root": {
            "type": "Stack",
            "props": {"title": "Candidates"},
            "children": [],
        },
    }
    schema_path = pages / "candidates.json"
    schema_path.write_text(json.dumps(schema, indent=2))

    diagnosis = {
        "symptom": "title wrong",
        "feature": "Candidates list",
        "rootCause": "title",
        "artifact": {"kind": "page", "path": "src/pages/candidates.json"},
        "locator": {"nodeId": None, "jsonPointer": "/root/props/title"},
        "proposedFix": {
            "seam": "page_schema_patch",
            "patch": [{"op": "replace", "path": "/root/props/title", "value": "All Candidates"}],
        },
        "confidence": 0.8,
        "explanation": "",
    }

    result = fix_applier.apply_fix(str(out), diagnosis, git=False)

    assert result["applied"] is True
    assert result["seam"] == "page_schema_patch"
    patched = json.loads(schema_path.read_text())
    assert patched["root"]["props"]["title"] == "All Candidates"
    assert result["verify"]["resolved"] is True
    assert spy_post_generate == [str(out)]

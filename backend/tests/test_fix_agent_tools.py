"""Tests for the Fix-Assistant tool palette (Slice 3, Task 3-A).

Every tool is a thin wrapper around a Slice 0-2 primitive; the wrappers are
read-only, JSON-serializable, and reject unsafe paths. Tests exercise them on
the real ``output/mc2xgclv`` app when it exists, plus a compact tmp_path
fixture for shape assertions.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services import fix_agent_tools as tools


REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_APP = REPO_ROOT / "output" / "mc2xgclv"
HAS_LIVE = LIVE_APP.is_dir() and (LIVE_APP / "contracts" / "resource-registry.json").is_file()


# --------------------------------------------------------------------------- #
# Compact tmp_path fixture mirroring the mc2xgclv shape
# --------------------------------------------------------------------------- #

_REGISTRY = {
    "entities": {
        "Assessment": {
            "id": "assessment",
            "name": "Assessment",
            "slug": "assessments",
            "table": "assessments",
            "columns": [
                {"name": "id", "type": "uuid", "notNull": True, "primaryKey": True},
                {"name": "candidateId", "type": "uuid", "fk": "candidate", "notNull": True},
                {"name": "scheduledAt", "type": "timestamp", "notNull": False},
                {"name": "status", "type": "varchar", "notNull": False},
            ],
        },
        "Candidate": {
            "id": "candidate",
            "name": "Candidate",
            "slug": "candidates",
            "table": "candidates",
            "columns": [{"name": "id", "type": "uuid"}, {"name": "fullName", "type": "varchar"}],
        },
    },
    "relationships": [],
    "roles": ["Recruiter"],
    "interactions": [],
    "version": 1,
}


_WORKFLOW = {
    "id": "createassessment",
    "name": "CreateAssessment",
    "definition": {
        "trigger": {"type": "manual"},
        "nodes": [
            {
                "id": "create_assessment_record",
                "type": "action",
                "data": {
                    "label": "Create Assessment Record",
                    "nodeType": "action",
                    "config": {
                        "table": "assessments",
                        "actionType": "db_insert",
                        # DELIBERATE bug: candidateId=CURRENT_TIMESTAMP (uuid col).
                        "values": {
                            "candidateId": "CURRENT_TIMESTAMP",
                            "scheduledAt": "CURRENT_TIMESTAMP",
                            "status": "Create Assessment Record",
                        },
                        "nodeType": "action",
                    },
                },
            },
        ],
        "edges": [],
    },
}


_PAGE = {
    "schemaVersion": "2",
    "id": "assessments-new",
    "route": "/assessments/new",
    "root": {
        "type": "Stack",
        "children": [
            {"type": "Form", "props": {"workflow": "createassessment"}, "children": [
                {"type": "Input", "props": {"name": "candidateId", "label": "Candidate"}},
                {"type": "DateTimePicker", "props": {"name": "scheduledAt", "label": "When"}},
                {"type": "Button", "props": {"label": "Save", "action": {"workflow": "createassessment"}}},
            ]},
        ],
    },
}


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps(_REGISTRY))
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "CreateAssessment.json").write_text(json.dumps(_WORKFLOW))
    (tmp_path / "src" / "schemas" / "assessments").mkdir(parents=True)
    (tmp_path / "src" / "schemas" / "assessments" / "new.json").write_text(json.dumps(_PAGE))
    # Also a small dossier so recall() has intent.
    (tmp_path / "contracts" / "generation-dossier.json").write_text(json.dumps({
        "prompt": "recruit-tech assessments app",
        "plan": {"description": "an ATS with assessments"},
        "generatedAt": None,
    }))
    return tmp_path


# --------------------------------------------------------------------------- #
# path safety
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", ["/etc/passwd", "../secret", "workflows/../../x",
                                 "workflows/./../../x", "\\Windows\\System32"])
def test_read_workflow_rejects_unsafe_paths(app_dir: Path, bad: str):
    out = tools.read_workflow(str(app_dir), bad)
    assert "error" in out


@pytest.mark.parametrize("bad", ["/x", "..", "../../", "src/../../"])
def test_read_page_rejects_unsafe_paths(app_dir: Path, bad: str):
    out = tools.read_page(str(app_dir), bad)
    assert "error" in out


def test_analyze_rejects_unsafe_paths(app_dir: Path):
    assert "error" in tools.analyze_workflow_values_tool(str(app_dir), "../../x")
    assert "error" in tools.analyze_workflow_values_tool(str(app_dir), "/tmp/x.json")


# --------------------------------------------------------------------------- #
# recall / list_workflows / read_workflow / read_page
# --------------------------------------------------------------------------- #

def test_recall_shape(app_dir: Path):
    out = tools.recall(str(app_dir))
    assert "promptBlock" in out
    assert isinstance(out["promptBlock"], str) and out["promptBlock"]
    assert any(e.get("name") == "Assessment" for e in out["entities"])
    assert "Recruiter" in out["roles"]


def test_list_workflows_finds_files(app_dir: Path):
    out = tools.list_workflows(str(app_dir))
    wfs = out["workflows"]
    assert len(wfs) == 1
    assert wfs[0]["path"] == "workflows/CreateAssessment.json"
    assert wfs[0]["name"] == "CreateAssessment"
    assert wfs[0]["id"] == "createassessment"


def test_read_workflow_returns_nodes(app_dir: Path):
    out = tools.read_workflow(str(app_dir), "workflows/CreateAssessment.json")
    assert out["name"] == "CreateAssessment"
    assert len(out["nodes"]) == 1
    node = out["nodes"][0]
    assert node["id"] == "create_assessment_record"
    assert node["config"]["actionType"] == "db_insert"
    assert node["config"]["values"]["candidateId"] == "CURRENT_TIMESTAMP"


def test_read_workflow_missing_file(app_dir: Path):
    out = tools.read_workflow(str(app_dir), "workflows/DoesNotExist.json")
    assert "error" in out


def test_read_page_extracts_refs_and_fields(app_dir: Path):
    out = tools.read_page(str(app_dir), "src/schemas/assessments/new.json")
    assert out["route"] == "/assessments/new"
    assert "createassessment" in out["workflowRefs"]
    names = {f["name"] for f in out["fields"]}
    assert {"candidateId", "scheduledAt"}.issubset(names)


# --------------------------------------------------------------------------- #
# read_column
# --------------------------------------------------------------------------- #

def test_read_column_returns_type_and_fk(app_dir: Path):
    out = tools.read_column(str(app_dir), "Assessment", "candidateId")
    assert out["type"] == "uuid"
    assert out["fk"] == "candidate"
    assert out["notNull"] is True


def test_read_column_unknown(app_dir: Path):
    assert "error" in tools.read_column(str(app_dir), "Assessment", "nope")
    assert "error" in tools.read_column(str(app_dir), "NoSuchEntity", "id")


# --------------------------------------------------------------------------- #
# analyzers / parsers
# --------------------------------------------------------------------------- #

def test_analyze_workflow_values_flags_candidate_id(app_dir: Path):
    out = tools.analyze_workflow_values_tool(str(app_dir), "workflows/CreateAssessment.json")
    findings = out["findings"]
    # candidateId=CURRENT_TIMESTAMP into uuid → mismatch.
    cols = {f["column"] for f in findings}
    assert "candidateId" in cols


def test_parse_error_pg_type_mismatch():
    text = 'column "candidate_id" is of type uuid but expression is of type timestamp with time zone'
    out = tools.parse_error_tool(text)
    assert out["kind"] == "postgres_type_mismatch"
    assert out["column"] == "candidate_id"


def test_parse_error_non_error_returns_empty():
    assert tools.parse_error_tool("some plain sentence") == {}


# --------------------------------------------------------------------------- #
# probes
# --------------------------------------------------------------------------- #

def test_probe_logs_available(app_dir: Path):
    (app_dir / "logs").mkdir()
    (app_dir / "logs" / "server.log").write_text("hello\nworld\n")
    out = tools.probe_logs_tool(str(app_dir), lines=10)
    assert out["available"] is True
    assert out["evidence"]["lines"][-1] == "world"


def test_probe_logs_missing(app_dir: Path):
    out = tools.probe_logs_tool(str(app_dir))
    assert out["available"] is False
    assert "reason" in out


def test_probe_endpoint_rejects_non_local(app_dir: Path):
    out = tools.probe_endpoint_tool(str(app_dir), "https://example.com/")
    assert out["available"] is False
    assert "local" in (out["reason"] or "").lower()


# --------------------------------------------------------------------------- #
# Live app smoke — only when output/mc2xgclv is present.
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not HAS_LIVE, reason="output/mc2xgclv not present")
def test_live_recall_and_list_workflows():
    r = tools.recall(str(LIVE_APP))
    assert "error" not in r
    assert isinstance(r["entities"], list) and r["entities"]

    ws = tools.list_workflows(str(LIVE_APP))
    assert "error" not in ws
    assert ws["workflows"], "expected workflows/*.json under mc2xgclv"


@pytest.mark.skipif(not HAS_LIVE, reason="output/mc2xgclv not present")
def test_live_read_workflow_and_analyze():
    ws = tools.list_workflows(str(LIVE_APP))["workflows"]
    wf_path = ws[0]["path"]
    read = tools.read_workflow(str(LIVE_APP), wf_path)
    assert "error" not in read
    assert isinstance(read["nodes"], list)
    ana = tools.analyze_workflow_values_tool(str(LIVE_APP), wf_path)
    assert "findings" in ana  # empty or populated; never an error

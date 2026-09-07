"""Tests for the Fix-Assistant agent (Slice 3, Task 3-B).

The LLM boundary is an injectable ``query_fn`` yielding canned tool-call dicts,
so the model is NEVER hit. Tests exercise:

- happy path (read_workflow → propose_fix)
- investigate-then-propose (parse_error → read_workflow → analyze → propose_fix)
- clarifying (ask_user → terminates with a question)
- iteration cap (a canned stream that never terminates → forced ask_user)
- unknown tool guardrail (single unknown → recover; two consecutive → forced ask_user)
- invalid diagnosis shape (propose_fix returns error → agent may recover)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.fix_chat_agent import run_fix_agent


# --------------------------------------------------------------------------- #
# Compact tmp_path app fixture (mirrors test_fix_agent_tools)
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
    },
    "relationships": [],
    "roles": [],
    "interactions": [],
    "version": 1,
}


def _workflow(dirty: bool = True) -> dict:
    values = {
        "candidateId": "CURRENT_TIMESTAMP" if dirty else "{{candidateId}}",
        "scheduledAt": "CURRENT_TIMESTAMP",
        "status": "Create Assessment Record" if dirty else "scheduled",
    }
    return {
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
                            "values": values,
                            "nodeType": "action",
                        },
                    },
                },
            ],
            "edges": [],
        },
    }


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps(_REGISTRY), encoding="utf-8")
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "CreateAssessment.json").write_text(json.dumps(_workflow()), encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# Injected query_fn: returns a canned iterator of tool-call dicts.
# --------------------------------------------------------------------------- #

def _stream(*steps: dict):
    """Return a factory matching the QueryFn signature (system, messages, tools)
    that yields the given canned steps in order."""
    def _fn(_system, _messages, _tools):
        for step in steps:
            yield step
    return _fn


# --------------------------------------------------------------------------- #
# Common diagnosis fixture (the deterministic fix)
# --------------------------------------------------------------------------- #

def _good_diagnosis() -> dict:
    return {
        "feature": "Schedule an assessment",
        "rootCause": "candidateId is written as CURRENT_TIMESTAMP into a uuid column",
        "artifact": {"kind": "workflow", "path": "workflows/CreateAssessment.json"},
        "locator": {"nodeId": "create_assessment_record", "jsonPointer": None},
        "proposedFix": {
            "seam": "workflow_node_config",
            "patch": {"values": {
                "candidateId": "{{candidateId}}",
                "scheduledAt": "{{scheduledAt}}",
                "status": "scheduled",
            }},
        },
        "confidence": 0.85,
        "explanation": "The workflow was writing the current timestamp into the candidate FK.",
    }


# --------------------------------------------------------------------------- #
# 1. Happy path: read_workflow → propose_fix
# --------------------------------------------------------------------------- #

def test_happy_path_read_then_propose(app_dir: Path):
    canned = _stream(
        {"tool": "read_workflow", "args": {"path": "workflows/CreateAssessment.json"}},
        {"tool": "propose_fix", "args": {"diagnosis": _good_diagnosis()}},
    )
    result = run_fix_agent(
        symptom="Scheduling an assessment fails",
        output_dir=str(app_dir),
        recall_block="(recall)",
        query_fn=canned,
    )
    assert result["question"] is None
    diag = result["diagnosis"]
    assert diag is not None
    assert diag["artifact"]["path"] == "workflows/CreateAssessment.json"
    assert diag["locator"]["nodeId"] == "create_assessment_record"
    # The proposed patch validates clean — analyzer finds no remaining bugs.
    assert diag["validation"]["clean"] is True
    assert diag["confidence"] == pytest.approx(0.85)
    # Trace has exactly the two tool calls.
    assert [t["tool"] for t in result["trace"]] == ["read_workflow", "propose_fix"]


# --------------------------------------------------------------------------- #
# 2. Investigate-then-propose: parse_error → read_workflow → analyze → propose_fix
# --------------------------------------------------------------------------- #

def test_investigate_then_propose_validates_clean(app_dir: Path):
    canned = _stream(
        {"tool": "parse_error", "args": {"text": (
            'column "candidate_id" is of type uuid but expression is of type '
            "timestamp with time zone"
        )}},
        {"tool": "read_workflow", "args": {"path": "workflows/CreateAssessment.json"}},
        {"tool": "analyze_workflow_values",
         "args": {"path": "workflows/CreateAssessment.json"}},
        {"tool": "propose_fix", "args": {"diagnosis": _good_diagnosis()}},
    )
    result = run_fix_agent(
        symptom="save fails",
        output_dir=str(app_dir),
        recall_block="",
        query_fn=canned,
    )
    assert result["diagnosis"] is not None
    assert result["diagnosis"]["validation"]["clean"] is True
    assert [t["tool"] for t in result["trace"]] == [
        "parse_error", "read_workflow", "analyze_workflow_values", "propose_fix",
    ]


# --------------------------------------------------------------------------- #
# 3. Clarifying — ask_user terminates without a diagnosis
# --------------------------------------------------------------------------- #

def test_ask_user_terminates_with_question(app_dir: Path):
    canned = _stream(
        {"tool": "recall", "args": {}},
        {"tool": "ask_user",
         "args": {"question": "Which screen were you on and what did you click?"}},
    )
    result = run_fix_agent(
        symptom="stuff is broken",
        output_dir=str(app_dir),
        recall_block="(recall)",
        query_fn=canned,
    )
    assert result["diagnosis"] is None
    assert result["question"] == "Which screen were you on and what did you click?"
    kinds = [t["tool"] for t in result["trace"]]
    assert kinds[-1] == "ask_user"


# --------------------------------------------------------------------------- #
# 4. Iteration cap → forced ask_user
# --------------------------------------------------------------------------- #

def test_iteration_cap_forces_ask_user(app_dir: Path):
    # A canned stream that never terminates: keeps calling recall forever.
    def _endless(_system, _messages, _tools):
        while True:
            yield {"tool": "recall", "args": {}}

    result = run_fix_agent(
        symptom="anything",
        output_dir=str(app_dir),
        recall_block="",
        query_fn=_endless,
        max_iters=3,
    )
    assert result["diagnosis"] is None
    assert result["question"] is not None
    # The final trace entry is the forced ask_user.
    assert result["trace"][-1]["tool"] == "ask_user"
    assert result["trace"][-1]["args"].get("forced") == "iteration_cap"
    # And the loop honored max_iters BEFORE forcing.
    tool_calls = [t for t in result["trace"] if t["tool"] == "recall"]
    assert len(tool_calls) == 3


# --------------------------------------------------------------------------- #
# 5. Unknown-tool guardrail
# --------------------------------------------------------------------------- #

def test_unknown_tool_recovers_after_one(app_dir: Path):
    canned = _stream(
        {"tool": "delete_file", "args": {"path": "src/app/page.tsx"}},  # bogus
        {"tool": "propose_fix", "args": {"diagnosis": _good_diagnosis()}},
    )
    result = run_fix_agent(
        symptom="save fails",
        output_dir=str(app_dir),
        recall_block="",
        query_fn=canned,
    )
    # Recovered → still produced a diagnosis.
    assert result["diagnosis"] is not None
    # Trace shows the unknown tool was recorded but did NOT force ask_user.
    assert result["trace"][0]["tool"] == "delete_file"
    assert "unknown tool" in result["trace"][0]["result_summary"]
    assert result["trace"][-1]["tool"] == "propose_fix"


def test_two_consecutive_unknown_tools_force_ask_user(app_dir: Path):
    canned = _stream(
        {"tool": "delete_file", "args": {}},
        {"tool": "shell_exec", "args": {}},
        # This is never reached because the second unknown forces ask_user.
        {"tool": "propose_fix", "args": {"diagnosis": _good_diagnosis()}},
    )
    result = run_fix_agent(
        symptom="save fails",
        output_dir=str(app_dir),
        recall_block="",
        query_fn=canned,
    )
    assert result["diagnosis"] is None
    assert result["question"]
    assert result["trace"][-1]["tool"] == "ask_user"
    assert result["trace"][-1]["args"].get("forced") == "unknown_tools"


# --------------------------------------------------------------------------- #
# 6. Invalid Diagnosis shape → propose_fix returns an error; agent may recover
# --------------------------------------------------------------------------- #

def test_invalid_diagnosis_shape_returns_error_and_recovers(app_dir: Path):
    bad_diag = {"feature": "x"}  # missing artifact / seam / patch
    canned = _stream(
        {"tool": "propose_fix", "args": {"diagnosis": bad_diag}},
        {"tool": "propose_fix", "args": {"diagnosis": _good_diagnosis()}},
    )
    result = run_fix_agent(
        symptom="save fails",
        output_dir=str(app_dir),
        recall_block="",
        query_fn=canned,
    )
    # First propose_fix was rejected (invalid), second was accepted.
    assert result["diagnosis"] is not None
    kinds = [t["tool"] for t in result["trace"]]
    assert kinds.count("propose_fix") == 2
    assert "invalid diagnosis" in result["trace"][0]["result_summary"]


def test_invalid_diagnosis_shape_never_recovers_ends_at_cap(app_dir: Path):
    bad = {"tool": "propose_fix", "args": {"diagnosis": {"feature": "x"}}}

    def _stream_bad(_s, _m, _t):
        while True:
            yield bad

    result = run_fix_agent(
        symptom="save fails",
        output_dir=str(app_dir),
        recall_block="",
        query_fn=_stream_bad,
        max_iters=3,
    )
    # No diagnosis; forced ask_user at the cap.
    assert result["diagnosis"] is None
    assert result["question"] is not None
    assert result["trace"][-1]["tool"] == "ask_user"


# --------------------------------------------------------------------------- #
# 7. Dirty proposed patch → passes validation with lowered confidence
# --------------------------------------------------------------------------- #

def test_workflow_patch_still_dirty_lowers_confidence(app_dir: Path):
    # patch that only fixes candidateId; leaves status as the leaked label.
    partial = _good_diagnosis()
    partial["proposedFix"] = {
        "seam": "workflow_node_config",
        "patch": {"values": {
            "candidateId": "{{candidateId}}",
            "scheduledAt": "CURRENT_TIMESTAMP",       # still wrong (leftover)
            "status": "Create Assessment Record",     # leaked label → mismatch
        }},
    }
    partial["confidence"] = 0.9

    canned = _stream({"tool": "propose_fix", "args": {"diagnosis": partial}})
    result = run_fix_agent(
        symptom="save fails",
        output_dir=str(app_dir),
        recall_block="",
        query_fn=canned,
    )
    diag = result["diagnosis"]
    assert diag is not None
    assert diag["validation"]["clean"] is False
    assert diag["confidence"] <= 0.25
    assert "type mismatch" in diag["explanation"].lower()


# --------------------------------------------------------------------------- #
# 8. Trace contents — every tool call is recorded, in order
# --------------------------------------------------------------------------- #

def test_trace_records_every_call(app_dir: Path):
    canned = _stream(
        {"tool": "recall", "args": {}},
        {"tool": "list_workflows", "args": {}},
        {"tool": "read_column", "args": {"entity": "Assessment", "column": "candidateId"}},
        {"tool": "propose_fix", "args": {"diagnosis": _good_diagnosis()}},
    )
    result = run_fix_agent(
        symptom="save fails",
        output_dir=str(app_dir),
        recall_block="",
        query_fn=canned,
    )
    assert [t["tool"] for t in result["trace"]] == [
        "recall", "list_workflows", "read_column", "propose_fix",
    ]
    # Every entry has a compact result_summary string.
    for entry in result["trace"]:
        assert "result_summary" in entry and isinstance(entry["result_summary"], str)

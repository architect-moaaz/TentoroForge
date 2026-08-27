"""Tests for services.workflow_validator — Phase 2 O4/O5/O6/O12 backstops."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.locked_spec import Entity, LockedSpec, persist_locked_spec
from services.workflow_validator import (
    validate_output_dir,
    validate_workflow,
)


# ---------- O4 undefined-ref ----------------------------------------------

def test_undefined_ref_status_variable():
    """The nni3wjf6 bug: db_update uses `{{status}}` but no node writes it."""
    workflow = {
        "definition": {"nodes": [
            {"id": "mark_complete", "data": {"config": {
                "actionType": "db_update", "table": "scans",
                "where": {"id": "{{create_scan.id}}"},
                "values": {"status": "{{status}}"},
            }}},
            {"id": "create_scan", "data": {"config": {
                "actionType": "db_insert", "table": "scans",
                "values": {"imageUrl": "{{trigger.imageUrl}}"},
            }}},
        ]},
    }
    findings = validate_workflow(workflow, "wf.json")
    codes = [f.code for f in findings]
    assert "undefined-ref" in codes, "expected {{status}} to be flagged"
    msg = next(f.message for f in findings if f.code == "undefined-ref")
    assert '"status"' in msg


def test_trigger_ref_ok():
    """trigger.* is always declared."""
    workflow = {"definition": {"nodes": [
        {"id": "x", "data": {"config": {
            "actionType": "db_insert", "values": {"a": "{{trigger.foo}}"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert not any(f.code == "undefined-ref" for f in findings)


def test_node_id_ref_ok():
    """Refs into a declared node id resolve."""
    workflow = {"definition": {"nodes": [
        {"id": "a", "data": {"config": {"actionType": "db_insert", "values": {}}}},
        {"id": "b", "data": {"config": {
            "actionType": "db_update", "values": {"x": "{{a.id}}"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert not any(f.code == "undefined-ref" for f in findings)


def test_variable_name_declared_by_set_variable():
    """variableName written by set_variable becomes available downstream."""
    workflow = {"definition": {"nodes": [
        {"id": "set_x", "data": {"config": {
            "actionType": "set_variable", "variableName": "myVar",
            "variableValue": "hello",
        }}},
        {"id": "consume", "data": {"config": {
            "actionType": "db_insert", "values": {"col": "{{myVar}}"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert not any(f.code == "undefined-ref" for f in findings)


def test_output_var_declares_step_output():
    """outputVar on an http_call/db_query step is a producer — downstream
    {{ocrResult.text}} refs must resolve (atb0m97x false-positive class)."""
    workflow = {"definition": {"nodes": [
        {"id": "ocr_sidecar", "data": {"config": {
            "actionType": "http_call", "url": "http://sidecar/ocr",
            "outputVar": "ocrResult",
        }}},
        {"id": "persist", "data": {"config": {
            "actionType": "db_update", "table": "documents",
            "values": {"ocrText": "{{ocrResult.text}}"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert not any(f.code == "undefined-ref" for f in findings)


def test_ai_extract_fields_declare_variables():
    """ai_extract exposes each aiExtractFields entry as a top-level variable
    (runtime ai.ts) — {{extractedFields}}/{{confidenceScore}} must resolve."""
    workflow = {"definition": {"nodes": [
        {"id": "ai_extract_fields", "data": {"config": {
            "actionType": "ai_extract",
            "aiExtractFields": ["extractedFields", "confidenceScore"],
        }}},
        {"id": "persist", "data": {"config": {
            "actionType": "db_update", "table": "documents",
            "values": {"extractedFields": "{{extractedFields}}",
                       "confidenceScore": "{{confidenceScore}}"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert not any(f.code == "undefined-ref" for f in findings)


def test_process_variables_declare_trigger_inputs():
    """Top-level processVariables entries are declared trigger inputs — the
    UpdateDocument {{id}} class must not flag."""
    workflow = {
        "processVariables": [
            {"name": "documentId", "type": "string", "required": True},
            {"name": "originalFilename", "type": "string", "required": False},
        ],
        "definition": {"nodes": [
            {"id": "db_update", "data": {"config": {
                "actionType": "db_update", "table": "documents",
                "where": {"id": "{{documentId}}"},
                "values": {"originalFilename": "{{originalFilename}}"},
            }}},
        ]},
    }
    findings = validate_workflow(workflow, "wf.json")
    assert not any(f.code == "undefined-ref" for f in findings)


def test_genuinely_dangling_ref_still_flagged():
    """The widened scope must not swallow real bugs: an env root the runtime
    never resolves stays an error."""
    workflow = {"definition": {"nodes": [
        {"id": "call", "data": {"config": {
            "actionType": "http_call",
            "url": "{{env.PADDLEOCR_SIDECAR_URL}}/ocr",
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert any(f.code == "undefined-ref" and '"env"' in f.message
               for f in findings)


# ---------- O6 SQL-literal-in-value ---------------------------------------

def test_current_timestamp_literal_flagged():
    """`"CURRENT_TIMESTAMP"` as a value string is a planner bug."""
    workflow = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {
            "actionType": "db_update", "table": "scans",
            "values": {"completedAt": "CURRENT_TIMESTAMP"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert any(f.code == "sql-literal-in-value" for f in findings)


def test_now_paren_literal_flagged():
    """NOW() shouldn't leak into runtime values either."""
    workflow = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {
            "actionType": "db_update",
            "values": {"ts": "NOW()"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert any(f.code == "sql-literal-in-value" for f in findings)


def test_exact_case_aliases_downgraded_to_warning():
    """The runtime maps exact-case CURRENT_TIMESTAMP / NOW() to $now
    (_resolveRef backwards-compat aliases) — style warning, not error."""
    workflow = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {
            "actionType": "db_update",
            "values": {"a": "CURRENT_TIMESTAMP", "b": "NOW()"},
        }}},
    ]}}
    findings = [f for f in validate_workflow(workflow, "wf.json")
                if f.code == "sql-literal-in-value"]
    assert len(findings) == 2
    assert all(f.severity == "warning" for f in findings)


def test_lowercase_sql_literal_stays_error():
    """Only the exact-case alias spellings work at runtime — lowercase
    current_timestamp ships as a literal string and stays an error."""
    workflow = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {
            "actionType": "db_update",
            "values": {"a": "current_timestamp", "b": "getdate()"},
        }}},
    ]}}
    findings = [f for f in validate_workflow(workflow, "wf.json")
                if f.code == "sql-literal-in-value"]
    assert all(f.severity == "error" for f in findings)
    assert len(findings) == 2


def test_runtime_sentinel_ok():
    """A runtime sentinel like $now is legal (runtime knows to substitute)."""
    workflow = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {
            "actionType": "db_update",
            "values": {"ts": "$now"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json")
    assert not any(f.code == "sql-literal-in-value" for f in findings)


# ---------- O12 event-status-not-written -----------------------------------

def _spec_with_events(names: list[str]) -> LockedSpec:
    return LockedSpec(entities=[Entity(name=n, kind="event") for n in names])


def test_event_status_not_written_flagged():
    """Writing to a Scan event without a status write is flagged."""
    spec = _spec_with_events(["Scan"])
    workflow = {"definition": {"nodes": [
        {"id": "create_scan", "data": {"config": {
            "actionType": "db_insert", "table": "scans",
            "values": {"imageUrl": "{{trigger.imageUrl}}"},
        }}},
        # No node writes .status on scans.
    ]}}
    findings = validate_workflow(workflow, "wf.json", spec=spec)
    assert any(f.code == "event-status-not-written" for f in findings)


def test_event_status_written_ok():
    """When a status write is present, the check passes."""
    spec = _spec_with_events(["Scan"])
    workflow = {"definition": {"nodes": [
        {"id": "create_scan", "data": {"config": {
            "actionType": "db_insert", "table": "scans",
            "values": {"imageUrl": "{{trigger.imageUrl}}"},
        }}},
        {"id": "mark_done", "data": {"config": {
            "actionType": "db_update", "table": "scans",
            "where": {"id": "{{create_scan.id}}"},
            "values": {"status": "completed"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json", spec=spec)
    assert not any(f.code == "event-status-not-written" for f in findings)


def test_no_spec_skips_event_check():
    """Without a LockedSpec, the O12 check can't fire — that's fine, other
    validators still run."""
    workflow = {"definition": {"nodes": [
        {"id": "x", "data": {"config": {
            "actionType": "db_insert", "table": "scans", "values": {"a": "b"},
        }}},
    ]}}
    findings = validate_workflow(workflow, "wf.json", spec=None)
    assert not any(f.code == "event-status-not-written" for f in findings)


# ---------- end-to-end via validate_output_dir ----------------------------

def test_validate_output_dir_reads_locked_spec_and_workflows(tmp_path: Path):
    """The whole pipeline: persist a spec, write workflows, run the validator."""
    spec = _spec_with_events(["Scan"])
    persist_locked_spec(spec, tmp_path)
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "ScanProduct.json").write_text(json.dumps({
        "definition": {"nodes": [
            {"id": "create_scan", "data": {"config": {
                "actionType": "db_insert", "table": "scans",
                "values": {"imageUrl": "{{trigger.imageUrl}}"},
            }}},
            {"id": "mark_done", "data": {"config": {
                "actionType": "db_update", "table": "scans",
                "where": {"id": "{{create_scan.id}}"},
                "values": {"completedAt": "CURRENT_TIMESTAMP"},
            }}},
        ]},
    }))
    findings = validate_output_dir(tmp_path)
    codes = {f.code for f in findings}
    # SQL literal must fire.
    assert "sql-literal-in-value" in codes
    # And event-status-not-written must fire because no node writes .status.
    assert "event-status-not-written" in codes


def test_validate_output_dir_no_workflows_dir_returns_empty(tmp_path: Path):
    assert validate_output_dir(tmp_path) == []

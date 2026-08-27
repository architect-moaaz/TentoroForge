"""Tests for services.proof_auto_heal — the deterministic auto-heal loop."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.proof_auto_heal import (
    fix_missing_trigger,
    fix_now_refs,
    fix_orphan_navigate,
    fix_sql_literals,
    persist_heal_report,
    run_auto_heal,
)


# ─── fix_sql_literals ───────────────────────────────────────────────────

def test_fix_sql_literal_current_timestamp():
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {
            "actionType": "db_insert",
            "values": {"created_at": "CURRENT_TIMESTAMP", "name": "keep"},
        }}},
    ]}}
    n = fix_sql_literals(wf)
    assert n == 1
    cfg = wf["definition"]["nodes"][0]["data"]["config"]
    assert cfg["values"]["created_at"] == "$now"
    assert cfg["values"]["name"] == "keep"


def test_fix_sql_literal_now_paren():
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {"values": {"ts": "NOW()"}}}},
    ]}}
    assert fix_sql_literals(wf) == 1
    assert wf["definition"]["nodes"][0]["data"]["config"]["values"]["ts"] == "$now"


def test_fix_sql_literal_current_date():
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {"values": {"d": "current_date"}}}},
    ]}}
    fix_sql_literals(wf)
    assert wf["definition"]["nodes"][0]["data"]["config"]["values"]["d"] == "$today"


def test_fix_sql_literal_leaves_partial_match_alone():
    """Substring of a longer string must not be rewritten."""
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {"values": {
            "note": "created current_timestamp on Monday",
        }}}},
    ]}}
    assert fix_sql_literals(wf) == 0
    assert "current_timestamp" in wf["definition"]["nodes"][0]["data"]["config"]["values"]["note"]


def test_fix_sql_literal_idempotent():
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {"values": {"ts": "CURRENT_TIMESTAMP"}}}},
    ]}}
    fix_sql_literals(wf)
    assert fix_sql_literals(wf) == 0  # second pass, nothing to do


# ─── fix_now_refs ───────────────────────────────────────────────────────

def test_fix_now_ref_plain():
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {"values": {"ts": "{{now}}"}}}},
    ]}}
    assert fix_now_refs(wf) == 1
    assert wf["definition"]["nodes"][0]["data"]["config"]["values"]["ts"] == "$now"


def test_fix_now_ref_with_arithmetic():
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {"values": {"expires_at": "{{now + 90days}}"}}}},
    ]}}
    assert fix_now_refs(wf) == 1
    assert wf["definition"]["nodes"][0]["data"]["config"]["values"]["expires_at"] == "$now"


def test_fix_now_ref_with_dot_call():
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {"values": {"ts": "{{ now.toISOString() }}"}}}},
    ]}}
    assert fix_now_refs(wf) == 1
    assert wf["definition"]["nodes"][0]["data"]["config"]["values"]["ts"] == "$now"


def test_fix_now_ref_leaves_normal_refs_alone():
    wf = {"definition": {"nodes": [
        {"id": "n", "data": {"config": {"values": {
            "user_id": "{{trigger.userId}}",
            "id": "{{create_session.id}}",
        }}}},
    ]}}
    assert fix_now_refs(wf) == 0


# ─── fix_missing_trigger ────────────────────────────────────────────────

def test_fix_missing_trigger_prepends_when_absent():
    wf = {"definition": {
        "nodes": [
            {"id": "first_action", "type": "action",
             "data": {"config": {"actionType": "db_insert", "table": "scans"}}},
            {"id": "second_action", "type": "action",
             "data": {"config": {"actionType": "db_update", "table": "scans"}}},
        ],
        "edges": [
            {"source": "first_action", "target": "second_action"},
        ],
    }}
    assert fix_missing_trigger(wf) == 1
    nodes = wf["definition"]["nodes"]
    assert nodes[0]["id"] == "trigger"
    assert nodes[0]["type"] == "trigger"
    edges = wf["definition"]["edges"]
    assert edges[0] == {"source": "trigger", "target": "first_action"}


def test_fix_missing_trigger_noop_when_present():
    wf = {"definition": {
        "nodes": [
            {"id": "trigger", "type": "trigger", "data": {"config": {"actionType": "trigger"}}},
            {"id": "action", "type": "action", "data": {"config": {"actionType": "db_insert"}}},
        ],
        "edges": [{"source": "trigger", "target": "action"}],
    }}
    assert fix_missing_trigger(wf) == 0
    assert len(wf["definition"]["nodes"]) == 2


def test_fix_missing_trigger_detects_actiontype_variant():
    """Node with type != 'trigger' but data.config.actionType == 'trigger'
    still counts as a trigger."""
    wf = {"definition": {
        "nodes": [
            {"id": "kickoff", "type": "unknown",
             "data": {"config": {"actionType": "trigger"}}},
            {"id": "action", "type": "action",
             "data": {"config": {"actionType": "db_insert"}}},
        ],
        "edges": [],
    }}
    assert fix_missing_trigger(wf) == 0  # already has trigger-shaped node


def test_fix_missing_trigger_empty_nodes_no_op():
    wf = {"definition": {"nodes": []}}
    assert fix_missing_trigger(wf) == 0


# ─── fix_orphan_navigate ────────────────────────────────────────────────

def test_fix_orphan_navigate_typo_repair():
    """Navigate to /scans/<uuid>/pricess should snap to /scans/[id]/prices."""
    uuid = "a5373987-702a-4469-8d1e-aae1fe18f4e4"
    schema = {
        "route": "/scans/[id]",
        "root": {
            "type": "Stack", "children": [
                {"type": "Button", "props": {"navigate": f"/scans/{uuid}/pricess"}},
            ],
        },
    }
    universe = ["/scans", "/scans/[id]", "/scans/[id]/prices", "/retailers"]
    assert fix_orphan_navigate(schema, universe) == 1
    btn = schema["root"]["children"][0]
    assert btn["props"]["navigate"] == "/scans/[id]/prices"


def test_fix_orphan_navigate_leaves_valid_alone():
    schema = {"route": "/x", "root": {
        "type": "Button", "props": {"navigate": "/scans"},
    }}
    universe = ["/scans", "/retailers"]
    assert fix_orphan_navigate(schema, universe) == 0


def test_fix_orphan_navigate_no_match_leaves_alone():
    schema = {"route": "/x", "root": {
        "type": "Button", "props": {"navigate": "/totally-different"},
    }}
    universe = ["/scans", "/retailers"]
    assert fix_orphan_navigate(schema, universe) == 0
    assert schema["root"]["props"]["navigate"] == "/totally-different"


# ─── run_auto_heal orchestrator ─────────────────────────────────────────

def _write_wf(dir_: Path, name: str, data: dict) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / name).write_text(json.dumps(data), encoding="utf-8")


def _write_report(dir_: Path, data: dict) -> None:
    (dir_ / "contracts").mkdir(parents=True, exist_ok=True)
    (dir_ / "contracts" / "proof_report.json").write_text(json.dumps(data), encoding="utf-8")


def test_run_auto_heal_no_report_noop(tmp_path: Path):
    result = run_auto_heal(tmp_path)
    assert result.iterations == 0
    assert result.converged is False


def test_run_auto_heal_already_passed_returns_immediately(tmp_path: Path):
    _write_report(tmp_path, {
        "passed": True, "error_count": 0, "warning_count": 0, "findings": []
    })
    result = run_auto_heal(tmp_path)
    assert result.iterations == 0
    assert result.converged is True


def test_run_auto_heal_fixes_sql_literals_and_converges(tmp_path: Path):
    # Broken workflow with a SQL literal.
    _write_wf(tmp_path / "workflows", "wf.json", {
        "definition": {
            "nodes": [
                {"id": "trigger", "type": "trigger",
                 "data": {"config": {"actionType": "trigger"}}},
                {"id": "act", "type": "action", "data": {"config": {
                    "actionType": "db_insert", "table": "x",
                    "values": {"ts": "CURRENT_TIMESTAMP"},
                }}},
            ],
            "edges": [{"source": "trigger", "target": "act"}],
        },
    })
    # Initial proof report says failed.
    _write_report(tmp_path, {
        "passed": False, "error_count": 1, "warning_count": 0,
        "findings": [{"severity": "error", "code": "sql-literal-in-value",
                      "message": "x", "workflow_file": "wf.json"}],
    })
    result = run_auto_heal(tmp_path, max_iterations=3)
    assert result.iterations >= 1
    assert result.fixes_by_type.get("sql-literal") == 1
    # The workflow file should now have $now instead of CURRENT_TIMESTAMP.
    wf = json.loads((tmp_path / "workflows" / "wf.json").read_text())
    val = wf["definition"]["nodes"][1]["data"]["config"]["values"]["ts"]
    assert val == "$now"


def test_run_auto_heal_stops_when_no_fixes_apply(tmp_path: Path):
    """When the report has errors but nothing our fixers can address, we
    bail out after one iteration without spinning."""
    _write_wf(tmp_path / "workflows", "wf.json", {
        "definition": {
            "nodes": [
                {"id": "trigger", "type": "trigger",
                 "data": {"config": {"actionType": "trigger"}}},
                {"id": "act", "type": "action", "data": {"config": {
                    "actionType": "db_insert", "table": "x",
                    "values": {"ts": "{{genuinely_undefined}}"},
                }}},
            ],
            "edges": [{"source": "trigger", "target": "act"}],
        },
    })
    _write_report(tmp_path, {
        "passed": False, "error_count": 1, "warning_count": 0,
        "findings": [{"severity": "error", "code": "undefined-ref",
                      "message": "x", "workflow_file": "wf.json"}],
    })
    result = run_auto_heal(tmp_path, max_iterations=3)
    # First iteration ran, no fixes applied, loop exited.
    assert result.iterations == 1
    assert result.fixes_by_type == {}


def test_persist_heal_report_writes_json(tmp_path: Path):
    _write_report(tmp_path, {
        "passed": True, "error_count": 0, "warning_count": 0, "findings": []
    })
    result = run_auto_heal(tmp_path)
    path = persist_heal_report(result, tmp_path)
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert "iterations" in loaded
    assert "converged" in loaded

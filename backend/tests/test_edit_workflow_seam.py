"""Structured editor for existing workflow JSON files.

Every test writes a tiny 3-node workflow (trigger → action → end) to a
tmp dir, applies a changeset, and asserts the on-disk file has exactly
the expected shape. Post-condition validation rejects changes that
break connectivity — those tests assert `success=False` AND that the
file was NOT modified."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.edit_workflow_seam import edit_workflow


def _write_wf(tmp_path: Path, wf_id: str = "process_cv", trigger_inputs=None) -> Path:
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / f"{wf_id}.json").write_text(json.dumps({
        "id": wf_id,
        "nodes": [
            {"id": "trigger", "type": "trigger", "next": "act",
             "data": {"config": {"inputs": trigger_inputs or []}}},
            {"id": "act", "type": "action", "next": "end",
             "data": {"actionType": "db_update",
                      "config": {"table": "candidates",
                                 "where": {"id": "{{input.candidateId}}"},
                                 "values": {"status": "'done'"}}}},
            {"id": "end", "type": "end"},
        ],
    }, indent=2))
    return tmp_path / "workflows" / f"{wf_id}.json"


def _read_wf(tmp_path: Path, wf_id: str = "process_cv") -> dict:
    return json.load(open(tmp_path / "workflows" / f"{wf_id}.json"))


# =========================================================================
# Happy path — each op works in isolation
# =========================================================================

def test_add_trigger_input(tmp_path):
    _write_wf(tmp_path)
    r = edit_workflow(str(tmp_path), "process_cv", {
        "add_trigger_input": {"name": "candidateId", "type": "uuid", "required": True},
    })
    assert r.success is True, r.error
    data = _read_wf(tmp_path)
    inputs = data["nodes"][0]["data"]["config"]["inputs"]
    assert {"name": "candidateId", "type": "uuid", "required": True} in inputs


def test_add_trigger_input_is_idempotent(tmp_path):
    _write_wf(tmp_path, trigger_inputs=[{"name": "candidateId", "type": "uuid", "required": True}])
    r = edit_workflow(str(tmp_path), "process_cv", {
        "add_trigger_input": {"name": "candidateId", "type": "uuid", "required": True},
    })
    assert r.success is True
    data = _read_wf(tmp_path)
    names = [i["name"] for i in data["nodes"][0]["data"]["config"]["inputs"]]
    assert names.count("candidateId") == 1  # not duplicated


def test_remove_trigger_input(tmp_path):
    _write_wf(tmp_path, trigger_inputs=[
        {"name": "candidateId", "type": "uuid"},
        {"name": "cvId", "type": "uuid"},
    ])
    r = edit_workflow(str(tmp_path), "process_cv", {"remove_trigger_input": "cvId"})
    assert r.success is True
    data = _read_wf(tmp_path)
    names = [i["name"] for i in data["nodes"][0]["data"]["config"]["inputs"]]
    assert names == ["candidateId"]


def test_set_step_config(tmp_path):
    """Update a WHERE-binding on an existing db_update step."""
    _write_wf(tmp_path, trigger_inputs=[{"name": "candidateId", "type": "uuid", "required": True}])
    r = edit_workflow(str(tmp_path), "process_cv", {
        "set_step_config": {"step_id": "act", "path": ["values", "cvSeen"], "value": "true"},
    })
    assert r.success is True
    data = _read_wf(tmp_path)
    assert data["nodes"][1]["data"]["config"]["values"]["cvSeen"] == "true"


def test_add_step_and_rewire(tmp_path):
    _write_wf(tmp_path, trigger_inputs=[{"name": "candidateId", "type": "uuid", "required": True}])
    r = edit_workflow(str(tmp_path), "process_cv", {
        "add_step": {
            "id": "log", "type": "action", "after": "act",
            "config": {"actionType": "send_notification", "message": "'CV processed'"},
        },
    })
    assert r.success is True, r.error
    data = _read_wf(tmp_path)
    ids = [s["id"] for s in data["nodes"]]
    assert ids == ["trigger", "act", "log", "end"]
    # act now points at log; log points at end.
    act = next(s for s in data["nodes"] if s["id"] == "act")
    log = next(s for s in data["nodes"] if s["id"] == "log")
    assert act["next"] == "log"
    assert log["next"] == "end"


def test_remove_step_rewires_predecessors(tmp_path):
    """Insert a middle step then remove it — the predecessor's `next`
    should be rewired to the successor."""
    _write_wf(tmp_path, trigger_inputs=[{"name": "candidateId", "type": "uuid", "required": True}])
    # Add a log step, then remove it.
    edit_workflow(str(tmp_path), "process_cv", {
        "add_step": {"id": "log", "type": "action", "after": "act",
                     "config": {"actionType": "send_notification"}},
    })
    r = edit_workflow(str(tmp_path), "process_cv", {"remove_step": "log"})
    assert r.success is True, r.error
    data = _read_wf(tmp_path)
    ids = [s["id"] for s in data["nodes"]]
    assert "log" not in ids
    act = next(s for s in data["nodes"] if s["id"] == "act")
    assert act["next"] == "end"


def test_rewire_next(tmp_path):
    _write_wf(tmp_path, trigger_inputs=[{"name": "candidateId", "type": "uuid", "required": True}])
    edit_workflow(str(tmp_path), "process_cv", {
        "add_step": {"id": "log", "type": "action", "after": "act",
                     "config": {"actionType": "send_notification"}},
    })
    # Skip log — rewire act → end.
    r = edit_workflow(str(tmp_path), "process_cv", {
        "rewire": {"step_id": "act", "next": "end"},
    })
    assert r.success is True
    data = _read_wf(tmp_path)
    act = next(s for s in data["nodes"] if s["id"] == "act")
    assert act["next"] == "end"


# =========================================================================
# Failure paths — validation rejects, file untouched
# =========================================================================

def test_unknown_workflow_returns_error(tmp_path):
    (tmp_path / "workflows").mkdir()
    r = edit_workflow(str(tmp_path), "nope", {"remove_trigger_input": "x"})
    assert r.success is False
    assert "not found" in r.error


def test_unknown_change_op_returns_error(tmp_path):
    _write_wf(tmp_path)
    r = edit_workflow(str(tmp_path), "process_cv", {"do_magic": {}})
    assert r.success is False
    assert "unknown change operation" in r.error


def test_remove_trigger_is_rejected(tmp_path):
    _write_wf(tmp_path)
    r = edit_workflow(str(tmp_path), "process_cv", {"remove_step": "trigger"})
    assert r.success is False
    assert "trigger" in r.error


def test_add_step_after_missing_predecessor_rejected(tmp_path):
    _write_wf(tmp_path)
    r = edit_workflow(str(tmp_path), "process_cv", {
        "add_step": {"id": "log", "type": "action", "after": "nope",
                     "config": {}},
    })
    assert r.success is False
    assert "predecessor" in r.error


def test_broken_connectivity_rollbacks_file(tmp_path):
    """A rewire that leaves the workflow disconnected must be rejected
    AND leave the file unchanged."""
    path = _write_wf(tmp_path, trigger_inputs=[
        {"name": "candidateId", "type": "uuid", "required": True},
    ])
    before = path.read_text()
    r = edit_workflow(str(tmp_path), "process_cv", {
        # Point act at a non-existent id → workflow_dangling_target violation.
        "rewire": {"step_id": "act", "next": "no_such_step"},
    })
    assert r.success is False
    assert r.violations
    assert path.read_text() == before, "file must be untouched on validation failure"


def test_multiple_changes_applied_in_order(tmp_path):
    _write_wf(tmp_path)
    r = edit_workflow(str(tmp_path), "process_cv", {
        "add_trigger_input": {"name": "candidateId", "type": "uuid", "required": True},
        "set_step_config": {"step_id": "act", "path": ["values", "processed"],
                            "value": "true"},
    })
    assert r.success is True
    assert set(r.applied) == {"add_trigger_input", "set_step_config"}
    data = _read_wf(tmp_path)
    assert data["nodes"][1]["data"]["config"]["values"]["processed"] == "true"

"""Tests for the undefined-ref proof-leak fix (workflow_variable_reconcile)."""
from __future__ import annotations

import json
from pathlib import Path

from services.workflow_variable_reconcile import reconcile_workflow_variables


def _mk(tmp_path: Path, wf: dict, plan: dict | None = None,
        name: str = "wf.json") -> Path:
    root = tmp_path / "app"
    (root / "workflows").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    if plan is not None:
        (root / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))
    (root / "workflows" / name).write_text(json.dumps(wf))
    return root


def _read(root: Path, name: str = "wf.json") -> dict:
    return json.loads((root / "workflows" / name).read_text())


_PLAN = {"data_models": [
    {"name": "WaitlistEntry", "fields": [
        {"name": "status", "type": "varchar",
         "enum_values": ["waiting", "notified", "expired"]}]},
    {"name": "Booking", "fields": [
        {"name": "status", "type": "varchar",
         "enum_values": ["confirmed", "cancelled"]}]},
]}


def _sched_wf(steps):
    return {"id": "w", "name": "WaitlistExpiryCheckWorkflow",
            "definition": {"trigger": {"type": "schedule"}, "steps": steps}}


# ─────────── C: self-referential enum literal ───────────

def test_self_ref_status_becomes_step_matched_literal(tmp_path):
    root = _mk(tmp_path, _sched_wf([
        {"id": "expire_entries", "type": "action", "config": {
            "actionType": "db_update", "table": "waitlist_entries",
            "values": {"status": "{{status}}"},
            "where": {"status": "notified"}}},
    ]), plan=_PLAN)
    rep = reconcile_workflow_variables(root)
    assert rep["files"][0]["literals"] == [
        {"step": "expire_entries", "column": "status", "literal": "expired"}]
    step = _read(root)["definition"]["steps"][0]
    assert step["config"]["values"]["status"] == "expired"


def test_self_ref_matched_from_workflow_name(tmp_path):
    wf = {"id": "c", "name": "CancelBookingWorkflow",
          "definition": {"trigger": {"type": "manual"}, "steps": [
              {"id": "update_row", "type": "action", "config": {
                  "actionType": "db_update", "table": "bookings",
                  "values": {"status": "{{status}}"},
                  "where": {"id": "{{bookingId}}"}}}]}}
    root = _mk(tmp_path, wf, plan=_PLAN)
    reconcile_workflow_variables(root)
    step = _read(root)["definition"]["steps"][0]
    assert step["config"]["values"]["status"] == "cancelled"


def test_self_ref_without_enum_left_alone_but_declared(tmp_path):
    wf = {"id": "c", "name": "UpdateThingWorkflow",
          "definition": {"trigger": {"type": "manual"}, "steps": [
              {"id": "u", "type": "action", "config": {
                  "actionType": "db_update", "table": "things",
                  "values": {"note": "{{note}}"}}}]}}
    root = _mk(tmp_path, wf, plan={"data_models": []})
    rep = reconcile_workflow_variables(root)
    step = _read(root)["definition"]["steps"][0]
    assert step["config"]["values"]["note"] == "{{note}}"   # untouched
    assert "note" in rep["files"][0]["declared"]            # declared instead


# ─────────── B: query-output pairing ───────────

def test_result_root_pairs_with_last_preceding_query(tmp_path):
    root = _mk(tmp_path, _sched_wf([
        {"id": "find_expired", "type": "action", "config": {
            "actionType": "db_query", "table": "waitlist_entries",
            "where": {"status": "notified"}}},
        {"id": "find_next", "type": "action", "config": {
            "actionType": "db_query", "table": "waitlist_entries",
            "where": {"status": "waiting"}}},
        {"id": "notify_next", "type": "action", "config": {
            "actionType": "db_update", "table": "waitlist_entries",
            "where": {"id": "{{nextEntry.id}}"}}},
    ]), plan=_PLAN)
    rep = reconcile_workflow_variables(root)
    assert rep["files"][0]["output_vars"] == [
        {"query": "find_next", "outputVar": "nextEntry"}]
    steps = _read(root)["definition"]["steps"]
    assert steps[1]["config"]["outputVar"] == "nextEntry"
    assert "outputVar" not in steps[0]["config"]  # unused query untouched


def test_column_named_root_never_becomes_output_var(tmp_path):
    root = _mk(tmp_path, _sched_wf([
        {"id": "find_rows", "type": "action", "config": {
            "actionType": "db_query", "table": "waitlist_entries",
            "where": {"status": "waiting"}}},
        {"id": "update", "type": "action", "config": {
            "actionType": "db_update", "table": "waitlist_entries",
            "values": {"status": "{{unknownThing}}", "note": "{{status}}"}}},
    ]), plan={"data_models": []})
    rep = reconcile_workflow_variables(root)
    # `status` is a written column → excluded; `unknownThing` pairs.
    assert rep["files"][0]["output_vars"] == [
        {"query": "find_rows", "outputVar": "unknownThing"}]


# ─────────── A: final free-ref declaration ───────────

def test_late_introduced_ref_declared_on_api_event(tmp_path):
    wf = {"id": "s", "name": "ScheduleInterview",
          "processVariables": [{"name": "candidateId", "type": "uuid"}],
          "definition": {"trigger": {"type": "api_event"}, "nodes": [
              {"id": "insert", "type": "action", "data": {"config": {
                  "actionType": "db_insert", "table": "interviews",
                  "values": {"driveStageId": "{{driveStageId}}",
                             "candidateId": "{{candidateId}}"}}}}]}}
    root = _mk(tmp_path, wf, plan={"data_models": []})
    rep = reconcile_workflow_variables(root)
    assert "driveStageId" in rep["files"][0]["declared"]
    names = {p["name"] for p in _read(root)["processVariables"]}
    assert {"candidateId", "driveStageId"} <= names


def test_schedule_trigger_leftover_not_declared(tmp_path):
    root = _mk(tmp_path, _sched_wf([
        {"id": "u", "type": "action", "config": {
            "actionType": "db_update", "table": "things",
            "values": {"status": "{{mystery}}"}}},
    ]), plan={"data_models": []})
    rep = reconcile_workflow_variables(root)
    # No query to pair with, schedule trigger carries no payload —
    # the ref stays undeclared for the validator to flag.
    assert not rep["files"] or not rep["files"][0]["declared"]


def test_reconcile_is_idempotent(tmp_path):
    root = _mk(tmp_path, _sched_wf([
        {"id": "expire_entries", "type": "action", "config": {
            "actionType": "db_update", "table": "waitlist_entries",
            "values": {"status": "{{status}}"}}},
    ]), plan=_PLAN)
    assert reconcile_workflow_variables(root)["files"]
    assert reconcile_workflow_variables(root)["files"] == []

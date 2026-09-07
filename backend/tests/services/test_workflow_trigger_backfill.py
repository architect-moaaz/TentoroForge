"""REM-4 — trigger-contract backfill for pre-eventing workflow JSONs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.workflow_trigger_backfill import backfill_workflow_triggers


def _app(tmp_path: Path, plan_workflows: list[dict], files: dict[str, dict]) -> Path:
    contracts = tmp_path / "src" / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "plan.json").write_text(json.dumps({"workflows": plan_workflows}), encoding="utf-8")
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    for name, doc in files.items():
        (wf_dir / name).write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_event_trigger_backfilled(tmp_path):
    root = _app(
        tmp_path,
        [{"name": "NotifyOnOrder",
          "trigger": {"type": "db_change", "entity": "Order", "on": "created"}}],
        {"NotifyOnOrder.json": {"id": "NotifyOnOrder", "definition": {"nodes": []}}},
    )
    assert backfill_workflow_triggers(str(root)) == 1
    doc = json.loads((root / "workflows" / "NotifyOnOrder.json").read_text(encoding="utf-8"))
    assert doc["trigger"] == {"kind": "event", "event": "order.created"}


def test_schedule_trigger_backfilled_via_name_match(tmp_path):
    root = _app(
        tmp_path,
        [{"name": "DailyDigest", "trigger": {"type": "schedule", "every": "daily"}}],
        {"digest.json": {"id": "wf-123", "name": "DailyDigest", "definition": {}}},
    )
    assert backfill_workflow_triggers(str(root)) == 1
    doc = json.loads((root / "workflows" / "digest.json").read_text(encoding="utf-8"))
    assert doc["trigger"]["kind"] == "schedule"
    assert doc["trigger"]["cron"]


def test_existing_trigger_never_touched(tmp_path):
    existing = {"kind": "event", "event": "custom.event"}
    root = _app(
        tmp_path,
        [{"name": "NotifyOnOrder",
          "trigger": {"type": "db_change", "entity": "Order", "on": "created"}}],
        {"NotifyOnOrder.json": {"id": "NotifyOnOrder", "trigger": existing}},
    )
    assert backfill_workflow_triggers(str(root)) == 0
    doc = json.loads((root / "workflows" / "NotifyOnOrder.json").read_text(encoding="utf-8"))
    assert doc["trigger"] == existing


def test_manual_workflow_is_noop(tmp_path):
    root = _app(
        tmp_path,
        [{"name": "CreateTask", "trigger": {"type": "manual"}}],
        {"CreateTask.json": {"id": "CreateTask"}},
    )
    assert backfill_workflow_triggers(str(root)) == 0
    assert "trigger" not in json.loads((root / "workflows" / "CreateTask.json").read_text(encoding="utf-8"))


def test_idempotent_second_run(tmp_path):
    root = _app(
        tmp_path,
        [{"name": "NotifyOnOrder",
          "trigger": {"type": "db_change", "entity": "Order", "on": "created"}}],
        {"NotifyOnOrder.json": {"id": "NotifyOnOrder"}},
    )
    assert backfill_workflow_triggers(str(root)) == 1
    first = (root / "workflows" / "NotifyOnOrder.json").read_text(encoding="utf-8")
    assert backfill_workflow_triggers(str(root)) == 0
    assert (root / "workflows" / "NotifyOnOrder.json").read_text(encoding="utf-8") == first


def test_malformed_file_skipped_others_patched(tmp_path):
    root = _app(
        tmp_path,
        [{"name": "NotifyOnOrder",
          "trigger": {"type": "db_change", "entity": "Order", "on": "created"}}],
        {"NotifyOnOrder.json": {"id": "NotifyOnOrder"}},
    )
    (root / "workflows" / "broken.json").write_text("{not json", encoding="utf-8")
    assert backfill_workflow_triggers(str(root)) == 1


@pytest.mark.parametrize("missing", ["workflows", "plan"])
def test_missing_pieces_graceful(tmp_path, missing):
    if missing == "workflows":
        contracts = tmp_path / "src" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "plan.json").write_text(json.dumps({"workflows": []}), encoding="utf-8")
    else:
        (tmp_path / "workflows").mkdir()
    assert backfill_workflow_triggers(str(tmp_path)) == 0

"""workflow_input_map_backfill — the fix for the 'nothing happens after
I save' bug we found in xnoo9mrj. The action-contract already knew the
form fields were unmapped; nothing was acting on the signal."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from services.workflow_input_map_backfill import (
    backfill_workflow_input_maps,
    is_input_map_backfill_enabled,
)


def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2))


def _drives_workflow(values: dict) -> dict:
    """Match the shape of the real ``createdrive.json`` we found in
    xnoo9mrj — a data.config.values map inside a nested definition."""
    return {
        "id": "createdrive",
        "name": "CreateDrive",
        "definition": {
            "trigger": {"type": "manual"},
            "steps": [],
            "nodes": [
                {"id": "trigger", "type": "trigger",
                 "data": {"nodeType": "trigger",
                          "config": {"nodeType": "trigger"}}},
                {"id": "insert_drive", "type": "action",
                 "data": {
                     "label": "Insert Drive",
                     "nodeType": "action",
                     "config": {
                         "table":      "drives",
                         "values":     dict(values),
                         "actionType": "db_insert",
                         "nodeType":   "action",
                     },
                 }},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"source": "trigger", "target": "insert_drive"},
                {"source": "insert_drive", "target": "end"},
            ],
        },
    }


def _drives_action(unmapped, mapped=None):
    return {
        "file":            "drives/new.json",
        "kind":            "form_submit",
        "label":           "Create Drive",
        "workflow_ref":    "CreateDrive",
        "workflow_id":     "createdrive",
        "resolved":        True,
        "input_map":       dict(mapped or {"status": "status"}),
        "unmapped_fields": list(unmapped),
    }


# ── happy path ─────────────────────────────────────────────────

def test_backfills_every_unmapped_field(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action(
            ["title", "location", "openDate", "headcount"]
        )],
    })
    _write(tmp_path, "workflows/createdrive.json",
           _drives_workflow({"status": "draft"}))

    summary = backfill_workflow_input_maps(tmp_path)

    assert summary["actions_backfilled"] == 1
    assert summary["fields_added"] == 4
    assert "createdrive" in summary["workflows_touched"]

    wf = json.loads(
        (tmp_path / "workflows/createdrive.json").read_text()
    )
    insert = next(n for n in wf["definition"]["nodes"]
                  if n["id"] == "insert_drive")
    values = insert["data"]["config"]["values"]
    assert values["status"]   == "draft"                   # existing preserved
    assert values["title"]    == "{{title}}"
    assert values["location"] == "{{location}}"
    assert values["openDate"] == "{{openDate}}"
    assert values["headcount"] == "{{headcount}}"


def test_updates_action_contract_after_backfill(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action(["title", "location"])],
    })
    _write(tmp_path, "workflows/createdrive.json",
           _drives_workflow({"status": "draft"}))

    backfill_workflow_input_maps(tmp_path)

    ac = json.loads(
        (tmp_path / "contracts/action-contract.json").read_text()
    )
    action = ac["actions"][0]
    assert action["unmapped_fields"] == []
    assert action["input_map"] == {
        "status": "status", "title": "title", "location": "location",
    }


# ── idempotency ────────────────────────────────────────────────

def test_second_run_is_noop(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action(["title"])],
    })
    _write(tmp_path, "workflows/createdrive.json",
           _drives_workflow({"status": "draft"}))

    first  = backfill_workflow_input_maps(tmp_path)
    second = backfill_workflow_input_maps(tmp_path)

    assert first["fields_added"] == 1
    assert second["fields_added"] == 0
    assert second["actions_backfilled"] == 0


def test_already_present_key_is_not_overwritten(tmp_path):
    """If someone manually mapped title to a literal or a different
    expression, we don't clobber it."""
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action(["title", "location"])],
    })
    _write(tmp_path, "workflows/createdrive.json", _drives_workflow({
        "status": "draft",
        "title":  "hardcoded",   # already there
    }))

    backfill_workflow_input_maps(tmp_path)
    wf = json.loads(
        (tmp_path / "workflows/createdrive.json").read_text()
    )
    insert = next(n for n in wf["definition"]["nodes"]
                  if n["id"] == "insert_drive")
    assert insert["data"]["config"]["values"]["title"] == "hardcoded"
    # But location was still missing, so it was added.
    assert insert["data"]["config"]["values"]["location"] == "{{location}}"


# ── mutation-step selection ────────────────────────────────────

def test_prefers_db_insert_over_db_update(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action(["title"])],
    })
    _write(tmp_path, "workflows/createdrive.json", {
        "id": "createdrive", "name": "CreateDrive",
        "definition": {
            "nodes": [
                {"id": "u", "data": {"config": {
                    "values": {}, "actionType": "db_update"}}},
                {"id": "i", "data": {"config": {
                    "values": {}, "actionType": "db_insert"}}},
            ],
        },
    })
    backfill_workflow_input_maps(tmp_path)
    wf = json.loads(
        (tmp_path / "workflows/createdrive.json").read_text()
    )
    insert = next(n for n in wf["definition"]["nodes"] if n["id"] == "i")
    update = next(n for n in wf["definition"]["nodes"] if n["id"] == "u")
    assert insert["data"]["config"]["values"] == {"title": "{{title}}"}
    assert update["data"]["config"]["values"] == {}


def test_falls_back_to_db_update_when_no_insert(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action(["title"])],
    })
    _write(tmp_path, "workflows/createdrive.json", {
        "id": "createdrive", "name": "CreateDrive",
        "definition": {
            "nodes": [
                {"id": "u", "data": {"config": {
                    "values": {}, "actionType": "db_update"}}},
            ],
        },
    })
    backfill_workflow_input_maps(tmp_path)
    wf = json.loads(
        (tmp_path / "workflows/createdrive.json").read_text()
    )
    u = next(n for n in wf["definition"]["nodes"] if n["id"] == "u")
    assert u["data"]["config"]["values"] == {"title": "{{title}}"}


# ── skip conditions ────────────────────────────────────────────

def test_no_action_contract_returns_zero_summary(tmp_path):
    result = backfill_workflow_input_maps(tmp_path)
    assert result["actions_backfilled"] == 0
    assert result["fields_added"] == 0


def test_action_with_empty_unmapped_fields_skipped(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action([])],
    })
    _write(tmp_path, "workflows/createdrive.json",
           _drives_workflow({"status": "draft"}))
    result = backfill_workflow_input_maps(tmp_path)
    assert result["fields_added"] == 0


def test_missing_workflow_file_silently_skipped(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action(["title"])],
    })
    # NO workflow file written.
    result = backfill_workflow_input_maps(tmp_path)
    assert result["fields_added"] == 0
    assert result["actions_backfilled"] == 0


def test_non_form_submit_actions_ignored(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [{"kind": "navigate", "unmapped_fields": ["x"]}],
    })
    result = backfill_workflow_input_maps(tmp_path)
    assert result["fields_added"] == 0


def test_workflow_with_no_mutation_step_skipped(tmp_path):
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [_drives_action(["title"])],
    })
    _write(tmp_path, "workflows/createdrive.json", {
        "id": "createdrive", "name": "CreateDrive",
        "definition": {
            "nodes": [
                {"id": "t", "type": "trigger"},
                {"id": "n", "data": {"config": {
                    "actionType": "send_notification"}}},
                {"id": "e", "type": "end"},
            ],
        },
    })
    result = backfill_workflow_input_maps(tmp_path)
    assert result["fields_added"] == 0


# ── env gate ───────────────────────────────────────────────────
# The gate is ON by default now: the pipeline already recorded
# unmapped_fields in contracts/action-contract.json, so the backfill
# only had to be run to consume them and stop dropping form fields.


def test_env_gate_on_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_INPUT_MAP_BACKFILL", raising=False)
    assert is_input_map_backfill_enabled() is True


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_env_gate_truthy(monkeypatch, val):
    monkeypatch.setenv("FORGE_INPUT_MAP_BACKFILL", val)
    assert is_input_map_backfill_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off"])
def test_env_gate_falsy_opts_out(monkeypatch, val):
    monkeypatch.setenv("FORGE_INPUT_MAP_BACKFILL", val)
    assert is_input_map_backfill_enabled() is False


def test_kebab_case_workflow_id_resolves_to_pascal_case_file(tmp_path):
    """Real xnoo9mrj/v3azan7i regression: action-contract wrote
    ``update-candidateprofile`` but the file is
    ``UpdateCandidateProfile.json``. The resolver normalizes both sides."""
    _write(tmp_path, "contracts/action-contract.json", {
        "actions": [{
            "file":            "candidates/[id]/edit.json",
            "kind":            "form_submit",
            "workflow_id":     "update-candidateprofile",
            "input_map":       {},
            "unmapped_fields": ["fullName"],
        }],
    })
    _write(tmp_path, "workflows/UpdateCandidateProfile.json",
           _drives_workflow({}))
    r = backfill_workflow_input_maps(tmp_path)
    assert r["fields_added"] == 1
    assert r["workflows_touched"] == ["update-candidateprofile"]

"""Tests for workflow_form_field_pruner.

The CRUD workflow generator writes plain-string `{"col": "col"}` values that
name process variables. When the dispatching form doesn't collect one of those
columns (e.g. `isVerified` / `verifiedAt` on Carer — system-managed), the
runtime dispatch has no value → the db_insert writes undefined to a typed
column → Postgres rejects → silent insert failure.

This pruner cross-references each workflow's mutation values against the
UNION of input_maps of every action-contract entry dispatching it. Any values
key whose RHS names a process variable NOT in that union is dropped so the
DB default / NULL takes over.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.workflow_form_field_pruner import prune_workflow_form_fields


def _wf(process_vars: list[str], values: dict) -> dict:
    return {
        "id": "create-carer",
        "name": "CreateCarer",
        "processVariables": [{"name": n, "type": "string"} for n in process_vars],
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [
                {"id": "trigger", "type": "trigger", "data": {"config": {"type": "manual"}}},
                {
                    "id": "db_insert",
                    "type": "action",
                    "data": {
                        "config": {
                            "actionType": "db_insert",
                            "table": "carers",
                            "values": values,
                        },
                        "label": "Create",
                    },
                },
                {"id": "end", "type": "end", "data": {"config": {}}},
            ],
            "edges": [
                {"source": "trigger", "target": "db_insert"},
                {"source": "db_insert", "target": "end"},
            ],
        },
    }


def _write_wf(root: Path, name: str, wf: dict) -> None:
    (root / "workflows").mkdir(exist_ok=True)
    (root / "workflows" / f"{name}.json").write_text(json.dumps(wf))


def _write_action_contract(root: Path, actions: list[dict]) -> None:
    (root / "contracts").mkdir(exist_ok=True)
    (root / "contracts" / "action-contract.json").write_text(
        json.dumps({"version": 1, "actions": actions})
    )


# ────────────────────────────────────────────────────────────
# core case — the Carer bug
# ────────────────────────────────────────────────────────────


def test_drops_plain_string_value_not_in_form_input_map(tmp_path):
    # Form collects userId + bio; workflow ALSO tries to write isVerified.
    # isVerified is a declared process var but no form provides it.
    wf = _wf(
        ["userId", "bio", "isVerified", "verifiedAt"],
        {
            "userId": "userId",
            "bio": "bio",
            "isVerified": "isVerified",
            "verifiedAt": "verifiedAt",
        },
    )
    _write_wf(tmp_path, "CreateCarer", wf)
    _write_action_contract(
        tmp_path,
        [
            {
                "file": "carers/new.json",
                "kind": "form_submit",
                "workflow_ref": "CreateCarer",
                "workflow_id": "create-carer",
                "resolved": True,
                "input_map": {"userId": "userId", "bio": "bio"},
            }
        ],
    )

    result = prune_workflow_form_fields(str(tmp_path))
    written = json.loads((tmp_path / "workflows" / "CreateCarer.json").read_text())
    values = written["definition"]["nodes"][1]["data"]["config"]["values"]
    assert "isVerified" not in values
    assert "verifiedAt" not in values
    assert values == {"userId": "userId", "bio": "bio"}
    assert result["values_removed"] == 2


def test_keeps_value_when_form_collects_it(tmp_path):
    wf = _wf(["email"], {"email": "email"})
    _write_wf(tmp_path, "CreateUser", wf)
    _write_action_contract(
        tmp_path,
        [
            {
                "file": "users/new.json",
                "kind": "form_submit",
                "workflow_id": "create-user",
                "resolved": True,
                "input_map": {"email": "email"},
            }
        ],
    )
    result = prune_workflow_form_fields(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text())[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert values == {"email": "email"}
    assert result["values_removed"] == 0


def test_keeps_literal_value_not_a_process_var(tmp_path):
    # `"role": "carer"` — RHS is a literal string, NOT a process-var name.
    # Even though "carer" isn't in input_map, we don't touch it.
    wf = _wf(["userId"], {"userId": "userId", "role": "carer"})
    _write_wf(tmp_path, "CreateCarer", wf)
    _write_action_contract(
        tmp_path,
        [{"file": "carers/new.json", "kind": "form_submit", "workflow_id": "create-carer", "resolved": True, "input_map": {"userId": "userId"}}],
    )
    prune_workflow_form_fields(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateCarer.json").read_text())[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert values["role"] == "carer"


def test_keeps_mustache_bindings_untouched(tmp_path):
    # Mustache-mode values are handled by workflow_values_clean_guard; leave
    # them alone here to avoid double-touching the same bug class.
    wf = _wf(["email"], {"email": "email", "junk": "{{junk}}"})
    _write_wf(tmp_path, "CreateUser", wf)
    _write_action_contract(
        tmp_path,
        [{"file": "users/new.json", "kind": "form_submit", "workflow_id": "create-user", "resolved": True, "input_map": {"email": "email"}}],
    )
    prune_workflow_form_fields(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text())[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert values["junk"] == "{{junk}}"


def test_unions_input_maps_across_multiple_forms(tmp_path):
    # CreateUser is dispatched from admins/new (collects email + name) AND
    # admins/link (collects userId only). Union means email/name/userId are
    # all "form-provided" — none should be dropped.
    wf = _wf(["email", "name", "userId"], {"email": "email", "name": "name", "userId": "userId"})
    _write_wf(tmp_path, "CreateUser", wf)
    _write_action_contract(
        tmp_path,
        [
            {"file": "admins/new.json",  "kind": "form_submit", "workflow_id": "create-user", "resolved": True, "input_map": {"email": "email", "name": "name"}},
            {"file": "admins/link.json", "kind": "form_submit", "workflow_id": "create-user", "resolved": True, "input_map": {"userId": "userId"}},
        ],
    )
    prune_workflow_form_fields(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text())[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert set(values.keys()) == {"email", "name", "userId"}


def test_no_action_contract_is_safe_noop(tmp_path):
    wf = _wf(["email"], {"email": "email", "phantom": "phantom"})
    _write_wf(tmp_path, "CreateUser", wf)
    # No action-contract file at all.
    result = prune_workflow_form_fields(str(tmp_path))
    assert result["values_removed"] == 0
    values = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text())[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert values == {"email": "email", "phantom": "phantom"}


def test_workflow_with_no_dispatching_form_is_untouched(tmp_path):
    # An orphan workflow (no form_submit points at it) leaves the values map
    # alone — we can't say what the form-vs-not-form split is.
    wf = _wf(["email"], {"email": "email", "isVerified": "isVerified"})
    _write_wf(tmp_path, "CreateUser", wf)
    _write_action_contract(
        tmp_path,
        [
            {"file": "carers/new.json", "kind": "form_submit", "workflow_id": "create-carer", "resolved": True, "input_map": {"userId": "userId"}},
        ],
    )
    prune_workflow_form_fields(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text())[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert "isVerified" in values  # left alone


def test_idempotent(tmp_path):
    wf = _wf(["userId", "isVerified"], {"userId": "userId", "isVerified": "isVerified"})
    _write_wf(tmp_path, "CreateCarer", wf)
    _write_action_contract(
        tmp_path,
        [{"file": "carers/new.json", "kind": "form_submit", "workflow_id": "create-carer", "resolved": True, "input_map": {"userId": "userId"}}],
    )
    first = prune_workflow_form_fields(str(tmp_path))
    second = prune_workflow_form_fields(str(tmp_path))
    assert first["values_removed"] == 1
    assert second["values_removed"] == 0


def test_matches_workflow_by_normalized_id(tmp_path):
    # Action-contract may say `workflow_id: "create-carer"` while the file
    # is `CreateCarer.json`. Resolve via case/dash-insensitive match.
    wf = _wf(["userId", "isVerified"], {"userId": "userId", "isVerified": "isVerified"})
    _write_wf(tmp_path, "CreateCarer", wf)
    _write_action_contract(
        tmp_path,
        [{"file": "carers/new.json", "kind": "form_submit", "workflow_id": "createcarer", "resolved": True, "input_map": {"userId": "userId"}}],
    )
    result = prune_workflow_form_fields(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateCarer.json").read_text())[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert "isVerified" not in values
    assert result["values_removed"] == 1


def test_updates_db_update_values_too(tmp_path):
    wf = _wf(["id", "userId", "isVerified"], {})
    wf["definition"]["nodes"][1]["data"]["config"] = {
        "actionType": "db_update",
        "table": "carers",
        "where": {"id": "id"},
        "values": {"userId": "userId", "isVerified": "isVerified"},
    }
    _write_wf(tmp_path, "UpdateCarer", wf)
    _write_action_contract(
        tmp_path,
        [{"file": "carers/[id]/edit.json", "kind": "form_submit", "workflow_id": "update-carer", "resolved": True, "input_map": {"userId": "userId"}}],
    )
    prune_workflow_form_fields(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "UpdateCarer.json").read_text())[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert "isVerified" not in values

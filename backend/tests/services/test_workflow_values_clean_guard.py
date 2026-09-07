"""Tests for workflow_values_clean_guard.

The workflow_input_map_backfill can accumulate ``{{fieldName}}`` entries in a
mutation node's ``values`` map that don't correspond to any process variable —
for example when action-contract's ``unmapped_fields`` names a column that the
form doesn't collect and no earlier pass filters it out. At runtime the FEEL-
lite interpolator resolves those to empty/undefined, and the db_insert then
crashes on the DB type cast (e.g. `""` → boolean).

The guard walks every workflow's mutation nodes and removes any values-map
key whose right-hand side is a `{{name}}` binding where `name` is neither a
declared processVariable nor a static value.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.workflow_values_clean_guard import clean_workflow_values


def _wf(process_vars: list[str], values: dict) -> dict:
    return {
        "id": "create-user",
        "name": "CreateUser",
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
                            "table": "users",
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


def _write(tmp_path: Path, name: str, wf: dict) -> Path:
    wdir = tmp_path / "workflows"
    wdir.mkdir(exist_ok=True)
    p = wdir / f"{name}.json"
    p.write_text(json.dumps(wf), encoding="utf-8")
    return p


def test_removes_mustache_key_not_in_process_vars(tmp_path):
    # `isActive` is inside values as a `{{isActive}}` binding but there's no
    # processVariable named `isActive`. It must be dropped.
    wf = _wf(
        ["email", "password"],
        {"email": "email", "password": "password", "isActive": "{{isActive}}"},
    )
    _write(tmp_path, "CreateUser", wf)
    summary = clean_workflow_values(str(tmp_path))
    written = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text(encoding="utf-8"))
    values = written["definition"]["nodes"][1]["data"]["config"]["values"]
    assert "isActive" not in values
    assert values == {"email": "email", "password": "password"}
    assert summary["workflows_touched"] == ["CreateUser"]
    assert summary["values_removed"] == 1


def test_keeps_plain_string_mapping_even_without_process_var(tmp_path):
    # `"role": "role"` is the CRUD-generator format: RHS names a process var
    # (not a mustache). If the plain-string form references an unknown var
    # we could ALSO drop it, but the pipeline emits process vars from the
    # planner post-hoc — so only drop the mustache form (which is what the
    # backfill emits when it can't verify presence). Conservative.
    wf = _wf(
        ["email"],
        {"email": "email", "role": "role"},
    )
    _write(tmp_path, "CreateUser", wf)
    clean_workflow_values(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text(encoding="utf-8"))[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert values == {"email": "email", "role": "role"}


def test_keeps_mustache_binding_that_maps_to_declared_process_var(tmp_path):
    wf = _wf(
        ["email", "isActive"],
        {"email": "email", "isActive": "{{isActive}}"},
    )
    _write(tmp_path, "CreateUser", wf)
    clean_workflow_values(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text(encoding="utf-8"))[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert "isActive" in values


def test_keeps_static_literal_values(tmp_path):
    # A hard-coded string like "user" isn't a `{{...}}` binding — leave it.
    wf = _wf(
        ["email"],
        {"email": "email", "role": "customer"},
    )
    _write(tmp_path, "CreateUser", wf)
    clean_workflow_values(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text(encoding="utf-8"))[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert values["role"] == "customer"


def test_no_workflows_dir_is_noop(tmp_path):
    summary = clean_workflow_values(str(tmp_path))
    assert summary["workflows_scanned"] == 0
    assert summary["values_removed"] == 0


def test_idempotent(tmp_path):
    wf = _wf(
        ["email"],
        {"email": "email", "junk": "{{junk}}"},
    )
    _write(tmp_path, "CreateUser", wf)
    first = clean_workflow_values(str(tmp_path))
    second = clean_workflow_values(str(tmp_path))
    assert first["values_removed"] == 1
    assert second["values_removed"] == 0


def test_handles_db_update_node_too(tmp_path):
    wf = _wf(["id", "email"], {})
    wf["definition"]["nodes"][1]["data"]["config"] = {
        "actionType": "db_update",
        "table": "users",
        "where": {"id": "id"},
        "values": {"email": "email", "stale": "{{stale}}"},
    }
    _write(tmp_path, "UpdateUser", wf)
    clean_workflow_values(str(tmp_path))
    values = json.loads((tmp_path / "workflows" / "UpdateUser.json").read_text(encoding="utf-8"))[
        "definition"
    ]["nodes"][1]["data"]["config"]["values"]
    assert "stale" not in values
    assert values["email"] == "email"


def test_walks_multiple_mutation_nodes(tmp_path):
    wf = _wf(["email"], {"email": "email"})
    # Add a SECOND mutation node with a stale mustache.
    wf["definition"]["nodes"].insert(
        2,
        {
            "id": "audit",
            "type": "action",
            "data": {
                "config": {
                    "actionType": "db_insert",
                    "table": "audit",
                    "values": {"action": "{{missing}}"},
                },
                "label": "Audit",
            },
        },
    )
    _write(tmp_path, "CreateUser", wf)
    summary = clean_workflow_values(str(tmp_path))
    written = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text(encoding="utf-8"))
    assert written["definition"]["nodes"][1]["data"]["config"]["values"] == {
        "email": "email"
    }
    assert written["definition"]["nodes"][2]["data"]["config"]["values"] == {}
    assert summary["values_removed"] == 1

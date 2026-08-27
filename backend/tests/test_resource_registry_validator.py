"""Tests for the canonical-registry reference validator (spec P5).

`validate_registry(output_dir)` asserts the registry is internally consistent:
every relationship / fk / interaction reference resolves to a real registry
entity id, and every interaction workflow resolves to a real workflow.
"""
import json
import os

from services.resource_registry_validator import validate_registry


def _write_registry(output_dir: str, registry: dict) -> None:
    cdir = os.path.join(output_dir, "contracts")
    os.makedirs(cdir, exist_ok=True)
    with open(os.path.join(cdir, "resource-registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)


def _write_workflow(output_dir: str, stem: str, doc: dict) -> None:
    wdir = os.path.join(output_dir, "workflows")
    os.makedirs(wdir, exist_ok=True)
    with open(os.path.join(wdir, f"{stem}.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)


def _clean_registry() -> dict:
    return {
        "version": 1,
        "entities": {
            "Equipment": {
                "id": "equipment",
                "name": "Equipment",
                "table": "equipment",
                "slug": "equipment",
                "columns": [
                    {"name": "status", "type": "varchar", "notNull": False,
                     "fk": None, "enum": None},
                ],
                "fks": [],
            },
            "MaintenanceLog": {
                "id": "maintenance-log",
                "name": "MaintenanceLog",
                "table": "maintenanceLogs",
                "slug": "maintenance-logs",
                "columns": [
                    {"name": "equipmentId", "type": "uuid", "notNull": True,
                     "fk": "equipment", "enum": None},
                ],
                "fks": [{"column": "equipmentId", "targetEntityId": "equipment"}],
            },
        },
        "relationships": [
            {"from": "maintenance-log", "to": "equipment",
             "type": "many-to-one", "fkColumn": "equipmentId"},
        ],
        "interactions": [
            {"id": "create-equipment", "sourcePage": "/equipment",
             "trigger": "button", "label": "Create Equipment",
             "workflowId": "CreateEquipment", "targetEntityId": "equipment",
             "inputMap": {}},
        ],
        "roles": [],
    }


def test_clean_registry_is_ok(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _clean_registry())
    _write_workflow(out, "CreateEquipment", {"id": "CreateEquipment"})

    res = validate_registry(out)

    assert res["ok"] is True
    assert res["errors"] == []


def test_relationship_to_missing_entity_errors(tmp_path):
    out = str(tmp_path)
    reg = _clean_registry()
    reg["relationships"][0]["to"] = "sprocket"
    _write_registry(out, reg)
    _write_workflow(out, "CreateEquipment", {"id": "CreateEquipment"})

    res = validate_registry(out)

    assert res["ok"] is False
    kinds = {e["kind"] for e in res["errors"]}
    assert "relationship_unresolved" in kinds


def test_interaction_target_entity_unresolved(tmp_path):
    out = str(tmp_path)
    reg = _clean_registry()
    reg["interactions"][0]["targetEntityId"] = "ghost"
    _write_registry(out, reg)
    _write_workflow(out, "CreateEquipment", {"id": "CreateEquipment"})

    res = validate_registry(out)

    assert res["ok"] is False
    kinds = {e["kind"] for e in res["errors"]}
    assert "interaction_entity_unresolved" in kinds


def test_interaction_workflow_unresolved_when_workflows_dir_present(tmp_path):
    out = str(tmp_path)
    reg = _clean_registry()
    reg["interactions"][0]["workflowId"] = "NoSuchWorkflow"
    _write_registry(out, reg)
    # a workflows dir exists (with a different workflow) → missing ref is an ERROR
    _write_workflow(out, "CreateEquipment", {"id": "CreateEquipment"})

    res = validate_registry(out)

    assert res["ok"] is False
    kinds = {e["kind"] for e in res["errors"]}
    assert "interaction_workflow_unresolved" in kinds


def test_missing_registry_file_is_ok_with_warning(tmp_path):
    res = validate_registry(str(tmp_path))

    assert res["ok"] is True
    assert res["errors"] == []
    assert "resource-registry.json not found" in res["warnings"]

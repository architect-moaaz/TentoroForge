"""Tests for list_entity_coherence_guard.

A persona/entity list page whose filename matches (singular of) a registered
entity must bind to THAT entity. The `inhdm3ta` symptom — carers.json
binding {entity: "User"} — is the class we're closing.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.list_entity_coherence_guard import reconcile_list_entities


def _fixture_project(tmp_path: Path, entities: dict, schemas: dict[str, dict]) -> Path:
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "registry.json").write_text(json.dumps({"entities": entities}), encoding="utf-8")
    (tmp_path / "plan.json").write_text(json.dumps({"entities": entities}), encoding="utf-8")
    for rel, content in schemas.items():
        path = tmp_path / "src" / "schemas" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content), encoding="utf-8")
    return tmp_path


def _page(*, ds_entity: str, ds_name: str, rows_binding: str) -> dict:
    return {
        "dataSources": [{"name": ds_name, "entity": ds_entity, "op": "list"}],
        "root": {
            "type": "Stack",
            "children": [
                {
                    "type": "Table",
                    "props": {
                        "columns": [{"key": "id", "label": "Id"}],
                        "rows": rows_binding,
                    },
                }
            ],
        },
    }


# ────────────────────────────────────────────────────────────
# core case — the real inhdm3ta bug
# ────────────────────────────────────────────────────────────

def test_rebinds_persona_list_page_bound_to_wrong_entity(tmp_path):
    entities = {
        "User": {"table": "users", "fields": {}},
        "Carer": {"table": "carers", "fields": {"id": {}, "userId": {}}},
    }
    schemas = {
        "carers.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    r = reconcile_list_entities(str(tmp_path))

    page = json.loads((tmp_path / "src" / "schemas" / "carers.json").read_text(encoding="utf-8"))
    assert page["dataSources"][0]["entity"] == "Carer"
    assert page["dataSources"][0]["name"] == "carers"
    assert r["pages_rebound"] == 1
    # rows binding should also be repointed to the new name
    tbl = page["root"]["children"][0]
    assert tbl["props"]["rows"] == "{{carers}}"


def test_rebinds_kebab_named_page(tmp_path):
    # elderly-users.json → ElderlyUser entity
    entities = {
        "User": {"table": "users", "fields": {}},
        "ElderlyUser": {"table": "elderly_users", "fields": {"id": {}}},
    }
    schemas = {
        "elderly-users.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    reconcile_list_entities(str(tmp_path))

    page = json.loads((tmp_path / "src" / "schemas" / "elderly-users.json").read_text(encoding="utf-8"))
    assert page["dataSources"][0]["entity"] == "ElderlyUser"


def test_leaves_correct_binding_alone(tmp_path):
    entities = {"Carer": {"table": "carers", "fields": {}}}
    schemas = {
        "carers.json": _page(ds_entity="Carer", ds_name="carers", rows_binding="{{carers}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    r = reconcile_list_entities(str(tmp_path))
    assert r["pages_rebound"] == 0


def test_skips_page_when_no_matching_entity(tmp_path):
    # /dashboard has no matching entity; leave its dataSource alone.
    entities = {"User": {"table": "users", "fields": {}}}
    schemas = {
        "dashboard.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    r = reconcile_list_entities(str(tmp_path))
    assert r["pages_rebound"] == 0
    page = json.loads((tmp_path / "src" / "schemas" / "dashboard.json").read_text(encoding="utf-8"))
    assert page["dataSources"][0]["entity"] == "User"


def test_skips_detail_and_edit_pages(tmp_path):
    # carers/[id].json and carers/[id]/edit.json shouldn't be treated as list.
    entities = {
        "User": {"table": "users", "fields": {}},
        "Carer": {"table": "carers", "fields": {}},
    }
    schemas = {
        "carers/[id].json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
        "carers/[id]/edit.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
        "carers/new.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    r = reconcile_list_entities(str(tmp_path))
    assert r["pages_rebound"] == 0


def test_skips_shell_and_login(tmp_path):
    entities = {"User": {"table": "users", "fields": {}}}
    schemas = {
        "shell.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
        "login.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
        "signup.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    r = reconcile_list_entities(str(tmp_path))
    assert r["pages_rebound"] == 0


def test_matches_singular_plural(tmp_path):
    # `carer.json` singular should also rebind to Carer.
    entities = {
        "User": {"table": "users", "fields": {}},
        "Carer": {"table": "carers", "fields": {}},
    }
    schemas = {
        "carer.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    reconcile_list_entities(str(tmp_path))
    page = json.loads((tmp_path / "src" / "schemas" / "carer.json").read_text(encoding="utf-8"))
    assert page["dataSources"][0]["entity"] == "Carer"


def test_prefers_existing_dataSource_name_convention(tmp_path):
    # After rebinding, the dataSource name uses the plural-lowercase of the entity name
    # ('Carer' → 'carers'), matching the deterministic-emitter convention.
    entities = {
        "User": {"table": "users", "fields": {}},
        "Carer": {"table": "carers", "fields": {}},
    }
    schemas = {
        "carers.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    reconcile_list_entities(str(tmp_path))
    page = json.loads((tmp_path / "src" / "schemas" / "carers.json").read_text(encoding="utf-8"))
    assert page["dataSources"][0]["name"] == "carers"


def test_no_registry_is_safe_noop(tmp_path):
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    r = reconcile_list_entities(str(tmp_path))
    assert r["pages_rebound"] == 0
    assert r["pages_scanned"] == 0


def test_idempotent(tmp_path):
    entities = {
        "User": {"table": "users", "fields": {}},
        "Carer": {"table": "carers", "fields": {}},
    }
    schemas = {
        "carers.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    first = reconcile_list_entities(str(tmp_path))
    second = reconcile_list_entities(str(tmp_path))
    assert first["pages_rebound"] == 1
    assert second["pages_rebound"] == 0


def test_rebinds_multiple_persona_pages_in_one_run(tmp_path):
    entities = {
        "User": {"table": "users", "fields": {}},
        "Carer": {"table": "carers", "fields": {}},
        "ElderlyUser": {"table": "elderly_users", "fields": {}},
        "Guardian": {"table": "guardians", "fields": {}},
    }
    schemas = {
        "carers.json":        _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
        "elderly-users.json": _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
        "guardians.json":     _page(ds_entity="User", ds_name="users", rows_binding="{{users}}"),
    }
    _fixture_project(tmp_path, entities, schemas)
    r = reconcile_list_entities(str(tmp_path))
    assert r["pages_rebound"] == 3


def test_preserves_extra_data_sources_and_shape(tmp_path):
    # A page with multiple dataSources: only the list one gets rebound.
    entities = {
        "User": {"table": "users", "fields": {}},
        "Carer": {"table": "carers", "fields": {}},
    }
    page = {
        "dataSources": [
            {"name": "users", "entity": "User", "op": "list"},
            {"name": "stats", "entity": "Statistic", "op": "aggregate"},
        ],
        "root": {"type": "Table", "props": {"rows": "{{users}}"}},
    }
    schemas = {"carers.json": page}
    _fixture_project(tmp_path, entities, schemas)
    reconcile_list_entities(str(tmp_path))
    written = json.loads((tmp_path / "src" / "schemas" / "carers.json").read_text(encoding="utf-8"))
    assert len(written["dataSources"]) == 2
    assert written["dataSources"][0]["entity"] == "Carer"
    assert written["dataSources"][1]["entity"] == "Statistic"  # untouched

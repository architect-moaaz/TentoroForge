"""Tests for services.test_suite_emitter — the in-app vitest suite emitter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.test_suite_emitter import emit_test_suite

GEN = Path("src") / "__tests__" / "generated"
HEADER = "// AUTO-GENERATED — regenerated every build. Do not edit by hand."


def _registry() -> dict:
    """Small canonical registry: Project (enum), Task (NOT-NULL FK → project),
    User (auth-reserved table)."""
    return {
        "version": 1,
        "entities": {
            "Project": {
                "name": "Project", "id": "project", "slug": "projects",
                "table": "projects", "camel": "project", "singular": "project",
                "columns": [
                    {"name": "id", "type": "uuid", "notNull": True, "fk": None, "enum": None},
                    {"name": "title", "type": "varchar", "notNull": True, "fk": None, "enum": None},
                    {"name": "status", "type": "varchar", "notNull": True, "fk": None,
                     "enum": ["active", "archived"]},
                    {"name": "createdAt", "type": "timestamp", "notNull": False, "fk": None, "enum": None},
                ],
                "fks": [],
            },
            "Task": {
                "name": "Task", "id": "task", "slug": "tasks",
                "table": "tasks", "camel": "task", "singular": "task",
                "columns": [
                    {"name": "id", "type": "uuid", "notNull": True, "fk": None, "enum": None},
                    {"name": "name", "type": "varchar", "notNull": True, "fk": None, "enum": None},
                    {"name": "projectId", "type": "uuid", "notNull": True, "fk": "project", "enum": None},
                    {"name": "estimate", "type": "integer", "notNull": False, "fk": None, "enum": None},
                ],
                "fks": [{"column": "projectId", "targetEntityId": "project"}],
            },
            "User": {
                "name": "User", "id": "user", "slug": "users",
                "table": "users", "camel": "user", "singular": "user",
                "columns": [
                    {"name": "id", "type": "uuid", "notNull": True, "fk": None, "enum": None},
                    {"name": "email", "type": "varchar", "notNull": True, "fk": None, "enum": None},
                ],
                "fks": [],
            },
        },
        "relationships": [], "interactions": [], "roles": [],
    }


@pytest.fixture()
def app_dir(tmp_path: Path) -> Path:
    out = tmp_path / "app"
    (out / "contracts").mkdir(parents=True)
    (out / "contracts" / "resource-registry.json").write_text(
        json.dumps(_registry()), encoding="utf-8")

    (out / "workflows").mkdir()
    (out / "workflows" / "CreateTask.json").write_text(json.dumps({
        "id": "create-task", "name": "CreateTask",
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [
                {"id": "trigger", "type": "trigger", "data": {"config": {"type": "manual"}}},
                {"id": "db_insert", "type": "action",
                 "data": {"config": {"actionType": "db_insert", "table": "tasks"}}},
                {"id": "end", "type": "end", "data": {"config": {}}},
            ],
            "edges": [
                {"id": "e1", "source": "trigger", "target": "db_insert"},
                {"id": "e2", "source": "db_insert", "target": "end"},
            ],
        },
    }), encoding="utf-8")

    (out / "src" / "schemas").mkdir(parents=True)
    (out / "src" / "schemas" / "dashboard.json").write_text(json.dumps({
        "schemaVersion": "2", "id": "dashboard", "route": "/dashboard",
        "dataSources": [{"name": "tasks", "entity": "Task", "op": "list"}],
        "root": {},
    }), encoding="utf-8")

    (out / "package.json").write_text(json.dumps({
        "name": "fixture-app",
        "scripts": {"dev": "next dev"},
        "devDependencies": {"typescript": "^5.0.0"},
    }, indent=2), encoding="utf-8")
    return out


def test_emits_expected_files(app_dir: Path):
    res = emit_test_suite(str(app_dir))
    assert "reason" not in res
    gen = app_dir / GEN
    assert (gen / "crud.projects.test.ts").is_file()
    assert (gen / "crud.tasks.test.ts").is_file()
    assert (gen / "workflows.test.ts").is_file()
    assert (gen / "registry-consistency.test.ts").is_file()
    assert (gen / "manifest.json").is_file()
    assert (app_dir / "vitest.config.ts").is_file()
    assert res["counts"]["crud_tests"] == 2


def test_crud_test_content(app_dir: Path):
    emit_test_suite(str(app_dir))
    task = (app_dir / GEN / "crud.tasks.test.ts").read_text(encoding="utf-8")
    assert task.startswith(HEADER)
    assert 'describe.skipIf(!LIVE)("CRUD round-trip: Task"' in task
    # NOT-NULL FK → parent Project created first, id wired into the insert
    assert 'engine.create("projects"' in task
    assert '"projectId": parentProject.id' in task
    # in-process engine import (not HTTP)
    assert 'await import("@/lib/data-engine")' in task
    assert "ensureDataEngineInitialized" in task
    # nullable column NOT in the minimal insert
    assert '"estimate"' not in task.split("engine.update")[0]

    project = (app_dir / GEN / "crud.projects.test.ts").read_text(encoding="utf-8")
    # enum → first value on create, second on update
    assert '"status": "active"' in project or '"title"' in project
    assert '"active"' in project
    assert "engine.update" in project
    # system columns never synthesized
    assert '"createdAt"' not in project


def test_user_entity_skipped(app_dir: Path):
    res = emit_test_suite(str(app_dir))
    assert not (app_dir / GEN / "crud.users.test.ts").exists()
    reasons = {s.get("entity"): s.get("reason") for s in res["skipped"] if "entity" in s}
    assert reasons.get("User") == "auth-reserved table"
    assert res["counts"]["entities_skipped"] == 1


def test_workflow_and_consistency_tests_embed_registry_keys(app_dir: Path):
    emit_test_suite(str(app_dir))
    wf = (app_dir / GEN / "workflows.test.ts").read_text(encoding="utf-8")
    assert '"tasks"' in wf and '"task"' in wf
    assert "KNOWN_TABLE_KEYS" in wf
    cons = (app_dir / GEN / "registry-consistency.test.ts").read_text(encoding="utf-8")
    assert "KNOWN_ENTITY_KEYS" in cons
    assert '"project"' in cons


def test_manifest_counts(app_dir: Path):
    emit_test_suite(str(app_dir))
    manifest = json.loads((app_dir / GEN / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "resource-registry"
    assert manifest["counts"]["crud_tests"] == 2
    assert manifest["counts"]["workflow_files"] == 1
    assert manifest["counts"]["schema_files"] == 1


def test_package_json_injection(app_dir: Path):
    emit_test_suite(str(app_dir))
    pkg = json.loads((app_dir / "package.json").read_text(encoding="utf-8"))
    assert pkg["scripts"]["test"] == "vitest run"
    assert "vitest" in pkg["devDependencies"]
    # existing keys preserved
    assert pkg["scripts"]["dev"] == "next dev"
    assert pkg["devDependencies"]["typescript"] == "^5.0.0"


def test_idempotent_second_run(app_dir: Path):
    emit_test_suite(str(app_dir))
    first = {p.name: p.read_text(encoding="utf-8")
             for p in (app_dir / GEN).iterdir()}
    pkg_first = (app_dir / "package.json").read_text(encoding="utf-8")
    cfg_first = (app_dir / "vitest.config.ts").read_text(encoding="utf-8")

    res2 = emit_test_suite(str(app_dir))
    second = {p.name: p.read_text(encoding="utf-8")
              for p in (app_dir / GEN).iterdir()}
    assert first == second
    assert (app_dir / "package.json").read_text(encoding="utf-8") == pkg_first
    assert (app_dir / "vitest.config.ts").read_text(encoding="utf-8") == cfg_first
    file_skips = {s.get("file"): s.get("reason") for s in res2["skipped"] if "file" in s}
    assert file_skips.get("vitest.config.ts") == "already present"
    assert file_skips.get("package.json") == "already wired"


def test_prunes_stale_generated_but_keeps_user_files(app_dir: Path):
    gen = app_dir / GEN
    gen.mkdir(parents=True, exist_ok=True)
    stale = gen / "crud.old-entity.test.ts"
    stale.write_text(HEADER + "\n// stale\n", encoding="utf-8")
    user_file = gen / "my-own.test.ts"
    user_file.write_text("// hand-written, no header\n", encoding="utf-8")

    emit_test_suite(str(app_dir))
    assert not stale.exists(), "header-carrying stale file must be pruned"
    assert user_file.exists(), "user file without header must survive"


def test_never_clobbers_existing_vitest_config(app_dir: Path):
    (app_dir / "vitest.config.ts").write_text("// user config\n", encoding="utf-8")
    res = emit_test_suite(str(app_dir))
    assert (app_dir / "vitest.config.ts").read_text(encoding="utf-8") == "// user config\n"
    file_skips = {s.get("file"): s.get("reason") for s in res["skipped"] if "file" in s}
    assert file_skips.get("vitest.config.ts") == "already present"


def test_graceful_without_registry(tmp_path: Path):
    out = tmp_path / "bare"
    out.mkdir()
    res = emit_test_suite(str(out))
    assert res["written"] == []
    assert "reason" in res
    assert not (out / GEN).exists() or not list((out / GEN).iterdir())


def test_missing_output_dir(tmp_path: Path):
    res = emit_test_suite(str(tmp_path / "nope"))
    assert res["written"] == []
    assert "reason" in res


def test_fallback_to_contract_registry(tmp_path: Path):
    out = tmp_path / "fallback"
    out.mkdir()
    (out / "registry.json").write_text(json.dumps({
        "entities": {
            "Invoice": {"fields": {
                "id": {"type": "uuid", "nullable": False},
                "amount": {"type": "integer", "nullable": False},
                "status": {"type": "varchar", "nullable": False,
                           "enum_values": ["draft", "sent"]},
            }, "indexes": []},
        },
        "relations": [],
    }), encoding="utf-8")
    res = emit_test_suite(str(out))
    assert res["counts"]["crud_tests"] == 1
    files = [Path(p).name for p in res["written"]]
    assert any(f.startswith("crud.invoice") for f in files)
    manifest = json.loads((out / GEN / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "registry.json"

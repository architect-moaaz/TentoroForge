from pathlib import Path
from services.schema_barrel import reconcile_db_schema_barrel


def _mk(tmp_path: Path):
    d = tmp_path / "src" / "db" / "schema"
    d.mkdir(parents=True)
    (d / "property.ts").write_text('export const properties = pgTable("properties", {});', encoding="utf-8")
    (d / "user.ts").write_text('export const users = pgTable("users", {});', encoding="utf-8")
    (d / "relations.ts").write_text('export const propertiesRelations = relations(properties, () => ({}));', encoding="utf-8")
    return tmp_path


def test_builds_complete_barrel_and_removes_shadow(tmp_path):
    root = _mk(tmp_path)
    # singular shadow that would otherwise win @/db/schema resolution
    (root / "src" / "db" / "schema.ts").write_text(
        'export const property = pgTable("property", {});\n'
        "export { wfInstances } from '@/lib/workflow-engine/infrastructure/schema';\n", encoding="utf-8")
    rep = reconcile_db_schema_barrel(root)
    assert rep["reconciled"] and rep["removed_shadow"]
    idx = (root / "src" / "db" / "schema" / "index.ts").read_text(encoding="utf-8")
    assert 'export { properties } from "./property";' in idx
    assert 'export { users } from "./user";' in idx           # users no longer dropped
    assert "wfInstances" in idx                                # carried over
    assert not (root / "src" / "db" / "schema.ts").exists()    # shadow gone


def test_noop_without_dir(tmp_path):
    assert reconcile_db_schema_barrel(tmp_path)["reconciled"] is False

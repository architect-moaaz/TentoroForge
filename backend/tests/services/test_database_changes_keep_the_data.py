"""A feature that changes the database keeps the data that is already there.

The database tests of 2026-10-01 ran every kind of change against Postgres 16
and 18, the way Smith pushed it and the way a publish does: a required field
EMPTIED the table on publish; a rename, a refused type change and every
removal crashed or failed with exit 0 and the push said "applied"; a removal
dropped its data. These hold the fixes: the scripts that run around the push,
the build that checks the database after it, the same chain for Smith's own
push, and the renames Smith writes down so the data moves with the name.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint import migrations_ledger

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "templates" / "app-foundation" / "src" / "db"


def test_the_publish_build_checks_the_database_after_the_push():
    build = json.loads((ROOT / "templates/runtime/vercel.json").read_text())["buildCommand"]
    order = [build.index(s) for s in ("prepare-schema.ts", "drizzle-kit push", "verify-schema.ts", "seed.ts")]
    assert order == sorted(order)


def test_every_app_gets_the_current_database_scripts_on_publish_and_on_its_next_turn():
    from services.deploy.vercel_provider import _PLATFORM_REFRESH_FOUNDATION_FILES
    from services.smith.sync_app import DB_SCRIPTS
    for rel in ("src/db/prepare-schema.ts", "src/db/verify-schema.ts"):
        assert rel in _PLATFORM_REFRESH_FOUNDATION_FILES and rel in DB_SCRIPTS
        assert (ROOT / "templates/app-foundation" / rel).is_file()


def test_prepare_schema_keeps_rows_through_every_kind_of_change():
    src = (DB / "prepare-schema.ts").read_text()
    for part in ("async function applyRenames", "async function addRequired", "async function keepRetired",
                 "forge_retired.rows", "src/db/migrations.json", "cannot become"):
        assert part in src, part


def test_smiths_push_runs_the_publish_chain(tmp_path, monkeypatch):
    import subprocess
    from services.blueprint import schema_push
    app = tmp_path / "app"
    (app / "node_modules").mkdir(parents=True)
    (app / "drizzle.config.ts").write_text("")
    (app / "src/db").mkdir(parents=True)
    for f in ("prepare-schema.ts", "verify-schema.ts", "seed.ts"):
        (app / "src/db" / f).write_text("")
    (app / ".env.local").write_text("DATABASE_URL=postgresql://u:p@127.0.0.1:5999/x\n")
    monkeypatch.setattr(schema_push, "_answers", lambda url: True)
    ran = []

    class Done:
        def __init__(self, code, out=""):
            self.returncode, self.stdout, self.stderr = code, out, ""

    def fake(cmd, **kw):
        ran.append(cmd[1:3])
        if cmd[2] == "src/db/verify-schema.ts":
            return Done(1, "[verify-schema] the database is NOT in step with the definition:\n"
                           "  - orders.fulfilled is not in the database\nThe schema push above did not apply all of it.")
        return Done(0)
    monkeypatch.setattr(subprocess, "run", fake)
    out = schema_push.push_now(app)
    assert ran == [["tsx", "src/db/prepare-schema.ts"], ["drizzle-kit", "push"], ["tsx", "src/db/verify-schema.ts"]]
    assert not out["applied"] and "orders.fulfilled is not in the database" in out["reason"]


def test_a_rename_is_written_down_once_and_follows_its_table(tmp_path):
    migrations_ledger.column_renamed(tmp_path, "items", "name", "title")
    migrations_ledger.column_renamed(tmp_path, "items", "name", "title")
    migrations_ledger.table_renamed(tmp_path, "items", "products")
    data = json.loads((tmp_path / "src/db/migrations.json").read_text())
    assert data == {"columns": [{"table": "products", "from": "name", "to": "title"}],
                    "tables": [{"from": "items", "to": "products"}]}


def test_renaming_a_field_writes_its_rename_for_the_database(tmp_path, monkeypatch):
    from services.blueprint.service import BlueprintService
    from services.smith import field_change
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="F&B", domain="food")
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Order", "table": "orders", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True}, {"name": "customerName", "type": "string"}]}],
        "relationships": []}
    svc.save()
    app = tmp_path / "app"
    (app / "src/db").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    monkeypatch.setattr(field_change, "_project", lambda svc, root: [])
    out = field_change.rename_field(svc, "Order", "customerName", "customer", app_root=str(app))
    assert json.loads((app / "src/db/migrations.json").read_text())["columns"] == [
        {"table": "orders", "from": "customer_name", "to": "customer"}]
    assert "with its data" in field_change.summary_of("rename_field", out)

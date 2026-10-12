"""A record Smith adds to a built app is in its database now, not at the next install.

Test2, 2026-09-28: Smith added an Area record and said "the table lands as a
migration on the next install" — so the screen it would build next had no
table to save into until somebody restarted the preview.
"""
import subprocess
from pathlib import Path

from services.blueprint import schema_push


def _app(tmp_path, url="postgresql://postgres:postgres@localhost:5433/app_t"):
    app = tmp_path / "app"
    (app / "node_modules").mkdir(parents=True)
    (app / "src/db").mkdir(parents=True)
    (app / "src/db/seed.ts").write_text("")
    (app / "drizzle.config.ts").write_text("")
    (app / ".env.local").write_text(f"NEXTAUTH_URL=x\nDATABASE_URL={url}\n")
    return app


def test_the_schema_is_pushed_then_seeded_against_the_apps_own_database(tmp_path, monkeypatch):
    app = _app(tmp_path)
    ran = []
    monkeypatch.setattr(schema_push, "_answers", lambda url: True)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: ran.append((cmd, k["env"]["DATABASE_URL"], k["stdin"]))
                        or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert schema_push.push_now(app) == {"applied": True, "reason": "", "lines": []}
    # The publish's own chain (prepare-schema and verify-schema are skipped
    # where the app does not have them): `--force` is safe because
    # prepare-schema keeps the rows a push would otherwise destroy.
    # The program is `npx` — resolved to its `.CMD` shim on Windows, left as the bare name elsewhere.
    assert [[Path(r[0][0]).stem.lower(), *r[0][1:]] for r in ran] == [
        ["npx", "drizzle-kit", "push", "--force"], ["npx", "tsx", "src/db/seed.ts"]]
    assert all(r[1].endswith("/app_t") for r in ran)
    assert all(r[2] == subprocess.DEVNULL for r in ran), "nothing ever waits on a terminal nobody has"


def test_no_database_running_is_said_not_hidden(tmp_path, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(schema_push, "_answers", lambda url: False)
    assert schema_push.push_now(app) == {"applied": False, "reason": "its database is not running"}


def test_a_push_that_fails_names_what_failed(tmp_path, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(schema_push, "_answers", lambda url: True)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "error: relation exists"))
    out = schema_push.push_now(app)
    assert not out["applied"] and "drizzle-kit push" in out["reason"] and "relation exists" in out["reason"]


def test_a_record_added_after_the_build_is_registered_with_the_data_engine(tmp_path):
    """Test2, 2026-09-28: Area had a table, twelve rows and a schema file,
    and Location Data said "No areas registered yet" — `data-init.ts`, the
    engine's list of records, was only ever written by the build."""
    from services.blueprint.projection import project_data_layer
    app = tmp_path / "app"
    (app / "src/lib").mkdir(parents=True)
    (app / "src/lib/data-init.ts").write_text('import("@/db/schema/worker"),\n')   # as the build left it
    doc = {"data": {"entities": [
        {"id": "ENTITY-001", "name": "Worker", "table": "workers", "fields": [{"name": "name", "type": "string"}]},
        {"id": "ENTITY-002", "name": "Area", "table": "areas", "fields": [{"name": "areaName", "type": "string"}]}]}}
    out = project_data_layer(doc, app)
    init = (app / "src/lib/data-init.ts").read_text()
    assert 'import("@/db/schema/area")' in init and 'import("@/db/schema/worker")' in init
    assert "src/lib/data-init.ts" in out["files"]

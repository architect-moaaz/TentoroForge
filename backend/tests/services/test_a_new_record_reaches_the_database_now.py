"""A record Smith adds to a built app is in its database now, not at the next install.

Test2, 2026-09-28: Smith added an Area record and said "the table lands as a
migration on the next install" — so the screen it would build next had no
table to save into until somebody restarted the preview.
"""
import subprocess

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
    assert schema_push.push_now(app) == {"applied": True, "reason": ""}
    assert [r[0] for r in ran] == [["npx", "drizzle-kit", "push"], ["npx", "tsx", "src/db/seed.ts"]]
    assert all(r[1].endswith("/app_t") for r in ran)
    assert all(r[2] == subprocess.DEVNULL for r in ran), "a destructive prompt is never confirmed for the owner"


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

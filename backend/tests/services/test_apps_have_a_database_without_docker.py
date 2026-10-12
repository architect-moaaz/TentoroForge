"""forge-v3 (2026-10-01): "Verify & fix" answered "Docker is not available for
the app's database" for every app, and the Preview tab started apps with no
database: the backend runs in a container with no Docker. With
FORGE_APPS_DATABASE_URL set, each app's database lives on the apps server,
created over the network, and a review works on a TEMPLATE copy of it.

The database tests run against a real Postgres when APPS_DB_TEST_SERVER names
one (postgresql://user:pass@host:port); the wiring tests always run.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from services import app_databases

SERVER = os.environ.get("APPS_DB_TEST_SERVER", "")
needs_server = pytest.mark.skipif(not SERVER, reason="APPS_DB_TEST_SERVER not set")


def _app(tmp_path, project="Fxa532bj"):
    root = tmp_path / project / "app"
    root.mkdir(parents=True)
    (root / ".env").write_text("NEXTAUTH_SECRET=x\nDATABASE_URL=postgres://postgres:pw@localhost:5432/app\n")
    return root


def test_unset_means_the_docker_path_as_before(monkeypatch, tmp_path):
    monkeypatch.delenv(app_databases.SERVER_ENV, raising=False)
    assert app_databases.server() == "" and app_databases.ensure(_app(tmp_path)) is None


def test_an_app_is_named_by_its_project(tmp_path):
    assert app_databases.name_for(tmp_path / "Fxa532bj" / "app") == "app_fxa532bj"
    assert app_databases.name_for(tmp_path / "my-app") == "app_my_app"


@needs_server
def test_an_apps_database_is_created_pointed_at_copied_and_dropped(monkeypatch, tmp_path):
    monkeypatch.setenv(app_databases.SERVER_ENV, SERVER)
    pushed = []
    monkeypatch.setattr("services.blueprint.schema_push.push_now",
                        lambda root: pushed.append(root) or {"applied": True})
    root = _app(tmp_path, f"t{os.getpid()}")
    name = app_databases.name_for(root)
    try:
        out = app_databases.ensure(root)
        assert out["created"] and out["pushed"] and pushed == [root]
        url = f"{SERVER}/{name}"
        assert f"DATABASE_URL={url}" in (root / ".env").read_text()
        assert f"DATABASE_URL={url}" in (root / ".env.local").read_text()
        assert "localhost:5432" not in (root / ".env").read_text() and "NEXTAUTH_SECRET=x" in (root / ".env").read_text()
        app_databases.query(name, "CREATE TABLE things (id int, label text)")
        app_databases.query(name, "INSERT INTO things VALUES (1, 'kept') RETURNING id")
        again = app_databases.ensure(root)                      # exists, has tables: not pushed again
        assert not again["created"] and len(pushed) == 1
        copy, copy_url = app_databases.clone(root)
        assert copy.startswith(f"{name}_review_") and copy_url.endswith("/" + copy)
        assert app_databases.query(copy, "SELECT label FROM things") == [["kept"]]
        app_databases.drop(copy)
        assert app_databases.query("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{copy}'") == []
    finally:
        app_databases.drop(name)


def test_the_review_uses_the_apps_server_when_there_is_one(monkeypatch, tmp_path):
    from services.blueprint import page_review
    monkeypatch.setenv(app_databases.SERVER_ENV, "postgresql://postgres:pw@apps-db:5432")
    calls = []
    monkeypatch.setattr(app_databases, "ensure", lambda root: calls.append(("ensure", Path(root).name)))
    # The Workbench asks the database itself for its tables and a login.
    monkeypatch.setattr(app_databases, "_has_tables", lambda name: True)
    monkeypatch.setattr(app_databases, "_has_a_login", lambda name: True)
    monkeypatch.setattr(app_databases, "clone", lambda root: ("app_x_review_1", "postgresql://h/app_x_review_1"))
    monkeypatch.setattr(app_databases, "drop", lambda name: calls.append(("drop", name)))
    monkeypatch.setattr(app_databases, "query", lambda name, sql: [["row"]] if name == "app_x_review_1" else [])
    monkeypatch.setattr(page_review.RunningApp, "_serve", lambda self: self)
    monkeypatch.setattr(page_review.shutil, "which", lambda name: None)     # no Docker at all
    app = page_review.RunningApp(_app(tmp_path)).__enter__()
    assert app.clone == ("", "app_x_review_1", "postgresql://h/app_x_review_1")
    assert page_review._query(app, "SELECT 1") == [["row"]]
    app.__exit__(None, None, None)
    assert calls == [("ensure", "app"), ("drop", "app_x_review_1")]


def test_the_review_finds_the_images_own_playwright(monkeypatch, tmp_path):
    from services.blueprint import page_review
    (tmp_path / "playwright").mkdir()
    monkeypatch.setenv("FORGE_PLAYWRIGHT_MODULES", str(tmp_path))
    assert page_review._playwright_modules() == tmp_path


def test_the_preview_uses_the_apps_server_when_there_is_one(monkeypatch, tmp_path):
    import asyncio
    import preview
    monkeypatch.setenv(app_databases.SERVER_ENV, "postgresql://postgres:pw@apps-db:5432")
    seen = []
    monkeypatch.setattr(app_databases, "ensure", lambda root: seen.append(str(root)))
    monkeypatch.setattr(app_databases, "_has_tables", lambda name: True)
    monkeypatch.setattr(app_databases, "_has_a_login", lambda name: True)
    asyncio.run(preview._ensure_database(str(tmp_path)))
    assert seen == [str(tmp_path)]


def test_a_database_with_tables_and_no_login_is_seeded(monkeypatch, tmp_path):
    """TStyle (forge-v3, 2026-10-09): pushed before the app was installed, its
    database had tables and no rows, and nothing seeded it again — the handover
    named a login that did not exist and every statement was refused at sign-in."""
    class Con:
        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def execute(self, sql):
            pass

        def close(self):
            pass

    monkeypatch.setenv(app_databases.SERVER_ENV, "postgresql://u:p@apps-db:5432")
    monkeypatch.setattr(app_databases, "_connect", lambda *a: Con())
    monkeypatch.setattr(app_databases, "_exists", lambda cur, name: True)
    monkeypatch.setattr(app_databases, "_write_url", lambda root, url: None)
    monkeypatch.setattr(app_databases, "_extensions", lambda root, url: None)
    monkeypatch.setattr(app_databases, "_has_tables", lambda name: True)
    pushed = []
    monkeypatch.setattr("services.blueprint.schema_push.push_now",
                        lambda root: pushed.append(root) or {"applied": True})
    root = _app(tmp_path)
    monkeypatch.setattr(app_databases, "_has_a_login", lambda name: False)
    assert app_databases.ensure(root)["pushed"] and pushed == [root]
    monkeypatch.setattr(app_databases, "_has_a_login", lambda name: True)
    assert not app_databases.ensure(root)["pushed"] and len(pushed) == 1, "a seeded database is left as it is"

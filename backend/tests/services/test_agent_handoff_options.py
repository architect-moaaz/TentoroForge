"""Who could handle a handoff in this app (services/agent_handoff_options.py).

Roles come from the Blueprint, people from the app's own users table; reading the people is best-effort, and
an app whose database is not running still gets its roles.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from services.agent_handoff_options import handoff_options
from tests.services.test_agent_runtime_install import make_app


def with_blueprint(project, roles):
    (project / ".forge" / "blueprint").mkdir(parents=True, exist_ok=True)
    (project / ".forge" / "blueprint" / "current.json").write_text(json.dumps({"roles": roles}), encoding="utf-8")


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql):
        self.sql = sql

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def cursor(self, cursor_factory=None):
        return FakeCursor(self.rows)

    def close(self):
        self.closed = True


def test_roles_come_from_the_blueprint_without_duplicates_or_retired_ones(tmp_path):
    project, app = make_app(tmp_path)
    with_blueprint(project, [{"name": "Manager"}, {"name": "Support Agent"}, {"name": "manager"},
                             {"name": "Old", "status": "DEPRECATED"}, {"id": "no name"}])
    got = handoff_options(project)
    assert got["roles"] == ["Manager", "Support Agent"]


def test_people_come_from_the_apps_users_table_and_inactive_ones_are_left_out(tmp_path, monkeypatch):
    project, app = make_app(tmp_path)
    with_blueprint(project, [{"name": "Manager"}])
    (app / ".env.local").write_text("DATABASE_URL=postgresql://u:p@localhost:5999/app\n", encoding="utf-8")
    rows = [{"id": "u1", "display_name": "Maya Brandt", "role": "Manager", "email": "m@x.test"},
            {"id": "u2", "name": "Idris", "role": "Support Agent"},
            {"id": "u3", "email": "only-email@x.test", "role": "Manager"},
            {"id": "u4", "display_name": "Gone", "role": "Manager", "is_active": False},
            {"display_name": "No id"}]
    seen = {}
    fake = FakeConnection(rows)

    def connect(url, connect_timeout=0):
        seen["url"], seen["timeout"] = url, connect_timeout
        return fake

    monkeypatch.setattr("psycopg2.connect", connect)
    got = handoff_options(project)
    assert [p["name"] for p in got["people"]] == ["Idris", "Maya Brandt", "only-email@x.test"], "named, sorted, active only"
    assert got["people"][1] == {"id": "u1", "name": "Maya Brandt", "role": "Manager"}
    assert "Support Agent" in got["roles"], "a role someone holds counts even when the Blueprint does not list it"
    assert got["peopleNote"] is None and fake.closed and seen["url"].endswith("/app") and seen["timeout"] <= 5


def test_an_app_whose_database_is_not_running_still_gets_its_roles(tmp_path):
    project, app = make_app(tmp_path)
    with_blueprint(project, [{"name": "Manager"}])
    (app / ".env.local").write_text("DATABASE_URL=postgresql://u:p@127.0.0.1:1/app\n", encoding="utf-8")
    got = handoff_options(project)
    assert got["roles"] == ["Manager"] and got["people"] == []
    assert "could not be listed" in got["peopleNote"] and "pick roles" in got["peopleNote"]


def test_an_app_that_is_not_built_yet_says_so(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    with_blueprint(project, [{"name": "Manager"}])
    got = handoff_options(project)
    assert got["roles"] == ["Manager"] and got["people"] == [] and "not built yet" in got["peopleNote"]


def test_no_blueprint_and_no_app_is_just_empty(tmp_path):
    got = handoff_options(tmp_path / "nothing")
    assert got["roles"] == [] and got["people"] == []


@pytest.mark.asyncio
async def test_the_endpoint_answers_and_is_not_mistaken_for_an_agent_id(tmp_path, monkeypatch):
    from routers.agent_builder import get_handoff_options, router

    project, app = make_app(tmp_path)
    with_blueprint(project, [{"name": "Manager"}])
    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=str(project))

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    monkeypatch.setattr("services.agent_handoff_options._people", lambda root: ([], None))
    assert (await get_handoff_options(proj.id, SimpleNamespace(id="u"), None))["roles"] == ["Manager"]
    paths = [r.path for r in router.routes if "GET" in getattr(r, "methods", set())]
    assert paths.index("/api/projects/{project_id}/agent-definitions/handoff-options") < \
        paths.index("/api/projects/{project_id}/agent-definitions/{agent_id}"), \
        "declared first, or FastAPI reads 'handoff-options' as an agent id"

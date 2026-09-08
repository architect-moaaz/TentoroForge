"""POST /api/projects/{id}/preview/start and GET .../preview/status.

Driven as functions, the way test_blueprint_endpoint drives its endpoint:
the auth and DB dependencies are stubbed and ``start_preview`` is recorded
rather than run, because what these assert is *where* the dev server is
started and *what the caller is told* — not that Next boots.

* the Blueprint engine writes the app to ``<output_dir>/app``; the server
  must start there, not at the project root
* a project generated before that layout has package.json at the root,
  and starts there
* a project with no application yet is told so, rather than left waiting
  thirty seconds for a server that cannot come up
* both endpoints return the proxy path the browser reaches the preview at,
  keyed by the short id the server was registered under
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException


class _FakeProject:
    def __init__(self, output_dir: str | None, short_id: str = "abc12345"):
        self.output_dir = output_dir
        self.short_id = short_id
        self.preview_port = None


class _FakeUser:
    id = "u-1"
    email = "test@example.com"


class _FakeDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture()
def project(monkeypatch, tmp_path):
    """Stub the project fetch; return the project the endpoint will see."""
    proj = _FakeProject(output_dir=str(tmp_path))

    async def _fake_get_project(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.projects.get_project_with_auth", _fake_get_project)
    return proj


@pytest.fixture()
def started(monkeypatch):
    """Record start_preview calls instead of spawning `next dev`."""
    calls: list[tuple[str, str]] = []

    async def _fake_start(project_id: str, output_dir: str) -> int:
        calls.append((project_id, output_dir))
        return 3210

    monkeypatch.setattr("routers.projects.start_preview", _fake_start)
    return calls


@pytest.mark.asyncio
async def test_starts_in_the_projected_app_directory(tmp_path, project, started):
    from routers.projects import preview_start

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")

    db = _FakeDb()
    body = await preview_start(project_id=uuid.uuid4(), user=_FakeUser(), db=db)

    assert started == [("abc12345", str(tmp_path / "app"))]
    assert body == {"port": 3210, "servePath": "/api/projects/abc12345/preview/serve"}
    assert project.preview_port == 3210
    assert db.commits == 1


@pytest.mark.asyncio
async def test_starts_at_the_root_for_the_older_layout(tmp_path, project, started):
    from routers.projects import preview_start

    (tmp_path / "package.json").write_text("{}")

    await preview_start(project_id=uuid.uuid4(), user=_FakeUser(), db=_FakeDb())

    assert started == [("abc12345", str(tmp_path))]


@pytest.mark.asyncio
async def test_no_application_yet_is_said_not_waited_for(tmp_path, project, started):
    from routers.projects import preview_start

    with pytest.raises(HTTPException) as exc:
        await preview_start(project_id=uuid.uuid4(), user=_FakeUser(), db=_FakeDb())

    assert exc.value.status_code == 404
    assert "No application to preview yet" in exc.value.detail
    assert started == []


@pytest.mark.asyncio
async def test_status_names_the_serve_path(monkeypatch, project):
    from routers.projects import preview_status

    monkeypatch.setattr("routers.projects.get_preview_port", lambda short_id: 3210)
    body = await preview_status(project_id=uuid.uuid4(), user=_FakeUser(), db=_FakeDb())
    assert body == {
        "running": True,
        "port": 3210,
        "servePath": "/api/projects/abc12345/preview/serve",
    }

    monkeypatch.setattr("routers.projects.get_preview_port", lambda short_id: None)
    body = await preview_status(project_id=uuid.uuid4(), user=_FakeUser(), db=_FakeDb())
    assert body["running"] is False and body["port"] is None

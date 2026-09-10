"""Tests for the POST /api/projects/{id}/rebuild-blueprint endpoint.

We drive the endpoint function directly (bypassing FastAPI's auth /
DB dependencies) because the project's router tests don't run against
a live auth stack. The behaviour we care about here is:

* it delegates to :func:`services.blueprint_writer.write_blueprint_safe`
* it returns the writer's dict shape unchanged
* it 400s a project without an output_dir
* it 404s an output_dir that doesn't exist on disk

Full end-to-end coverage lands with the router smoke test that runs
against a real DB.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _FakeProject:
    def __init__(self, output_dir: str | None):
        self.output_dir = output_dir


class _FakeUser:
    id = "u-1"
    email = "test@example.com"


@pytest.fixture()
def _patched_auth(monkeypatch):
    """Stub the project fetch so the endpoint doesn't hit the DB."""
    async def _fake_get_project(project_id, user, db):
        return _fake_get_project.project
    _fake_get_project.project = _FakeProject(output_dir=None)
    monkeypatch.setattr(
        "services.project_service.get_project_with_auth", _fake_get_project,
    )
    monkeypatch.setattr(
        "routers.projects.get_project_with_auth", _fake_get_project,
    )
    return _fake_get_project


@pytest.mark.asyncio
async def test_rebuild_writes_blueprint(tmp_path, _patched_auth):
    from routers.projects import rebuild_blueprint

    _patched_auth.project = _FakeProject(output_dir=str(tmp_path))
    import uuid as _uuid
    result = await rebuild_blueprint(
        project_id=_uuid.uuid4(),
        user=_FakeUser(),
        db=None,
    )
    assert result["written"] is True
    assert (tmp_path / "BLUEPRINT.md").is_file()
    assert result["byte_size"] > 0


@pytest.mark.asyncio
async def test_rebuild_400_without_output_dir(tmp_path, _patched_auth):
    from routers.projects import rebuild_blueprint
    import uuid as _uuid

    _patched_auth.project = _FakeProject(output_dir=None)
    with pytest.raises(HTTPException) as exc:
        await rebuild_blueprint(
            project_id=_uuid.uuid4(),
            user=_FakeUser(),
            db=None,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_rebuild_404_when_dir_missing(tmp_path, _patched_auth):
    from routers.projects import rebuild_blueprint
    import uuid as _uuid

    _patched_auth.project = _FakeProject(
        output_dir=str(tmp_path / "does-not-exist"),
    )
    with pytest.raises(HTTPException) as exc:
        await rebuild_blueprint(
            project_id=_uuid.uuid4(),
            user=_FakeUser(),
            db=None,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_rebuild_records_manual_source(tmp_path, _patched_auth):
    from routers.projects import rebuild_blueprint
    import uuid as _uuid
    import json as _json

    _patched_auth.project = _FakeProject(output_dir=str(tmp_path))
    await rebuild_blueprint(
        project_id=_uuid.uuid4(),
        user=_FakeUser(),
        db=None,
    )
    log_path = tmp_path / ".blueprint-log.jsonl"
    assert log_path.is_file()
    entry = _json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["source"] == "manual"
    assert "test@example.com" in entry["summary"]

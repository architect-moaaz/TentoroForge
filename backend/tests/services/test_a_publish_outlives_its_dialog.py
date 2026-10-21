"""A publish ran inside the HTTP response streaming its progress, so a dialog
closed half-way cancelled it and left its row at "snapshot" forever (Mark 8 on
forge-v3, 2026-10-17, and 41 rows like it). The publish now runs on its own
task; the stream only listens. Rows an earlier platform left unfinished are
closed as interrupted when the history is read."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.deployment import Deployment
from services.deploy import runs


class _Sessions:
    """A session factory that hands out a dummy session (the fake publish needs none)."""
    def __call__(self):
        class _S:
            async def __aenter__(self): return object()
            async def __aexit__(self, *a): return False
        return _S()


@pytest.mark.asyncio
async def test_the_publish_goes_on_when_nobody_is_listening():
    finished = asyncio.Event()

    async def publish(_session):
        for stage in ("snapshot", "provision_db", "upload", "build", "done"):
            await asyncio.sleep(0.01)
            yield SimpleNamespace(stage=stage, message=stage, progress=None, data={})
        finished.set()

    queue = runs.start(publish, _Sessions())
    reader = runs.frames(queue)
    first = await reader.__anext__()
    assert '"stage": "snapshot"' in first
    await reader.aclose()          # the dialog closed
    await asyncio.wait_for(finished.wait(), 2)   # the publish still finished


@pytest.mark.asyncio
async def test_a_leaked_error_still_ends_the_stream_with_an_error_frame():
    async def publish(_session):
        yield SimpleNamespace(stage="snapshot", message="", progress=None, data={})
        raise RuntimeError("vercel said no")
    got = [f async for f in runs.frames(runs.start(publish, _Sessions()))]
    assert '"stage": "error"' in got[-1] and "vercel said no" in got[-1]


@pytest.mark.asyncio
async def test_rows_left_unfinished_are_closed_as_interrupted(test_db, auth_client, org_id):
    from database import get_db
    from main import app
    project = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Mark 8"})).json()
    pid = uuid.UUID(project["id"])
    gen = app.dependency_overrides.get(get_db, get_db)()
    db = await gen.__anext__()
    now = datetime.now(timezone.utc)
    old = Deployment(project_id=pid, target="vercel", status="snapshot", environment="test", created_at=now - timedelta(hours=3))
    fresh = Deployment(project_id=pid, target="vercel", status="snapshot", environment="test", created_at=now - timedelta(minutes=2))
    done = Deployment(project_id=pid, target="vercel", status="succeeded", environment="test", created_at=now - timedelta(hours=5))
    db.add_all([old, fresh, done])
    await db.commit()
    assert await runs.close_stale(db, pid) == 1
    rows = {r.id: r for r in (await db.execute(select(Deployment).where(Deployment.project_id == pid))).scalars()}
    assert rows[old.id].status == "failed" and rows[old.id].error == runs.INTERRUPTED and rows[old.id].finished_at
    assert rows[fresh.id].status == "snapshot"     # may still be running
    assert rows[done.id].status == "succeeded"
    await gen.aclose()


@pytest.mark.asyncio
async def test_a_publish_the_last_restart_cut_off_is_closed_at_once(test_db, auth_client, org_id, monkeypatch):
    """Personal Finance's publish began in the minute a cutover restarted the
    backend and spun at "snapshot" for 45 minutes (u8w3uw4j, 2026-10-21): a
    row older than the running platform is closed straight away."""
    from database import get_db
    from main import app
    project = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Personal Finance"})).json()
    pid = uuid.UUID(project["id"])
    gen = app.dependency_overrides.get(get_db, get_db)()
    db = await gen.__anext__()
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(runs, "platform_started", lambda: now - timedelta(minutes=1))
    cut_off = Deployment(project_id=pid, target="vercel", status="snapshot", environment="test",
                         created_at=now - timedelta(minutes=2))
    running = Deployment(project_id=pid, target="vercel", status="build", environment="test",
                         created_at=now - timedelta(seconds=20))
    db.add_all([cut_off, running])
    await db.commit()
    assert await runs.close_stale(db, pid) == 1
    rows = {r.id: r for r in (await db.execute(select(Deployment).where(Deployment.project_id == pid))).scalars()}
    assert rows[cut_off.id].status == "failed" and rows[cut_off.id].error == runs.INTERRUPTED
    assert rows[running.id].status == "build"
    await gen.aclose()


def test_the_platform_start_is_read_or_said_unknown():
    started = runs.platform_started()
    assert started is None or started <= datetime.now(timezone.utc)

"""A restart of the platform no longer leaves an Expo build on "in progress" for ever.

The check on a build lives in the platform's own process, so when the process was stopped (the Claude app stops its servers now
and then) nothing was left to ask Expo, and the row stayed open though the build had finished (Gather, 2026-10-23). At start,
every build still open is watched again; one that never reached Expo is ended and says so."""
from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from routers import mobile_builds as mb

NOW = datetime.now(timezone.utc)


def row(*, eas="e-1", age=120, status="in_progress"):
    return types.SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), eas_build_id=eas, status=status, platform="android",
                                 created_at=NOW - timedelta(seconds=age))


class FakeSession:
    def __init__(self, rows, projects):
        self.rows, self.projects = rows, projects

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        rows = self.rows
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: rows))

    async def get(self, model, key):
        return self.projects.get(key)


@pytest.fixture
def wired(monkeypatch):
    seen = types.SimpleNamespace(failed=[], polled=[], rows=[], projects={})
    monkeypatch.setattr(mb, "async_session", lambda: FakeSession(seen.rows, seen.projects))

    async def failed(row_id, message):
        seen.failed.append((row_id, message))

    async def creds(org_id, sess):
        return types.SimpleNamespace(expo_eas_token="tok")

    async def poll(row_id, mobile_dir, eas_id, creds, *, already_waited=0.0):
        seen.polled.append((row_id, mobile_dir, eas_id, round(already_waited)))

    monkeypatch.setattr(mb, "_mark_failed", failed)
    monkeypatch.setattr(mb, "load_mobile_credentials", creds)
    monkeypatch.setattr(mb, "_poll_until_done", poll)
    monkeypatch.setattr(mb, "_blueprint_of", lambda output_dir: {})
    monkeypatch.setattr(mb.native_build, "choose_target", lambda output_dir, doc: types.SimpleNamespace(kind="native", dir=f"{output_dir}/native"))
    return seen


def add(seen, r):
    seen.rows.append(r)
    seen.projects[r.project_id] = types.SimpleNamespace(output_dir=f"/out/{r.project_id}", org_id=uuid.uuid4())
    return r


def run():
    async def go():
        taken = await mb.resume_open_builds()
        await asyncio.gather(*list(mb._resumed))
        return taken
    return asyncio.run(go())


def test_a_build_on_expo_is_watched_again_with_the_time_it_has_already_taken(wired):
    r = add(wired, row(age=300))
    assert run() == 1
    (row_id, mobile_dir, eas_id, waited), = wired.polled
    assert (row_id, mobile_dir, eas_id) == (r.id, f"/out/{r.project_id}/native", "e-1")
    assert 300 <= waited <= 330, "the time the build has already taken, not another whole hour"
    assert wired.failed == []


def test_a_build_that_never_reached_expo_is_ended_and_says_so(wired):
    r = add(wired, row(eas=None))
    assert run() == 0
    assert wired.polled == []
    assert wired.failed[0][0] == r.id and "restarted before this build reached Expo" in wired.failed[0][1]


def test_a_build_too_old_to_follow_is_ended_and_says_where_to_look(wired):
    r = add(wired, row(age=mb._RESUME_MAX_AGE_SEC + 60))
    assert run() == 0
    assert wired.polled == [] and "Look for it on Expo" in wired.failed[0][1]
    assert wired.failed[0][0] == r.id


def test_one_build_that_cannot_be_followed_does_not_stop_the_others(wired, monkeypatch):
    first, second = add(wired, row()), add(wired, row(eas="e-2"))
    real = mb.load_mobile_credentials

    async def creds(org_id, sess):
        if not wired.polled and not hasattr(wired, "tried"):
            wired.tried = True
            raise RuntimeError("no Expo token for this organisation")
        return await real(org_id, sess)

    monkeypatch.setattr(mb, "load_mobile_credentials", creds)
    assert run() == 1
    assert [p[2] for p in wired.polled] == ["e-2"]
    assert first.id != second.id


def test_nothing_open_means_nothing_to_do(wired):
    assert run() == 0 and wired.polled == [] and wired.failed == []

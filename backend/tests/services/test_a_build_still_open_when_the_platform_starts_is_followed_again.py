"""A restart of the platform no longer leaves an Expo build on "in progress" for ever, and never ends a finished one as failed.

The check on a build lives in the platform's own process, so when the process was stopped (the Claude app stops its servers now
and then) nothing was left to ask Expo, and the row stayed open though the build had finished (Gather, 2026-10-23). At start, every
build still open is asked about and watched again; one that never reached Expo is ended and says so.

THE CLOCK NEVER DECIDES BEFORE EXPO HAS BEEN ASKED. A build two hours old when the platform starts has used up the hour a build is
given, and the first version of this ended it as "timed out" without a question: the very build it was written for, finished on
Expo, turned into a failure (review of PR #31, 2026-10-26). The tests under "the clock" run the real loop against a fake Expo.

Only one worker follows the builds: the backend runs several, and each runs the start-up hook."""
from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from routers import mobile_builds as mb

def _now() -> datetime:
    """Read when the row is made: a time taken when the file was loaded aged
    every row by however long the tests before this one ran (a full run
    failed it by 22 s)."""
    return datetime.now(timezone.utc)


def row(*, eas="e-1", age=120, status="in_progress"):
    return types.SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), eas_build_id=eas, status=status, platform="android",
                                 created_at=_now() - timedelta(seconds=age))


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

    async def poll(row_id, mobile_dir, eas_id, creds, *, already_waited=0.0, ask_first=False):
        seen.polled.append((row_id, mobile_dir, eas_id, round(already_waited)))
        assert ask_first, "a build taken up again is asked about before its age is judged"

    async def alone():
        return True

    monkeypatch.setattr(mb, "_mark_failed", failed)
    monkeypatch.setattr(mb, "load_mobile_credentials", creds)
    monkeypatch.setattr(mb, "_poll_until_done", poll)
    monkeypatch.setattr(mb, "_first_worker", alone)
    monkeypatch.setattr(mb, "_blueprint_of", lambda output_dir: {})
    monkeypatch.setattr(mb.native_build, "choose_target",
                        lambda output_dir, doc: types.SimpleNamespace(kind="native", dir=f"{output_dir}/native"))
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


def test_a_build_too_old_to_follow_is_asked_about_once_and_ended_only_if_expo_says_it_is_going(wired, monkeypatch):
    asked = []

    async def still_going(row_id, mobile_dir, eas_id, creds):
        asked.append(eas_id)
        return False

    monkeypatch.setattr(mb, "_ask_once", still_going)
    r = add(wired, row(age=mb._RESUME_MAX_AGE_SEC + 60))
    assert run() == 0
    assert asked == ["e-1"], "Expo is asked, not the clock"
    assert wired.polled == [] and "Look for it on Expo" in wired.failed[0][1]
    assert wired.failed[0][0] == r.id


def test_one_build_that_cannot_be_followed_does_not_stop_the_others(wired, monkeypatch):
    first, second = add(wired, row()), add(wired, row(eas="e-2"))
    real_creds = mb.load_mobile_credentials
    state = {"tried": False}

    async def creds(org_id, sess):
        if not state["tried"]:
            state["tried"] = True
            raise RuntimeError("no Expo token for this organisation")
        return await real_creds(org_id, sess)

    monkeypatch.setattr(mb, "load_mobile_credentials", creds)
    assert run() == 1
    assert [p[2] for p in wired.polled] == ["e-2"]
    assert first.id != second.id


def test_nothing_open_means_nothing_to_do(wired):
    assert run() == 0 and wired.polled == [] and wired.failed == []


# ---- the clock never decides before Expo has been asked ---------------------------------------------------------------

class Store:
    """Rows kept in memory and read and written through the calls the platform makes."""

    def __init__(self):
        self.rows, self.projects, self.answers = {}, {}, []

    def add(self, r):
        self.rows[r.id] = r
        return r


class StoreSession:
    def __init__(self, store):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, model, key):
        return self.store.rows.get(key) or self.store.projects.get(key)

    async def execute(self, stmt):
        rows = [r for r in self.store.rows.values() if r.status not in ("completed", "failed", "canceled")]
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: rows))

    async def commit(self):
        return None


@pytest.fixture
def real(monkeypatch):
    store = Store()
    monkeypatch.setattr(mb, "async_session", lambda: StoreSession(store))

    async def poll(mobile_dir, eas_id, *, expo_token):
        return mb.BuildState(build_id=eas_id, status=store.answers.pop(0), artifact_url="https://expo.dev/a.apk")

    async def no_wait(_seconds):
        return None

    async def creds(org_id, sess):
        return types.SimpleNamespace(expo_eas_token="tok")

    async def alone():
        return True

    monkeypatch.setattr(mb, "poll_build", poll)
    monkeypatch.setattr(mb.asyncio, "sleep", no_wait)
    monkeypatch.setattr(mb, "load_mobile_credentials", creds)
    monkeypatch.setattr(mb, "_first_worker", alone)
    monkeypatch.setattr(mb, "_blueprint_of", lambda output_dir: {})
    monkeypatch.setattr(mb.native_build, "choose_target",
                        lambda output_dir, doc: types.SimpleNamespace(kind="native", dir=f"{output_dir}/native"))
    return store


def stored(real, age=0):
    r = real.add(types.SimpleNamespace(
        id=uuid.uuid4(), project_id=uuid.uuid4(), eas_build_id="e-1", status="in_progress", platform="android",
        created_at=_now() - timedelta(seconds=age), artifact_url=None, logs_url=None, error_message=None, completed_at=None))
    real.projects[r.project_id] = types.SimpleNamespace(output_dir=f"/out/{r.project_id}", org_id=uuid.uuid4())
    return r


def follow(r, age):
    creds = types.SimpleNamespace(expo_eas_token="tok")
    asyncio.run(mb._poll_until_done(r.id, "/out/native", r.eas_build_id, creds, already_waited=age, ask_first=True))


def test_a_build_that_finished_while_the_platform_was_down_ends_completed_not_timed_out(real):
    """The case this was written for: two hours old, finished on Expo. The clock must not decide before Expo is asked."""
    r = stored(real)
    real.answers = ["finished"]
    follow(r, age=2 * 60 * 60)
    assert r.status == "completed" and r.artifact_url == "https://expo.dev/a.apk" and r.completed_at is not None
    assert not r.error_message


def test_a_build_that_failed_on_expo_ends_failed_with_expos_word_not_a_timeout(real):
    r = stored(real)
    real.answers = ["errored"]
    follow(r, age=3 * 60 * 60)
    assert r.status == "failed" and "Timed out" not in (r.error_message or "")


def test_a_build_expo_says_is_still_going_after_more_than_an_hour_is_ended_as_timed_out(real):
    r = stored(real)
    real.answers = ["in_progress"]
    follow(r, age=2 * 60 * 60)
    assert r.status == "failed" and "Timed out" in r.error_message


def test_a_build_still_going_and_young_is_followed_until_it_finishes(real):
    r = stored(real)
    real.answers = ["in_progress", "in_progress", "finished"]
    follow(r, age=120)
    assert r.status == "completed" and real.answers == []


def test_a_build_older_than_the_resume_limit_that_finished_ends_completed(real):
    r = stored(real, age=mb._RESUME_MAX_AGE_SEC + 3600)
    real.answers = ["finished"]
    assert asyncio.run(mb.resume_open_builds()) == 0
    assert r.status == "completed", "asked once, and the answer was finished"


def test_a_build_older_than_the_resume_limit_that_is_still_going_ends_as_too_old(real):
    r = stored(real, age=mb._RESUME_MAX_AGE_SEC + 3600)
    real.answers = ["in_progress"]
    asyncio.run(mb.resume_open_builds())
    assert r.status == "failed" and "too old to follow" in r.error_message


def test_a_two_hour_old_build_found_at_start_ends_completed_through_the_whole_path(real):
    """From `resume_open_builds` to the row: the start-up hook, the poll task and the answer, with nothing replaced but Expo."""
    r = stored(real, age=2 * 60 * 60)
    real.answers = ["finished"]

    async def go():
        taken = await mb.resume_open_builds()
        await asyncio.gather(*list(mb._resumed))
        return taken

    assert asyncio.run(go()) == 1
    assert r.status == "completed"


# ---- one worker takes the builds up ---------------------------------------------------------------------------------

class Conn:
    def __init__(self, granted):
        self.granted, self.closed, self.committed = granted, False, False

    async def execute(self, stmt, params=None):
        return types.SimpleNamespace(scalar=lambda: self.granted)

    async def commit(self):
        self.committed = True

    async def close(self):
        self.closed = True


def engine_of(dialect, conn=None):
    async def connect():
        return conn
    return types.SimpleNamespace(dialect=types.SimpleNamespace(name=dialect), connect=connect)


def test_the_worker_that_gets_the_lock_follows_the_builds_and_keeps_the_connection(monkeypatch):
    import database
    conn = Conn(True)
    monkeypatch.setattr(database, "engine", engine_of("postgresql", conn))
    monkeypatch.setattr(mb, "_resume_lock_connection", None)
    assert asyncio.run(mb._first_worker()) is True
    assert mb._resume_lock_connection is conn and not conn.closed and conn.committed


def test_a_second_worker_does_not_get_it_and_follows_nothing(monkeypatch):
    import database
    conn = Conn(False)
    monkeypatch.setattr(database, "engine", engine_of("postgresql", conn))
    monkeypatch.setattr(mb, "_resume_lock_connection", None)
    assert asyncio.run(mb._first_worker()) is False
    assert conn.closed and mb._resume_lock_connection is None

    def not_read():
        raise AssertionError("a worker without the lock must not read the builds")

    monkeypatch.setattr(mb, "async_session", not_read)
    monkeypatch.setattr(database, "engine", engine_of("postgresql", Conn(False)))
    assert asyncio.run(mb.resume_open_builds()) == 0


def test_without_postgres_there_is_one_process_and_it_follows(monkeypatch):
    import database
    monkeypatch.setattr(database, "engine", engine_of("sqlite"))
    assert asyncio.run(mb._first_worker()) is True

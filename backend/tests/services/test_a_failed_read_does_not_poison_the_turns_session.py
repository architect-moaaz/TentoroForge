"""One unreadable thing must not take the next read down with it.

A turn reads the organisation's brand profile, then its MCP servers, on ONE shared session. When
the profile table did not exist (`org_brand_profiles`), the failed statement left the Postgres
transaction aborted — every statement after it answered `InFailedSQLTransaction` — so the MCP read
failed too, and Smith silently could not see the organisation's servers. Each best-effort read now
runs in a SAVEPOINT: a failure rolls back only itself.

The session here is a fake that records its savepoints; the failure semantics themselves are
Postgres's, so what is pinned is that every best-effort read is inside one, that a failure inside
one is swallowed as before, and that the read after it still runs.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from routers import blueprint_generate as bg


class FakeSession:
    """Records `begin_nested()` use; a statement run outside one after a failure is poisoned."""

    def __init__(self, fail_execute: bool = False):
        self.fail_execute = fail_execute
        self.savepoints_entered = 0
        self.savepoints_rolled_back = 0
        self.poisoned = False
        self._depth = 0

    def begin_nested(self):
        outer = self

        class _Savepoint:
            async def __aenter__(self_inner):
                outer.savepoints_entered += 1
                outer._depth += 1
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):
                outer._depth -= 1
                if exc_type is not None:
                    outer.savepoints_rolled_back += 1  # the failure is undone here …
                    return False                      # … and still propagates to the caller's except
                return False

        return _Savepoint()

    async def execute(self, *_a, **_k):
        if self.poisoned:
            raise RuntimeError("InFailedSQLTransaction: current transaction is aborted")
        if self.fail_execute:
            if self._depth == 0:
                self.poisoned = True  # outside a savepoint a failed statement aborts the transaction
            raise RuntimeError('relation "org_brand_profiles" does not exist')
        return SimpleNamespace(scalar_one_or_none=lambda: None)


def project():
    return SimpleNamespace(org_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_an_unreadable_brand_profile_is_no_profile_and_leaves_the_session_usable(tmp_path):
    db = FakeSession(fail_execute=True)

    adopted = await bg._adopt_brand_language(tmp_path, project(), db)

    assert adopted is False
    assert db.savepoints_entered == 1 and db.savepoints_rolled_back == 1, "the read ran in a savepoint"
    assert db.poisoned is False, "so the transaction the turn goes on using is not aborted"


@pytest.mark.asyncio
async def test_the_mcp_read_after_a_failed_brand_read_still_runs(tmp_path, monkeypatch):
    db = FakeSession(fail_execute=True)
    await bg._adopt_brand_language(tmp_path, project(), db)

    from services.blueprint import mcp_catalog

    reached = []

    async def refresh(output_dir, org_id, session):
        reached.append(True)
        await session.execute("select 1 from platform_mcp_servers")  # the statement that used to die

    monkeypatch.setattr(mcp_catalog, "refresh", refresh)
    db.fail_execute = False  # the profile table is the only thing that was missing
    await bg._adopt_mcp_servers(Path(tmp_path), project(), db)

    assert reached == [True]
    assert db.poisoned is False


@pytest.mark.asyncio
async def test_a_failing_mcp_read_is_swallowed_and_does_not_stop_the_settings_write(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}", encoding="utf-8")
    db = FakeSession()

    from services import env_writer
    from services.blueprint import mcp_catalog

    async def boom(*_a, **_k):
        raise RuntimeError("server down")

    written = []

    async def write_env(output_dir, org_id, session):
        written.append(True)

    monkeypatch.setattr(mcp_catalog, "refresh", boom)
    monkeypatch.setattr(env_writer, "write_env_local_from_platform", write_env)

    await bg._adopt_mcp_servers(tmp_path, project(), db)  # must not raise

    assert written == [True], "the second best-effort step is not skipped by the first one's failure"
    assert db.savepoints_entered == 2, "each read has a savepoint of its own"
    assert db.savepoints_rolled_back == 1, "only the failed one was rolled back"


@pytest.mark.asyncio
async def test_no_org_is_still_a_quiet_no_op(tmp_path):
    db = FakeSession()
    assert await bg._adopt_brand_language(tmp_path, SimpleNamespace(org_id=None), db) is False
    await bg._adopt_mcp_servers(tmp_path, SimpleNamespace(org_id=None), db)
    assert db.savepoints_entered == 0

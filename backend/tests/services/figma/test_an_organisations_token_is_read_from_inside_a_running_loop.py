"""The organisation's Figma settings are read even when the lookup is
bridged from inside a running event loop.

`config_for` is synchronous and bridges its two queries with `_run`. Inside
the server that bridge runs the query on another loop, and a session from
the shared engine then carries connections whose futures belong to the
server's loop: "got Future attached to a different loop". The lookup caught
that as "store unavailable" and fell back to the environment on every
extraction, so a token saved on the organisation's settings page was never
the one used. The queries now open their connections on the loop that runs
them.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A file-backed database holding one organisation's Figma token."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'store.db'}"
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "a" * 64)
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    import config

    monkeypatch.setattr(config, "DATABASE_URL", url)

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from database import Base
    from models.platform_integration import PlatformIntegration
    from services.platform_integrations_crypto import encrypt

    org_id = uuid.uuid4()

    async def fill() -> None:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: PlatformIntegration.__table__.create(sync_conn)
            )
        ct, iv = encrypt("figma", "figd_stored_for_this_organisation")
        async with async_sessionmaker(engine)() as db:
            db.add(PlatformIntegration(org_id=org_id, provider="figma",
                                       key="FIGMA_TOKEN", value_ct=ct, value_iv=iv))
            await db.commit()
        await engine.dispose()

    asyncio.run(fill())
    del Base  # the table was created directly; the base is not needed further
    return org_id


def test_the_stored_token_is_read_from_inside_a_running_loop(store):
    from services.figma.integrations import _fetch, _run

    async def inside_the_server() -> dict[str, str]:
        # The bridge is called while this loop is running, as the server does.
        return _run(_fetch(store, "figma"))

    values = asyncio.run(inside_the_server())

    assert values == {"FIGMA_TOKEN": "figd_stored_for_this_organisation"}
    assert "FIGMA_TOKEN" not in os.environ, "the value came from the store, not the environment"


def test_the_stored_token_is_read_from_a_plain_thread(store):
    """Executors fan out on threads with no loop of their own."""
    import threading

    from services.figma.integrations import _fetch, _run

    out: dict[str, str] = {}
    worker = threading.Thread(target=lambda: out.update(_run(_fetch(store, "figma"))))
    worker.start()
    worker.join()

    assert out == {"FIGMA_TOKEN": "figd_stored_for_this_organisation"}

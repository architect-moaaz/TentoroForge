"""The platform's background loops run once, however many workers there are.

The backend runs two workers (`--workers 2`) and every startup hook ran in
both: the workflow timer scheduler fired a due timer twice, an Expo build was
followed twice, the domain and lost-run watches did their work twice (audit,
2026-11-01). One worker leads: it holds a Postgres advisory lock on a
connection of its own for as long as it lives, and only the leader runs the
loops. When it dies its connection closes, the lock is free, and the other
worker takes it within `RETRY_S` and starts them.

On SQLite (tests, a laptop without Postgres) there is one process: it leads.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

#: The advisory lock's key: any constant the platform uses for nothing else.
LOCK_KEY = 0x464F524745  # "FORGE"
RETRY_S = 30.0

_conn = None  # the leader's own connection; held, never returned to a pool


async def _try_lead() -> bool:
    global _conn
    from sqlalchemy import text

    from database import engine

    if engine.dialect.name != "postgresql":
        return True
    conn = await engine.connect()
    try:
        got = (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar()
    except Exception:
        await conn.close()
        raise
    if got:
        _conn = conn
        return True
    await conn.close()
    return False


async def run_when_leading(starts: list[Callable[[], Awaitable[None]]], *, retry_s: float = RETRY_S) -> None:
    """Start every one of `starts` once this worker leads; until then, ask
    again every `retry_s`. Runs for the life of the worker."""
    while True:
        try:
            if await _try_lead():
                logger.info("[leader] this worker runs the background loops")
                for start in starts:
                    try:
                        await start()
                    except Exception:  # noqa: BLE001 — one loop failing to start leaves the others
                        logger.exception("[leader] %s did not start", getattr(start, "__name__", start))
                return
        except Exception:  # noqa: BLE001 — no database yet: asked again
            logger.warning("[leader] could not ask for the lead", exc_info=True)
        await asyncio.sleep(retry_s)


async def release() -> None:
    """At shutdown: the lead goes now, not when the connection times out."""
    global _conn
    if _conn is not None:
        try:
            await _conn.close()
        except Exception:  # noqa: BLE001 — the lock goes with the connection either way
            pass
        _conn = None


def leading() -> bool:
    """Whether this worker holds the lead (always, on SQLite)."""
    from database import engine

    return engine.dialect.name != "postgresql" or _conn is not None


__all__ = ["run_when_leading", "release", "leading", "LOCK_KEY"]

"""A publish is the server's to finish, not the browser's.

The publish ran inside the HTTP response that streamed its progress. When
that connection dropped — the Publish dialog closed, the page reloaded, a
second publish replaced the first — the server cancelled the response and the
publish with it, half-way. Cancellation is not an error, so the row was never
closed: it sat at "snapshot" (or "pending", "build") forever and the history
showed a spinner for it (Mark 8 and 41 others on forge-v3, 2026-10-17).

`start` runs the publish as its own task with its own database session; the
browser only listens. `close_stale` closes what an earlier platform left
running — a row that has not finished long after any publish could have.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.deployment import Deployment

log = logging.getLogger(__name__)

#: Statuses a publish ends in. Anything else is still running — or was cut off.
TERMINAL = ("succeeded", "succeeded_with_warnings", "failed")
#: Longer than any publish runs: the build is polled for five minutes, and the
#: migration trial and Neon provisioning come before it.
STALE_AFTER = timedelta(minutes=45)
INTERRUPTED = ("The publish stopped before it finished — the platform restarted or lost its "
               "connection to it. Nothing from it went live; publish again.")

#: Publishes running in this worker, held so the event loop does not drop them.
_RUNNING: set[asyncio.Task] = set()


def start(publish: Callable[[AsyncSession], AsyncIterator[Any]],
          sessions: async_sessionmaker) -> asyncio.Queue:
    """Run `publish(session)` to its end on its own task and session; return a
    queue of its progress frames (dicts), closed with `None`. Whoever reads the
    queue may stop at any time: the publish goes on and closes its own row."""
    queue: asyncio.Queue = asyncio.Queue()

    async def run() -> None:
        try:
            async with sessions() as own:
                async for evt in publish(own):
                    queue.put_nowait({"stage": evt.stage, "message": evt.message,
                                      "progress": evt.progress, "data": evt.data})
        except Exception as exc:  # noqa: BLE001 — the provider catches its own; this is the backstop
            log.exception("publish task leaked an exception")
            queue.put_nowait({"stage": "error", "message": str(exc)})
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(run())
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return queue


async def frames(queue: asyncio.Queue) -> AsyncIterator[str]:
    """The queue as server-sent events, until the publish ends."""
    while True:
        item = await queue.get()
        if item is None:
            return
        yield f"data: {json.dumps(item)}\n\n"


async def close_stale(db: AsyncSession, project_id: Any = None) -> int:
    """Close every publish row that is still not finished long after any
    publish could have been: failed, with the reason said. Returns how many."""
    now = datetime.now(timezone.utc)
    cond = [Deployment.status.notin_(TERMINAL), Deployment.created_at < now - STALE_AFTER]
    if project_id is not None:
        cond.append(Deployment.project_id == project_id)
    res = await db.execute(update(Deployment).where(*cond)
                           .values(status="failed", error=INTERRUPTED, finished_at=now))
    if res.rowcount:
        await db.commit()
        log.info("[deploy] closed %d publish(es) left unfinished", res.rowcount)
    return int(res.rowcount or 0)


__all__ = ["TERMINAL", "STALE_AFTER", "INTERRUPTED", "start", "frames", "close_stale"]

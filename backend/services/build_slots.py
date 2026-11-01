"""At most `SLOTS` builds run at once, across every worker.

Nothing limited them: each build is a thread in whichever worker took the
request, with its model calls, its app server and its checks, and the host
has died of out-of-memory under leftover servers before (forge-v3,
2026-10). A build holds one slot for as long as its graph runs: on Postgres
slot i is the advisory lock `SLOT_KEY_BASE + i`, held on a connection of its
own (the pattern `services.leader` uses for the lead), so a worker that dies
frees its slots with its connections. A build that finds every slot taken
waits, says so once on its stream, and asks again every `POLL_S`.

On SQLite (tests, a laptop) there is one process, and the slots are a set in
its memory.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Iterator

logger = logging.getLogger(__name__)

#: How many builds the platform runs at once, across both workers.
SLOTS = max(1, int(os.environ.get("FORGE_BUILD_SLOTS") or 2))
#: Slot i is advisory lock SLOT_KEY_BASE + i: beside the lead's key ("FORGE"), and used for nothing else.
SLOT_KEY_BASE = 0x464F524745 * 0x100
POLL_S = 5.0


def waiting_text(n: int) -> str:
    return (f"The platform is already running as many builds as it takes at once ({n}), so yours is "
            "waiting its turn and starts the moment one of them finishes. You don't need to do anything.")


class Slot:
    def __init__(self, index: int, conn: Any = None):
        self.index = index
        self.conn = conn

    def __repr__(self) -> str:
        return f"Slot({self.index})"


class Slots:
    """The cap as one process holds it. `engine` is the database the
    advisory locks are taken in; any engine but Postgres keeps them in memory."""

    def __init__(self, n: int | None = None, engine: Any = None, key_base: int = SLOT_KEY_BASE):
        self.n = SLOTS if n is None else n
        self._engine = engine
        self.key_base = key_base
        self._held: set[int] = set()
        self._lock = threading.Lock()

    @property
    def engine(self) -> Any:
        if self._engine is None:
            from database import engine
            self._engine = engine
        return self._engine

    @property
    def shared(self) -> bool:
        """Whether the slots are shared with other processes (Postgres)."""
        return self.engine.dialect.name == "postgresql"

    async def try_take(self) -> Slot | None:
        """A free slot, now, or None when every one is taken."""
        if not self.shared:
            with self._lock:
                for i in range(self.n):
                    if i not in self._held:
                        self._held.add(i)
                        return Slot(i)
            return None
        from sqlalchemy import text

        conn = await self.engine.connect()
        try:
            for i in range(self.n):
                got = (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"),
                                          {"k": self.key_base + i})).scalar()
                if got:
                    # A session lock outlives the transaction; ending it leaves the
                    # connection idle rather than idle in a transaction for an hour.
                    await conn.commit()
                    return Slot(i, conn)
            await conn.commit()
        except BaseException:
            await conn.invalidate()
            raise
        # Holds nothing, so it may go back to the pool.
        await conn.close()
        return None

    async def take(self, *, on_wait: Callable[[], Awaitable[None]] | None = None,
                   poll_s: float | None = None) -> Slot:
        """A slot, waiting for one if need be: `on_wait` is awaited once,
        the first time every slot is found taken."""
        poll_s = POLL_S if poll_s is None else poll_s
        told = False
        while True:
            slot = await self.try_take()
            if slot is not None:
                return slot
            if not told:
                told = True
                logger.info("[build-slots] all %d slots taken; a build waits", self.n)
                if on_wait is not None:
                    try:
                        await on_wait()
                    except Exception:  # noqa: BLE001 — saying so is a courtesy; the wait goes on
                        logger.warning("[build-slots] could not say a build is waiting", exc_info=True)
            await asyncio.sleep(poll_s)

    async def give_back(self, slot: Slot | None) -> None:
        if slot is None:
            return
        if slot.conn is None:
            with self._lock:
                self._held.discard(slot.index)
            return
        from sqlalchemy import text

        try:
            await slot.conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key_base + slot.index})
            await slot.conn.commit()
            await slot.conn.close()
        except Exception:  # noqa: BLE001 — a connection that cannot unlock is thrown away, and the lock with it
            logger.warning("[build-slots] slot %d: unlock failed; dropping its connection", slot.index,
                           exc_info=True)
            try:
                await slot.conn.invalidate()
            except Exception:  # noqa: BLE001
                pass
        slot.conn = None


_slots: Slots | None = None


def slots() -> Slots:
    """This process's slots."""
    global _slots
    if _slots is None:
        _slots = Slots()
    return _slots


@contextmanager
def held(emit: Callable[[str, dict], None] | None = None) -> Iterator[Slot | None]:
    """Hold a build slot for the block, from the worker thread a build runs
    in. The slot is taken on the event loop that owns the database's
    connections; while every slot is taken the build waits, its stream is
    told once (`emit`), and its job record says `waiting`."""
    from services import jobs
    from services.main_loop import get_main_loop

    job = jobs.current()
    loop = jobs.loop_of(job) or get_main_loop()
    pool = slots()
    waited = {"yes": False}

    async def on_wait() -> None:
        waited["yes"] = True
        if emit is not None:
            emit("message", {"text": waiting_text(pool.n)})
        if job:
            await jobs.set_status(job, "waiting")

    async def take() -> Slot:
        slot = await pool.take(on_wait=on_wait)
        if job and waited["yes"]:
            await jobs.set_status(job, "running")
        return slot

    slot = _run(loop, take(), pool)
    try:
        yield slot
    finally:
        if slot is not None:
            _run(loop, pool.give_back(slot), pool)


def _run(loop: asyncio.AbstractEventLoop | None, coro: Any, pool: Slots) -> Any:
    """`coro` run to its end from this (worker) thread."""
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if loop is not None and not loop.is_closed() and running is not loop:
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    if not pool.shared and running is None:
        return asyncio.run(coro)
    # Postgres with no loop to reach it from (a script): the build is not capped.
    coro.close()
    logger.warning("[build-slots] no event loop owns the database here; this build runs without a slot")
    return None


__all__ = ["SLOTS", "SLOT_KEY_BASE", "Slot", "Slots", "slots", "held", "waiting_text"]

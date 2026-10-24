"""The background worker: takes batches off the stream and applies them, and does the small chores that keep the numbers honest.

Started from the app's startup (main.py) in every backend process; each process is one consumer in the same group, so the stream's
entries are shared between them. ``FORGE_INSIGHTS_WORKER=0`` switches it off (tests, or a process that should only serve requests).

Per loop:
* READ a batch of entries, group them by project and apply each project's events in ONE transaction, then acknowledge them. If the
  database fails the entries are NOT acknowledged: they stay pending and come back (to this or another worker) once they have been idle
  for ``STALE_MS``. An entry that comes back too many times is moved to a dead-letter stream and logged, never retried forever;
* CLAIM entries another worker read and never finished (it was killed): that is the "a killed worker loses nothing" rule;
* every few seconds: write the dropped-event counts and key "last used" times to the database, and apply held thumbs whose turn has
  since arrived;
* every few seconds, in a loop of its own: refresh the people views (top users and so on) that are due, so the summary never has to;
* every quarter hour: retention (``agent_insights_store.housekeeping``), which also keeps tomorrow's raw partitions made.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from collections import defaultdict
from typing import Any

from services import agent_insights_bus as bus_mod
from services import agent_insights_ingest as ingest
from services import agent_insights_keys as keys
from services import agent_insights_people as people
from services import agent_insights_store as store

logger = logging.getLogger(__name__)

READ_COUNT = 40
BLOCK_MS = 1000
#: An entry read but not acknowledged for this long is taken over by another worker. A batch normally takes well under a second.
STALE_MS = 30_000
CLAIM_EVERY_S = 10.0
CHORES_EVERY_S = 5.0
HOUSEKEEPING_EVERY_S = 15 * 60.0
PEOPLE_EVERY_S = 5.0


def enabled() -> bool:
    return os.getenv("FORGE_INSIGHTS_WORKER", "1").strip().lower() not in ("0", "off", "false", "no")


class InsightsWorker:
    def __init__(self, session_factory=None, *, consumer: str | None = None, read_count: int = READ_COUNT, block_ms: int = BLOCK_MS,
                 stale_ms: int = STALE_MS) -> None:
        if session_factory is None:
            from database import async_session as session_factory
        self.session_factory = session_factory
        self.consumer = consumer or f"{socket.gethostname()}-{os.getpid()}-{id(self) % 10000}"
        self.read_count, self.block_ms, self.stale_ms = read_count, block_ms, stale_ms
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self.applied_events = 0
        self.dead_lettered = 0

    # -- applying -----------------------------------------------------------

    async def process(self, bus, entries: list[tuple[str, bytes, int]]) -> int:
        """Apply the entries (id, payload, times delivered) and acknowledge the ones that were applied. Returns how many were."""
        by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
        ids_by_project: dict[str, list[str]] = defaultdict(list)
        for entry_id, payload, delivered in entries:
            if delivered > bus_mod.MAX_DELIVERIES:
                logger.error("[insights] entry %s was delivered %d times without being applied: set aside in the dead-letter stream", entry_id, delivered)
                await bus.dead_letter(entry_id, payload)
                self.dead_lettered += 1
                continue
            try:
                doc = bus_mod.unpack(payload)
                by_project[doc["p"]].extend(doc["e"])
                ids_by_project[doc["p"]].append(entry_id)
            except Exception:  # noqa: BLE001 — an entry nobody can read can never be applied
                logger.exception("[insights] unreadable entry %s set aside", entry_id)
                await bus.dead_letter(entry_id, payload)
                self.dead_lettered += 1
        acked = 0
        for project, events in by_project.items():
            try:
                res = await self._apply_with_retry(project, events)
            except Exception:  # noqa: BLE001 — not acknowledged: it comes back after STALE_MS
                logger.exception("[insights] applying a batch for project %s failed; it will be retried", project)
                continue
            self.applied_events += res.new_turns
            try:
                await bus.hll_add(res.hll)
            except Exception:  # noqa: BLE001 — the distinct-people counters are a nicety; the exact counts are already saved
                logger.warning("[insights] could not update the distinct-people counters", exc_info=True)
            await bus.ack(ids_by_project[project])
            acked += len(ids_by_project[project])
        return acked

    async def _apply_with_retry(self, project: str, events: list[dict[str, Any]]) -> store.ApplyResult:
        for attempt in range(3):
            try:
                async with self.session_factory() as s, s.begin():
                    return await store.apply_events(s, project, events)
            except Exception as e:  # noqa: BLE001
                if attempt < 2 and ("deadlock" in str(e).lower() or "could not serialize" in str(e).lower()):
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("unreachable")

    async def run_once(self, bus, *, block_ms: int | None = None, claim: bool = False) -> int:
        """One pass: (optionally) take over stuck entries, then read new ones and apply them. Returns how many entries were applied."""
        n = 0
        if claim:
            stale = await bus.claim_stale(self.consumer, self.stale_ms, self.read_count)
            if stale:
                n += await self.process(bus, stale)
        fresh = await bus.read(self.consumer, self.read_count, self.block_ms if block_ms is None else block_ms)
        if fresh:
            n += await self.process(bus, [(i, p, 1) for i, p in fresh])
        return n

    async def drain(self, bus, *, timeout: float = 600.0) -> int:
        """Apply everything waiting (the load test and tests use this). Returns the entries applied."""
        total, end = 0, time.monotonic() + timeout
        while time.monotonic() < end:
            n = await self.run_once(bus, block_ms=0, claim=True)
            total += n
            if not n and await bus.depth(0) == 0:
                break
            if not n:
                await asyncio.sleep(0.05)
        return total

    async def chores(self) -> None:
        for step in (ingest.DROPPED.flush, keys.flush_touches):
            try:
                await step(self.session_factory)
            except Exception:  # noqa: BLE001
                logger.warning("[insights] a periodic write failed; trying again next time", exc_info=True)
        try:
            await store.sweep_pending_ratings(self.session_factory)
        except Exception:  # noqa: BLE001
            logger.warning("[insights] sweeping held ratings failed; trying again next time", exc_info=True)

    # -- running ------------------------------------------------------------

    async def _consume_loop(self) -> None:
        last_claim = 0.0
        while not self._stopping.is_set():
            try:
                bus = await bus_mod.get_bus()
                if bus is None:
                    await self._sleep(2.0)  # no Redis: the ingest route applies events itself, nothing to read
                    continue
                claim = time.monotonic() - last_claim >= CLAIM_EVERY_S
                if claim:
                    last_claim = time.monotonic()
                await self.run_once(bus, claim=claim)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("[insights] the worker could not reach the stream; trying again shortly", exc_info=True)
                await bus_mod.drop_bus()
                await self._sleep(2.0)

    async def _chores_loop(self) -> None:
        last_house: float | None = None  # None: not yet run, so the first pass makes sure the raw partitions exist
        while not self._stopping.is_set():
            try:
                await self.chores()
                if last_house is None or time.monotonic() - last_house >= HOUSEKEEPING_EVERY_S:
                    last_house = time.monotonic()  # set first: a failing housekeeping is retried in a quarter hour, not every 5 seconds
                    done = await store.housekeeping(self.session_factory)
                    logger.info("[insights] housekeeping: %s", done)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("[insights] housekeeping failed; trying again later", exc_info=True)
            await self._sleep(CHORES_EVERY_S)

    async def _people_loop(self) -> None:
        """Refreshes the top-users / different-people numbers the summary reads (see agent_insights_people). Its own loop, because a refresh of
        a big project can take seconds and must not hold up the other chores."""
        while not self._stopping.is_set():
            try:
                done = await people.refresh_due(self.session_factory)
                if done["refreshed"]:
                    logger.info("[insights] refreshed %d people views (%s ms)", done["refreshed"], sum(v["ms"] for v in done["views"]))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("[insights] refreshing the people views failed; trying again shortly", exc_info=True)
            await self._sleep(PEOPLE_EVERY_S)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    async def start(self) -> None:
        if self._tasks:
            return
        self._stopping.clear()
        self._tasks = [asyncio.create_task(self._consume_loop(), name="insights-consume"),
                       asyncio.create_task(self._chores_loop(), name="insights-chores"),
                       asyncio.create_task(self._people_loop(), name="insights-people")]
        logger.info("[insights] worker %s started", self.consumer)

    async def stop(self, timeout: float = 8.0) -> None:
        """Finish what is in hand, write the pending counts, and stop."""
        self._stopping.set()
        if self._tasks:
            _done, pending = await asyncio.wait(self._tasks, timeout=timeout)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self._tasks = []
        try:
            await ingest.DROPPED.flush(self.session_factory)
            await keys.flush_touches(self.session_factory)
        except Exception:  # noqa: BLE001
            logger.warning("[insights] could not write the last counts at shutdown", exc_info=True)
        logger.info("[insights] worker %s stopped", self.consumer)

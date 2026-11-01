"""The buffer between "an app posted events" and "the worker applied them": a Redis stream, with an in-memory twin for tests.

Why a buffer at all: the request that carries a batch must answer in a few milliseconds however busy the database is, so it
only appends the batch here and the worker writes the rollups at its own pace. Nothing is lost if the worker is down (the batch
waits here) or dies half way (a batch that was read but not acknowledged is handed to another worker after a timeout).

What lives where
* one stream entry per accepted REQUEST (not per event): the project and the normalised events, compressed when large;
* a consumer group, so several workers (the backend runs two processes) share the entries and each entry goes to one of them;
* an entry is deleted when it is acknowledged, so the stream's length IS the backlog and the ingest route can refuse new
  batches (503, the app retries) when the backlog is too big instead of filling Redis. The stream is never trimmed by length:
  trimming would throw away unread events, and the app's own outbox is the place that waits, not Redis;
* HyperLogLogs (a tiny fixed-size distinct counter) for "how many different people this hour / this minute", the one number
  that cannot be added up from counters. They expire by themselves. Adding the same person twice changes nothing, so a batch
  that is delivered twice cannot inflate them.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import time
import zlib
from typing import Any

from config import REDIS_URL

try:  # orjson is several times faster and is installed alongside langgraph; the standard library does the same job if it is not
    import orjson

    loads, dumps = orjson.loads, orjson.dumps
except ImportError:  # pragma: no cover
    import json

    loads = json.loads

    def dumps(obj: Any) -> bytes:
        return json.dumps(obj, separators=(",", ":")).encode("utf-8")

logger = logging.getLogger(__name__)

STREAM = "forge:insights:ingest"
DEAD_STREAM = "forge:insights:dead"
GROUP = "insights-workers"
#: A batch delivered this many times without being applied is set aside (and logged) instead of retried forever.
MAX_DELIVERIES = 6
#: More than this many unread requests and the ingest route answers 503. A request is at most 500 events, compressed.
MAX_BACKLOG = int(os.getenv("FORGE_INSIGHTS_MAX_BACKLOG", "4000"))
#: How long a failed Redis connection is left alone before trying again, so a Redis outage does not slow every request.
RETRY_AFTER_FAILURE_S = 5.0


def pack(project_id: str, received_at: float, events: list[dict[str, Any]]) -> bytes:
    """One stream payload. Compressed (fast, level 1) above 2 KB: event JSON shrinks about eightfold."""
    raw = dumps({"p": project_id, "r": received_at, "e": events})
    if len(raw) > 2048:
        return b"z" + zlib.compress(raw, 1)
    return b"j" + raw


def unpack(payload: bytes | str) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = payload.encode("latin-1")
    body = payload[1:]
    return loads(zlib.decompress(body) if payload[:1] == b"z" else body)


class RedisBus:
    """The real thing: a Redis stream with a consumer group, plus HyperLogLogs."""

    kind = "redis"

    def __init__(self, client) -> None:
        self.r = client
        self._group_ready = False
        self._depth_cache: tuple[float, int] = (0.0, 0)

    async def ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self.r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except Exception as e:  # noqa: BLE001 — "BUSYGROUP" means another process made it first, which is fine
            if "BUSYGROUP" not in str(e):
                raise
        self._group_ready = True

    async def publish(self, payload: bytes) -> None:
        await self.r.xadd(STREAM, {"d": payload})

    async def depth(self, max_age: float = 1.0) -> int:
        """Entries not yet acknowledged. The ingest route asks on every request, so the answer is reused for ``max_age`` seconds."""
        now = time.monotonic()
        if now - self._depth_cache[0] < max_age:
            return self._depth_cache[1]
        n = int(await self.r.xlen(STREAM))
        self._depth_cache = (now, n)
        return n

    async def read(self, consumer: str, count: int, block_ms: int) -> list[tuple[str, bytes]]:
        await self.ensure_group()
        res = await self.r.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=count, block=block_ms)
        out: list[tuple[str, bytes]] = []
        for _stream, entries in res or []:
            for entry_id, fields in entries:
                out.append((_s(entry_id), _field(fields)))
        return out

    async def claim_stale(self, consumer: str, min_idle_ms: int, count: int) -> list[tuple[str, bytes, int]]:
        """Entries another worker read but never acknowledged for ``min_idle_ms``: now this worker's. Returns (id, payload, times delivered)."""
        await self.ensure_group()
        cursor = "0-0"
        out: list[tuple[str, bytes, int]] = []
        for _ in range(20):
            res = await self.r.xautoclaim(STREAM, GROUP, consumer, min_idle_ms, start_id=cursor, count=count)
            cursor = _s(res[0])
            entries = res[1]
            if entries:
                first, last = _s(entries[0][0]), _s(entries[-1][0])
                pend = await self.r.xpending_range(STREAM, GROUP, first, last, len(entries))
                delivered = {_s(p["message_id"]): int(p["times_delivered"]) for p in pend}
                for entry_id, fields in entries:
                    if fields:  # a deleted entry still being tracked comes back empty: nothing to apply
                        out.append((_s(entry_id), _field(fields), delivered.get(_s(entry_id), 1)))
                    else:
                        await self.r.xack(STREAM, GROUP, entry_id)
            if cursor == "0-0" or len(out) >= count:
                break
        return out

    async def ack(self, ids: list[str]) -> None:
        if ids:
            await self.r.xack(STREAM, GROUP, *ids)
            await self.r.xdel(STREAM, *ids)

    async def dead_letter(self, entry_id: str, payload: bytes) -> None:
        await self.r.xadd(DEAD_STREAM, {"d": payload, "from": entry_id}, maxlen=1000, approximate=True)
        await self.ack([entry_id])

    async def hll_add(self, adds: list[tuple[str, int, list[str]]]) -> None:
        """(key, seconds to live, members): one round trip for the lot."""
        if not adds:
            return
        pipe = self.r.pipeline(transaction=False)
        for key, ttl, members in adds:
            pipe.pfadd(key, *members)
            pipe.expire(key, ttl)
        await pipe.execute()

    async def hll_counts(self, groups: list[list[str]]) -> list[int]:
        """For each group of keys, how many different members across them all (PFCOUNT merges on the fly)."""
        if not groups:
            return []
        pipe = self.r.pipeline(transaction=False)
        for keys in groups:
            pipe.pfcount(*keys) if keys else pipe.echo("0")
        return [int(x) for x in await pipe.execute()]

    async def close(self) -> None:
        try:
            await self.r.aclose()
        except Exception:  # noqa: BLE001
            pass


class MemoryBus:
    """The same behaviour in one process's memory, for tests and for load tests where no Redis is installed. It keeps the contract
    that matters: an entry read but not acknowledged is redelivered once it has been idle long enough, and acknowledging removes it."""

    kind = "memory"

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.entries: dict[str, bytes] = {}                 # entry id -> payload (the whole stream, acknowledged ones removed)
        self.order: list[str] = []                          # ids not yet delivered to anyone
        self.pending: dict[str, dict[str, Any]] = {}        # id -> {"consumer", "at", "n"} delivered and not acknowledged
        self.dead: list[tuple[str, bytes]] = []
        self.hlls: dict[str, set[str]] = {}
        self.fail_publish = False                           # a test flips this to behave like a dead Redis
        self._cv = asyncio.Condition()

    async def ensure_group(self) -> None:
        return

    async def publish(self, payload: bytes) -> None:
        if self.fail_publish:
            raise ConnectionError("memory bus told to fail")
        entry_id = f"{next(self._ids):012d}-0"
        self.entries[entry_id] = payload
        self.order.append(entry_id)
        async with self._cv:
            self._cv.notify_all()

    async def depth(self, max_age: float = 1.0) -> int:
        return len(self.entries)

    async def read(self, consumer: str, count: int, block_ms: int) -> list[tuple[str, bytes]]:
        if not self.order and block_ms:
            try:
                async with self._cv:
                    await asyncio.wait_for(self._cv.wait_for(lambda: bool(self.order)), block_ms / 1000)
            except asyncio.TimeoutError:
                return []
        out = []
        while self.order and len(out) < count:
            entry_id = self.order.pop(0)
            self.pending[entry_id] = {"consumer": consumer, "at": time.monotonic(), "n": 1}
            out.append((entry_id, self.entries[entry_id]))
        return out

    async def claim_stale(self, consumer: str, min_idle_ms: int, count: int) -> list[tuple[str, bytes, int]]:
        now = time.monotonic()
        out = []
        for entry_id, meta in sorted(self.pending.items()):
            if len(out) >= count:
                break
            if (now - meta["at"]) * 1000 >= min_idle_ms:
                meta.update(consumer=consumer, at=now, n=meta["n"] + 1)
                out.append((entry_id, self.entries[entry_id], meta["n"]))
        return out

    async def ack(self, ids: list[str]) -> None:
        for entry_id in ids:
            self.pending.pop(entry_id, None)
            self.entries.pop(entry_id, None)
            if entry_id in self.order:
                self.order.remove(entry_id)

    async def dead_letter(self, entry_id: str, payload: bytes) -> None:
        self.dead.append((entry_id, payload))
        await self.ack([entry_id])

    async def hll_add(self, adds: list[tuple[str, int, list[str]]]) -> None:
        for key, _ttl, members in adds:
            self.hlls.setdefault(key, set()).update(members)

    async def hll_counts(self, groups: list[list[str]]) -> list[int]:
        return [len(set().union(*(self.hlls.get(k, set()) for k in keys))) if keys else 0 for keys in groups]

    async def close(self) -> None:
        return


def _s(v: Any) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


def _field(fields: Any) -> bytes:
    """The payload field of a stream entry, whether the client hands back bytes or text."""
    for k, v in fields.items():
        if _s(k) == "d":
            return v if isinstance(v, bytes) else str(v).encode("latin-1")
    return b""


# ---------------------------------------------------------------------------
# which bus this process uses
# ---------------------------------------------------------------------------

_UNSET: Any = object()
_override: Any = _UNSET            # tests and the load test choose a bus (or None = "Redis is down") for the whole process
_bus: Any = None
_failed_at = 0.0


def use_bus(bus: Any) -> None:
    """Pin the bus for this process: a MemoryBus, a RedisBus, or None to behave as if Redis were unavailable (applies straight to the database)."""
    global _override
    _override = bus


def reset_bus() -> None:
    global _override, _bus, _failed_at
    _override, _bus, _failed_at = _UNSET, None, 0.0


async def get_bus() -> Any:
    """The bus to use right now, or None when there is no Redis (the caller then applies events to the database directly)."""
    global _bus, _failed_at
    if _override is not _UNSET:
        return _override
    if _bus is not None:
        return _bus
    if os.getenv("FORGE_INSIGHTS_BUS", "").lower() in ("off", "none", "0"):
        return None
    if time.monotonic() - _failed_at < RETRY_AFTER_FAILURE_S:
        return None
    try:
        import redis.asyncio as aioredis

        # Bytes in, bytes out (cache.py's client decodes text, which would mangle compressed payloads).
        client = aioredis.from_url(REDIS_URL, decode_responses=False, socket_connect_timeout=1.5, socket_timeout=10)
        await client.ping()
        _bus = RedisBus(client)
        logger.info("[insights] event buffer: Redis stream at %s", REDIS_URL)
        return _bus
    except Exception as e:  # noqa: BLE001
        _failed_at = time.monotonic()
        logger.warning("[insights] Redis not available (%s): events are applied straight to the database", e)
        return None


async def drop_bus() -> None:
    """Forget the connection after an error, so the next call reconnects (or falls back)."""
    global _bus, _failed_at
    old, _bus, _failed_at = _bus, None, time.monotonic()
    if old is not None:
        await old.close()

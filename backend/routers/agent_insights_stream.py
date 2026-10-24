"""Agent insights, push and rollup: the route an app posts its events to, and the builder's routes for the key and the summary.

* ``POST /api/insights/ingest``                                  public, server to server, signed with the project's key (no cookies, no CORS)
* ``GET|POST|DELETE /api/projects/{id}/agent-definitions/insights/key``   the builder's key
* ``GET /api/projects/{id}/agent-definitions/insights/summary``  the Insights page's numbers, from rollups only

The ingest route does as little as possible so it answers in milliseconds: check the key (a dictionary lookup), the rate limit, the
size, check each event, append the batch to the Redis stream, answer 202. The worker (services/agent_insights_worker.py) writes the
counters. With no Redis the route applies the batch to the database itself, in the same request, with the same idempotent writer.
The key/summary router is registered BEFORE the agent-definitions router in main.py, as the contract asks, though its two-segment
paths could not be read as an agent id anyway.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import async_session, get_db
from models.auth import PlatformUser
from services import agent_insights_bus as bus_mod
from services import agent_insights_ingest as ingest
from services import agent_insights_keys as keys
from services import agent_insights_store as store
from services import agent_insights_summary as summary
from services.features import feature_gate
from services.project_service import get_project_with_auth

logger = logging.getLogger(__name__)

# Public, outside the builder's sign-in: the app proves itself with its key.
ingest_router = APIRouter(tags=["agent-insights-ingest"])
# The builder's side: signed in, project access, and the Agents feature on, like the other agent-definitions routes.
router = APIRouter(tags=["agent-insights"], dependencies=[Depends(feature_gate("agents"))])

_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:]+\](:\d{1,5})?$")


def _error(status: int, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers=headers)


async def _read_body(request: Request) -> bytes:
    """The request body, refused as soon as it passes the limit (not read to the end first)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > ingest.MAX_BODY_BYTES:
        raise ingest.IngestError(413, "The request is bigger than 1 MB. Send smaller batches (at most 500 events).")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > ingest.MAX_BODY_BYTES:
            raise ingest.IngestError(413, "The request is bigger than 1 MB. Send smaller batches (at most 500 events).")
        chunks.append(chunk)
    return b"".join(chunks)


async def _deliver(ident: keys.KeyIdentity, events: list[dict[str, Any]]) -> int:
    """Hand the events on: to the stream, or (no Redis) straight into the rollups. Returns how many turns were already known (direct path only)."""
    bus = await bus_mod.get_bus()
    if bus is not None:
        try:
            if await bus.depth() >= bus_mod.MAX_BACKLOG:
                raise ingest.IngestError(503, "The platform is catching up on earlier events. Keep these and retry in a few seconds.", {"Retry-After": "5"})
            await bus.publish(bus_mod.pack(str(ident.project_id), time.time(), events))
            return 0
        except ingest.IngestError:
            raise
        except Exception as e:  # noqa: BLE001
            if "OOM" in str(e):
                # Redis is full: slow the app down rather than pile the work onto the database
                raise ingest.IngestError(503, "The platform's event buffer is full. Keep these and retry in a few seconds.", {"Retry-After": "5"}) from e
            logger.warning("[insights] the stream refused a batch (%s): applying it to the database directly", e)
            await bus_mod.drop_bus()
    try:
        async with async_session() as s, s.begin():
            res = await store.apply_events(s, ident.project_id, events)
        return res.duplicate_turns
    except Exception:  # noqa: BLE001
        logger.exception("[insights] could not apply a batch directly")
        raise ingest.IngestError(503, "The platform could not save events right now. Keep these and retry in a few seconds.", {"Retry-After": "5"}) from None


@ingest_router.post("/api/insights/ingest", status_code=202)
async def ingest_events(request: Request):
    """Take a batch of an app's events: ``{"schema": 1, "events": [...]}``, key in ``Authorization: Bearer fik_...``."""
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    ident = await keys.authenticate(token)
    if ident is None:
        return _error(401, "The key is missing, wrong or revoked. Send it as 'Authorization: Bearer fik_...' (make a new one on the Insights page).")
    ok, wait = ingest.RATE_LIMITER.allow(ident.key_hash)
    if not ok:
        ingest.DROPPED.add(ident.project_id, rate_limited=1)
        return _error(429, "Too many requests for this key. Slow down and retry.", {"Retry-After": str(max(1, int(wait + 0.999)))})
    try:
        parsed = ingest.parse_body(ingest.decode_body(await _read_body(request), request.headers.get("content-encoding")))
        if parsed.rejected_count:
            ingest.DROPPED.add(ident.project_id, rejected=parsed.rejected_count)
        known = await _deliver(ident, parsed.events) if parsed.events else 0
    except ingest.IngestError as e:
        return _error(e.status, e.message, e.headers)
    keys.touch(ident.key_id)
    return JSONResponse({
        "accepted": len(parsed.events) - known, "duplicates": parsed.duplicates + known,
        "rejected": parsed.rejected, "rejectedCount": parsed.rejected_count,
        "serverTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }, status_code=202)


# ---------------------------------------------------------------------------
# the builder's side
# ---------------------------------------------------------------------------

def _ingest_url(request: Request) -> str:
    """This platform's own address as the builder reached it (behind a proxy, the forwarded scheme and host)."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip().lower()
    if proto not in ("http", "https"):
        proto = request.url.scheme
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    if not _HOST.match(host):
        host = request.url.netloc
    return f"{proto}://{host}/api/insights/ingest"


@router.get("/api/projects/{project_id}/agent-definitions/insights/key")
async def get_insights_key(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Whether the app has a key, its first 8 characters, when it was made and last used. Never the key."""
    await get_project_with_auth(project_id, user, db)
    await keys.flush_touches()  # so "last used" is not behind by the batching interval on the page that was just opened
    return await keys.describe(db, project_id)


@router.post("/api/projects/{project_id}/agent-definitions/insights/key")
async def make_insights_key(project_id: uuid.UUID, request: Request, user: PlatformUser = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """Make the key, or rotate it (the old one stops working at once). The full key is in this answer and nowhere else, ever."""
    await get_project_with_auth(project_id, user, db)
    key, prefix = await keys.create_or_rotate(db, project_id, getattr(user, "id", None))
    return JSONResponse({"key": key, "prefix": prefix, "ingestUrl": _ingest_url(request)}, headers={"Cache-Control": "no-store"})


@router.delete("/api/projects/{project_id}/agent-definitions/insights/key")
async def remove_insights_key(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_project_with_auth(project_id, user, db)
    await keys.remove(db, project_id)
    return {"removed": True}


#: A summary is reused for a few seconds, so ten people watching one page cost one set of queries. Short for the live views, a little
#: longer for the wide ones. `FORGE_INSIGHTS_SUMMARY_CACHE_S=0` turns it off (tests).
_SUMMARY_CACHE: dict[tuple, tuple[float, dict]] = {}


def _cache_seconds(range_: str) -> float:
    raw = os.getenv("FORGE_INSIGHTS_SUMMARY_CACHE_S")
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return 2.0 if range_ in ("1h", "24h") else 10.0


@router.get("/api/projects/{project_id}/agent-definitions/insights/summary")
async def get_insights_summary(
    project_id: uuid.UUID,
    range: str = Query("24h", pattern="^(1h|24h|7d|30d|90d)$"),
    agent_id: str = Query("", max_length=100),
    role: str = Query("", max_length=60),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The page's numbers for the range, from the platform's rollups (never from the app). `{ok: true, insights}` or `{ok: false, reason}`."""
    await get_project_with_auth(project_id, user, db)
    ttl = _cache_seconds(range)
    key = (str(project_id), range, agent_id, role)
    hit = _SUMMARY_CACHE.get(key)
    if ttl and hit and hit[0] > time.monotonic():
        return hit[1]
    out = await summary.build_summary(db, project_id, range_=range, agent_id=agent_id or None, role=role or None,
                                      use_cache=os.getenv("FORGE_INSIGHTS_PEOPLE_CACHE", "1").strip().lower() not in ("0", "off", "false"))
    if ttl:
        if len(_SUMMARY_CACHE) > 500:
            _SUMMARY_CACHE.clear()
        _SUMMARY_CACHE[key] = (time.monotonic() + ttl, out)
    return out

"""The super admin watches one person's activity, live. Admin-only, and the
watching is on the record. The stream carries actions and masked data only
(`services.live_activity`); it stores nothing.

EventSource cannot send an Authorization header, so this one route takes the
access token as a query parameter and checks it here: a super admin, not
disabled, and not themselves acting as someone (the cockpit is shut under an
impersonation, and so is this).
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import decode_token
from database import async_session, get_db
from models.auth import PlatformUser
from platform_admin import require_super_admin
from services import live_activity
from services.audit_service import audit_log

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _super_admin_from_query_token(token: str, db: AsyncSession) -> PlatformUser:
    try:
        payload = decode_token(token, expected_type="access")
    except HTTPException:
        raise HTTPException(status_code=401, detail="Not signed in")
    if payload.get("act"):
        raise HTTPException(status_code=403, detail="Live activity is unavailable while impersonating")
    sub = payload.get("sub")
    user = (await db.execute(select(PlatformUser).where(PlatformUser.id == uuid.UUID(str(sub))))).scalar_one_or_none()
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="Not signed in")
    if user.platform_role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin role required")
    return user


@router.get("/live/available")
async def live_available(admin: PlatformUser = Depends(require_super_admin)) -> dict:
    """Whether live activity can run here — it needs Redis."""
    return {"available": await live_activity.available()}


@router.get("/live/{user_id}")
async def watch(user_id: uuid.UUID, request: Request, access_token: str = Query(...),
                db: AsyncSession = Depends(get_db)) -> EventSourceResponse:
    """Stream, as it happens, what the person is doing across the platform —
    the action and which record, never their private values."""
    admin = await _super_admin_from_query_token(access_token, db)
    uid, watcher = str(user_id), str(admin.id)
    target = (await db.execute(select(PlatformUser).where(PlatformUser.id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="No such person")

    async def _record(action: str) -> None:
        try:
            async with async_session() as rec:
                await audit_log(rec, target.id, action, "person", uid,
                                ip_address=getattr(request.client, "host", None),
                                user_agent=(request.headers.get("user-agent") or "")[:500] or None,
                                actor_user_id=admin.id)
                await rec.commit()
        except Exception:  # noqa: BLE001 — the record must never fail the stream
            logger.warning("[live-activity] could not record the watch", exc_info=True)

    async def _gen():
        on = await live_activity.start_watch(uid, watcher)
        await _record("live_activity.start")
        yield {"event": "ready", "data": json.dumps({"available": on, "user_id": uid})}
        pings = 0
        try:
            async for event in live_activity.stream(uid):
                name = event.pop("type", "activity")
                if name == "ping":
                    pings += 1
                    if pings % 2 == 0:  # ~every 50s, keep the watch alive
                        await live_activity.refresh_watch(uid)
                    yield {"event": "ping", "data": "{}"}
                else:
                    yield {"event": "activity", "data": json.dumps(event, default=str)}
        finally:
            await live_activity.stop_watch(uid, watcher)
            await _record("live_activity.stop")

    return EventSourceResponse(_gen())

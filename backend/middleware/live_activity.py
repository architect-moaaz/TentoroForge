"""Emit what a watched person is doing, as they do it.

After each request this reads the bearer to learn who it was served as, and
— only when a super admin is watching that person — publishes one masked
activity event. The hot path is a set test in memory: a request for someone
nobody is watching costs a token decode and nothing more. The person is
never told by this; whether people are told that administrators can watch
is the platform's policy to state, not this middleware's to decide.
"""
from __future__ import annotations

import logging
import uuid

from jose import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config import JWT_ALGORITHM, SECRET_KEY
from middleware.impersonation_audit import org_of

logger = logging.getLogger(__name__)


def _identify(request: Request) -> tuple[str, str | None] | None:
    """(person, admin-behind-them | None) from the bearer, without the
    database. None when there is no readable access token."""
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(header[7:], SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except Exception:  # noqa: BLE001
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    act = payload.get("act")
    return str(sub), (str(act) if act else None)


class LiveActivityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from services import live_activity

        await live_activity.ensure_listener()
        who = _identify(request)
        response = await call_next(request)
        if who is not None and live_activity.worth_streaming(request.url.path) and live_activity.is_watched(who[0]):
            person, by = who
            org = org_of(request)
            try:
                await live_activity.emit(live_activity.build_event(
                    user=person, method=request.method, path=request.url.path,
                    status=response.status_code, org=str(org) if org else None, by=by))
            except Exception:  # noqa: BLE001 — watching never affects the request
                logger.debug("[live-activity] emit failed", exc_info=True)
        return response

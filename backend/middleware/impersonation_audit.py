"""Every write made under an impersonation token is on the record.

A super admin acting as a person carries a token whose `act` names the admin
(`auth.create_impersonation_token`). Routes see the person; this sees the
token, and after a mutating request writes one audit row — the person as
`user_id`, the admin as `actor_user_id`, the request as the resource — in a
session of its own, so a route that writes nothing still leaves the mark, and
a route that fails still shows the attempt. Reads are not recorded: the
start of the impersonation already is (`impersonation.start`).
"""
from __future__ import annotations

import logging
import re
import uuid

from jose import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config import JWT_ALGORITHM, SECRET_KEY

logger = logging.getLogger(__name__)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

_ORG_IN_PATH = re.compile(r"^/api/orgs/([0-9a-fA-F-]{36})(?:/|$)")


def org_of(request: Request) -> uuid.UUID | None:
    """The organisation the request concerned: what the route's membership
    check left on the request, else the one its path names."""
    found = getattr(request.state, "org_id", None)
    if found:
        return found
    m = _ORG_IN_PATH.match(request.url.path)
    if m:
        try:
            return uuid.UUID(m.group(1))
        except ValueError:
            return None
    return None


def impersonation_of(request: Request) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(actor, person) when the bearer is an impersonation token; else None.
    Decoded without the database — the route's own check does the rest."""
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(header[7:], SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except Exception:  # noqa: BLE001 — an unreadable token is the route's to refuse
        return None
    act, sub = payload.get("act"), payload.get("sub")
    if not act or not sub:
        return None
    try:
        return uuid.UUID(str(act)), uuid.UUID(str(sub))
    except ValueError:
        return None


class ImpersonationAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        who = impersonation_of(request) if request.method in MUTATING else None
        response = await call_next(request)
        if who is not None:
            actor, person = who
            try:
                from database import async_session
                from services.audit_service import audit_log
                async with async_session() as db:
                    await audit_log(
                        db, person, "impersonated_request", "http",
                        f"{request.method} {request.url.path}",
                        changes={"status": response.status_code},
                        ip_address=getattr(request.client, "host", None),
                        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
                        request_id=getattr(request.state, "request_id", None),
                        actor_user_id=actor,
                        org_id=org_of(request),
                    )
                    await db.commit()
            except Exception:  # noqa: BLE001 — the record must never fail the request
                logger.warning("[impersonation] the request could not be recorded", exc_info=True)
        return response

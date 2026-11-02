"""Who may reach a project's routes — as a dependency, so a route cannot forget.

Several project routes took a project id and nothing else: any signed-in
person could start a verify run on another organisation's app (spending its
credit, letting Smith edit its code), and the event streams and the crash
inbox needed no sign-in at all (audit, 2026-11-01). Three doors now:

- `member_project` — a signed-in member of the project's organisation, the
  same check every other project route makes (`get_project_with_auth`).
- `stream_ticket` / `ticket_project` — an EventSource cannot send a header,
  so a member asks for a ticket first and opens the stream with it. The
  ticket names one person and one project, opens only streams, and lasts a
  working day; it is not an access token, so a URL that leaks one in a log
  leaks no session.
- `app_report` — what a generated app posts about itself carries the key
  only that app was given (`services.app_reporting.report_key`).
"""
from __future__ import annotations

import time
import uuid

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import Project

_TICKET_TYPE = "project_stream"
TICKET_TTL_S = 12 * 3600


async def member_project(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Project:
    from services.project_service import get_project_with_auth

    return await get_project_with_auth(project_id, user, db)


def stream_ticket(user_id: uuid.UUID, project_id: uuid.UUID) -> str:
    import jwt

    from config import JWT_ALGORITHM, SECRET_KEY

    now = int(time.time())
    return jwt.encode({"type": _TICKET_TYPE, "sub": str(user_id), "pid": str(project_id),
                       "iat": now, "exp": now + TICKET_TTL_S}, SECRET_KEY, algorithm=JWT_ALGORITHM)


async def ticket_project(
    project_id: uuid.UUID,
    ticket: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """The project a stream ticket opens, for a person who is still a member."""
    import jwt

    from config import JWT_ALGORITHM, SECRET_KEY
    from services.project_service import get_project_with_auth

    try:
        claims = jwt.decode(ticket, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="This stream needs a current ticket")
    if claims.get("type") != _TICKET_TYPE or claims.get("pid") != str(project_id):
        raise HTTPException(status_code=401, detail="This stream needs a current ticket")
    user = await db.get(PlatformUser, uuid.UUID(str(claims.get("sub"))))
    if user is None or getattr(user, "disabled_at", None) is not None:
        raise HTTPException(status_code=401, detail="This stream needs a current ticket")
    return await get_project_with_auth(project_id, user, db)


async def app_report(
    project_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Project:
    """The project a report is about, when the report is from its own app."""
    from services.app_reporting import KEY_HEADER, is_the_apps

    if not is_the_apps(project_id, request.headers.get(KEY_HEADER)):
        raise HTTPException(status_code=403, detail="Not this project's app")
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


__all__ = ["member_project", "stream_ticket", "ticket_project", "app_report", "TICKET_TTL_S"]

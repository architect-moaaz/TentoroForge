"""The super admin: who runs the platform, and how the role is held.

One role, `platform_role = "super_admin"`, on a platform login. The emails the
platform's configuration names (`FORGE_SUPER_ADMIN_EMAILS`, by default
`admin@tentoro.ai`) are given it the moment that account signs up or signs
in — so the account is made the ordinary way, and nobody types a password
into a seed. From the cockpit a super admin may grant or revoke the role to
others, never to themselves: the last one can not lock everyone out.

The cockpit is read through `/api/admin/*` (`require_super_admin`); acting
inside an organisation or an app is done by impersonating one of its people
(`auth.create_impersonation_token`), which every organisation route treats
as that person — no route is bypassed.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import SUPER_ADMIN, PlatformUser

logger = logging.getLogger(__name__)

SUPER_ADMIN_EMAILS_ENV = "FORGE_SUPER_ADMIN_EMAILS"
DEFAULT_SUPER_ADMIN_EMAIL = "admin@tentoro.ai"


def super_admin_emails() -> set[str]:
    """The emails made super admin at sign-in. Read at call time, so a test
    sets the environment and a running platform picks up a change on restart."""
    raw = os.environ.get(SUPER_ADMIN_EMAILS_ENV)
    if raw is None:
        raw = DEFAULT_SUPER_ADMIN_EMAIL
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_super_admin(user: PlatformUser | None) -> bool:
    return bool(user is not None and user.platform_role == SUPER_ADMIN)


async def record_sign_in(user: PlatformUser, db: AsyncSession) -> None:
    """A sign-in: the time is kept, and a listed email takes the role.
    Commits — every caller is about to answer with tokens."""
    user.last_sign_in_at = datetime.now(timezone.utc)
    # An invitation naming this email is taken up here, so a person who
    # signed up because they were invited lands in their organisation.
    from services.invites import claim_pending_invites
    await claim_pending_invites(user, db)
    if user.platform_role is None and user.email.lower() in super_admin_emails():
        from services.audit_service import audit_log
        user.platform_role = SUPER_ADMIN
        await audit_log(db, user.id, "super_admin.bootstrap", "platform_user", str(user.id),
                        changes={"email": user.email}, actor_user_id=user.id)
        logger.info("[super-admin] %s took the role at sign-in", user.email)
    await db.commit()


async def require_super_admin(
    request: Request,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformUser:
    """403 unless the signed-in person holds the role in their own right:
    the cockpit is never reached under an impersonation token."""
    if getattr(request.state, "impersonated_by", None):
        raise HTTPException(status_code=403, detail="Cockpit unavailable while impersonating")
    if not is_super_admin(user):
        raise HTTPException(status_code=403, detail="Super admin role required")
    return user


__all__ = ["SUPER_ADMIN_EMAILS_ENV", "DEFAULT_SUPER_ADMIN_EMAIL", "super_admin_emails",
           "is_super_admin", "record_sign_in", "require_super_admin"]

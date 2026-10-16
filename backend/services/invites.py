"""Invitations into an organisation.

An invite is a pending `OrgMember` row that names an email. Somebody with an
account already joins the moment they are invited; somebody without one joins
at the sign-in that follows their sign-up with that email — nobody has to find
an accept button. The invite email carries the sign-up address of this
platform; when no mail provider is set up, the address is handed back to the
inviter to pass on.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.auth import PlatformUser
from models.org import InviteStatus, OrgMember

logger = logging.getLogger(__name__)

#: The address people reach Forge at, when the request does not say.
PUBLIC_URL_ENV = "FORGE_PUBLIC_URL"


async def claim_pending_invites(user: PlatformUser, db: AsyncSession) -> int:
    """Every pending invite naming this account's email becomes a membership.
    Does not commit: the caller is recording a sign-in and commits after."""
    rows = (await db.execute(select(OrgMember).where(
        OrgMember.invite_status == InviteStatus.pending,
        func.lower(OrgMember.invite_email) == user.email.lower(),
        (OrgMember.user_id.is_(None)) | (OrgMember.user_id == user.id),
    ))).scalars().all()
    for row in rows:
        row.user_id = user.id
        row.invite_status = InviteStatus.accepted
        row.joined_at = datetime.now(timezone.utc)
    if rows:
        logger.info("[invites] %s took up %d invitation(s) at sign-in", user.email, len(rows))
    return len(rows)


def platform_base(headers) -> str:
    """Where the invitee should sign up: the frontend that made the request
    (its Origin), else the configured public address, else nothing."""
    origin = str(headers.get("origin") or "").strip().rstrip("/")
    if origin.startswith("http"):
        return origin
    return str(os.environ.get(PUBLIC_URL_ENV) or "").strip().rstrip("/")


def signup_url(base: str, email: str) -> str:
    return f"{base}/signup?email={quote(email)}" if base else ""


async def send_invite_email(*, to: str, org_name: str, inviter: str, role: str, url: str) -> bool:
    """True when the platform's mail service took the message."""
    try:
        from services.email_service import send_email
        return bool(await send_email(to, "org_invite",
                                     {"org_name": org_name, "inviter": inviter, "role": role, "signup_url": url}))
    except Exception:  # noqa: BLE001 — the address is handed back either way
        logger.warning("[invites] the invitation email could not be sent", exc_info=True)
        return False

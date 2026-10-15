"""Who may act in an organisation — one answer for every route.

Each router used to carry its own copy of the membership check, so the day an
organisation could be blocked there were seven places to teach it. There is
one now. The order is the point: an organisation that was removed answers 404
to everyone; a person who is not a member is refused before the status is
looked at, so an outsider learns nothing from a block; a member of a blocked
organisation is told so.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.auth import PlatformUser
from models.org import InviteStatus, Organization, OrgMember, OrgMemberRole

ROLE_RANK = {OrgMemberRole.owner: 3, OrgMemberRole.admin: 2, OrgMemberRole.member: 1}

BLOCKED_MESSAGE = "Organisation is blocked"


async def require_org_member(
    org_id: uuid.UUID,
    user: PlatformUser,
    db: AsyncSession,
    min_role: OrgMemberRole = OrgMemberRole.member,
    request: Request | None = None,
) -> OrgMember:
    """The caller's membership of `org_id`, with at least `min_role`.
    404 for an organisation that is not there or was removed; 403 for a
    non-member, a role below the bar, or a blocked organisation."""
    org = await db.get(Organization, org_id)
    if org is None or org.is_removed:
        raise HTTPException(status_code=404, detail="Organization not found")

    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    if ROLE_RANK.get(membership.role, 0) < ROLE_RANK.get(min_role, 0):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if org.is_blocked:
        raise HTTPException(status_code=403, detail=BLOCKED_MESSAGE)

    if request is not None:
        request.state.org_id = org_id
    return membership


async def require_any_org_admin(user: PlatformUser, db: AsyncSession) -> None:
    """403 unless the person is owner or admin of at least one active organisation."""
    result = await db.execute(
        select(OrgMember).join(Organization, Organization.id == OrgMember.org_id).where(
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
            OrgMember.role.in_([OrgMemberRole.owner, OrgMemberRole.admin]),
            Organization.status == "active",
        ).limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Admin role required")


async def org_is_usable(org_id: uuid.UUID, db: AsyncSession) -> bool:
    """Whether work may start for an organisation at all: it exists and is active."""
    org = await db.get(Organization, org_id)
    return org is not None and org.status == "active"


__all__ = ["ROLE_RANK", "BLOCKED_MESSAGE", "require_org_member", "require_any_org_admin", "org_is_usable"]

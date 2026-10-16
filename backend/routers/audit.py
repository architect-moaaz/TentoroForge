"""Audit log endpoints — query audit trail with filters."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.audit import AuditLog
from models.org import InviteStatus, OrgMember, OrgMemberRole
from schemas.audit import AuditLogResponse

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    user_id: uuid.UUID | None = Query(None),
    actor_user_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    resource_id: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query audit log with filters. A super admin reads everything; anyone
    else reads the rows about themselves and the rows of the organisations
    they own or administer — which is how an organisation's admins see that
    one of their people was impersonated, and what was done."""
    from platform_admin import is_super_admin
    q = select(AuditLog).order_by(AuditLog.timestamp.desc())

    if not is_super_admin(current_user):
        admin_of = await db.execute(
            select(OrgMember.org_id).where(
                OrgMember.user_id == current_user.id,
                OrgMember.invite_status == InviteStatus.accepted,
                OrgMember.role.in_([OrgMemberRole.owner, OrgMemberRole.admin]),
            )
        )
        mine = [row[0] for row in admin_of.all()]
        q = q.where(or_(AuditLog.user_id == current_user.id,
                        AuditLog.actor_user_id == current_user.id,
                        AuditLog.org_id.in_(mine) if mine else false()))

    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if actor_user_id:
        q = q.where(AuditLog.actor_user_id == actor_user_id)
    if org_id:
        q = q.where(AuditLog.org_id == org_id)
    if action:
        q = q.where(AuditLog.action == action)
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    if resource_id:
        q = q.where(AuditLog.resource_id == resource_id)
    if since:
        q = q.where(AuditLog.timestamp >= since)
    if until:
        q = q.where(AuditLog.timestamp <= until)

    q = q.limit(limit).offset(offset)

    result = await db.execute(q)
    return result.scalars().all()

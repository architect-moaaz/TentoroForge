"""Admin usage analytics — tokens + cost per app build.

Reads the build-usage ledger (services/build_usage.py, populated by the
generation pipeline's SSE stream hook) and serves the aggregates the
/admin/usage dashboard renders. Admin-only: the caller must hold an
owner/admin role in at least one org — build cost is platform-operator
data, not end-user data.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import InviteStatus, OrgMember, OrgMemberRole

router = APIRouter(tags=["usage"])


async def _require_any_org_admin(
    user: PlatformUser, db: AsyncSession
) -> None:
    """403 unless the user is owner/admin of at least one org."""
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
            OrgMember.role.in_([OrgMemberRole.owner, OrgMemberRole.admin]),
        ).limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=403,
            detail="Admin role required to view usage analytics",
        )


@router.get("/api/usage/summary")
async def get_usage_summary(
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Platform-wide build cost + token aggregates for the admin dashboard."""
    await _require_any_org_admin(user, db)
    from services.build_usage import usage_summary
    return usage_summary()


@router.get("/api/usage/projects/{project_slug}")
async def get_project_usage(
    project_slug: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-agent breakdown for a single app build (drill-down view)."""
    await _require_any_org_admin(user, db)
    from services.build_usage import _entry_cost, read_ledger
    entries = [e for e in read_ledger() if e.get("project") == project_slug]
    return {
        "project": project_slug,
        "events": [
            {**e, "cost_usd": _entry_cost(e)} for e in entries
        ],
        "total_cost_usd": round(sum(_entry_cost(e) for e in entries), 4),
    }

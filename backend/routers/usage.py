"""Usage and spend — who may read what.

Platform-wide figures (every app's build cost, every open platform patch)
are the super admin's: they are the platform operator's data. An
organisation's spend, balance and limits are read by its owners and
admins; a person reads their own spend and their own applications'.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import InviteStatus, OrgMember, OrgMemberRole
from platform_admin import is_super_admin, require_super_admin

router = APIRouter(tags=["usage"])


async def _admin_of(user: PlatformUser, db: AsyncSession, org_id: str) -> bool:
    try:
        oid = uuid.UUID(str(org_id))
    except ValueError:
        return False
    row = (await db.execute(select(OrgMember).where(
        OrgMember.org_id == oid, OrgMember.user_id == user.id, OrgMember.invite_status == InviteStatus.accepted,
        OrgMember.role.in_([OrgMemberRole.owner, OrgMemberRole.admin])))).scalar_one_or_none()
    return row is not None


async def _scope_allowed(user: PlatformUser, db: AsyncSession, *, org: str, person: str, project: str) -> None:
    """Who may read a scope: the super admin anything; an organisation's
    admin its organisation; anyone their own spend (`person=me`) and their
    own applications'. A scope naming nothing is the platform's: super admin."""
    if is_super_admin(user):
        return
    if person == "me" or (person and person == user.email):
        return
    if project:
        from models.project import Project
        row = (await db.execute(select(Project).where(Project.short_id == project))).scalar_one_or_none()
        if row is not None and (str(row.owner_id) == str(user.id) or await _admin_of(user, db, str(row.org_id))):
            return
        raise HTTPException(status_code=403, detail="Not your application")
    if org and await _admin_of(user, db, org):
        return
    raise HTTPException(status_code=403, detail="Super admin role required")


@router.get("/api/usage/summary")
async def get_usage_summary(
    user: PlatformUser = Depends(require_super_admin),
):
    """Platform-wide build cost + token aggregates for the admin dashboard."""
    from services.build_usage import usage_summary
    return usage_summary()


@router.get("/api/usage/projects/{project_slug}")
async def get_project_usage(
    project_slug: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-agent breakdown for a single app build (drill-down view)."""
    await _scope_allowed(user, db, org="", person="", project=project_slug)
    from services.build_usage import _entry_cost, read_ledger
    entries = [e for e in read_ledger() if e.get("project") == project_slug]
    return {
        "project": project_slug,
        "events": [
            {**e, "cost_usd": _entry_cost(e)} for e in entries
        ],
        "total_cost_usd": round(sum(_entry_cost(e) for e in entries), 4),
    }


@router.get("/api/usage/platform-patches")
async def get_platform_patches(
    user: PlatformUser = Depends(require_super_admin),
):
    """Every app's open patches to the platform's own files (`file_edit`):
    what Smith changed in an app's copy of the engine, why, and on what
    proof — the list the platform folds fixes in from. Nothing here is
    hidden drift: a patch retires itself when the platform has the fix."""
    from services.project_paths import OUTPUT_ROOT
    from services.smith.file_edit import open_patches
    patches = open_patches(OUTPUT_ROOT)
    return {"count": len(patches), "patches": patches}


@router.get("/api/spend/report")
async def get_spend_report(
    period: str = "month",
    at: str | None = None,
    org: str = "",
    person: str = "",
    project: str = "",
    agent: str = "",
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What was spent in the period containing `at` (today by default), for
    a scope — the platform, an organisation, a person (`me` or an email),
    an application, one agent's calls — split by agent, application,
    person, model, phase and day (hour, for a day)."""
    from services import credits, spending
    from services.build_usage import read_ledger
    await _scope_allowed(user, db, org=org, person=person, project=project)
    if person == "me":
        person = user.email
    projects, _names = await credits.projects_known(db)
    try:
        return spending.report(read_ledger(), period=period, at=spending.parse_at(at), org=org, user=person,
                               project=project, agent=agent, projects=projects)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/spend/standing")
async def get_spend_standing(
    org: str = "",
    person: str = "",
    project: str = "",
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Where a scope stands against every limit that covers it, per period,
    and the organisation's balance when the scope names one."""
    from services import credits, spending
    from services.build_usage import read_ledger
    await _scope_allowed(user, db, org=org, person=person, project=project)
    if person == "me":
        person = user.email
    rows = read_ledger()
    policy = await credits.load_policy(db)
    projects, _names = await credits.projects_known(db)
    out = spending.standing(rows, org=org, user=person, project=project, policy=policy, projects=projects)
    out["build_estimate_usd"] = spending.estimate_build_usd(spending.attributed(rows, projects), org=org)
    return out


@router.get("/api/orgs/{org_id}/spend")
async def get_org_spend(
    org_id: uuid.UUID,
    period: str = "month",
    at: str | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """An organisation's balance, its spend in the period, and the limits
    that cover it — for its owners and admins, and the super admin."""
    from services import credits, spending
    from services.build_usage import read_ledger
    if not is_super_admin(user) and not await _admin_of(user, db, str(org_id)):
        raise HTTPException(status_code=403, detail="Admin role required")
    rows = read_ledger()
    projects, _names = await credits.projects_known(db)
    standing = await credits.org_standing(db, rows, org_id)
    try:
        report = spending.report(rows, period=period, at=spending.parse_at(at), org=str(org_id), projects=projects)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"org_id": str(org_id), "balance": standing["balance"], "limits": standing["limits"],
            "limits_set": standing["limits_set"], "platform_limits": standing["platform_limits"],
            "build_estimate_usd": standing["build_estimate_usd"], "report": report}

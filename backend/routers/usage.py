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


@router.get("/api/usage/platform-patches")
async def get_platform_patches(
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every app's open patches to the platform's own files (`file_edit`):
    what Smith changed in an app's copy of the engine, why, and on what
    proof — the list the platform folds fixes in from. Nothing here is
    hidden drift: a patch retires itself when the platform has the fix."""
    await _require_any_org_admin(user, db)
    from services.project_paths import OUTPUT_ROOT
    from services.smith.file_edit import open_patches
    patches = open_patches(OUTPUT_ROOT)
    return {"count": len(patches), "patches": patches}


# --------------------------------------------------------------------------- #
# Spend: per person, organisation and application, by period; credit and limits
# --------------------------------------------------------------------------- #

from pydantic import BaseModel, Field  # noqa: E402


async def _projects_known(db: AsyncSession) -> tuple[dict[str, dict], dict[str, str]]:
    """Every application's organisation, owner (email) and name, keyed by
    its id — what attributes a ledger row to a person and an organisation —
    and display names for scopes."""
    from models.org import Organization
    from models.project import Project
    rows = (await db.execute(select(Project.short_id, Project.name, Project.org_id, Project.owner_id))).all()
    owners = {r.owner_id for r in rows if r.owner_id is not None}
    emails: dict[str, str] = {}
    if owners:
        found = (await db.execute(select(PlatformUser.id, PlatformUser.email)
                                  .where(PlatformUser.id.in_(list(owners))))).all()
        emails = {str(u.id): u.email for u in found}
    orgs = (await db.execute(select(Organization.id, Organization.name))).all()
    projects = {str(r.short_id): {"org": str(r.org_id), "owner": emails.get(str(r.owner_id), ""), "name": r.name}
                for r in rows}
    names = {f"org:{o.id}": o.name for o in orgs}
    names.update({f"project:{k}": v["name"] for k, v in projects.items()})
    return projects, names


async def _scope_allowed(user: PlatformUser, db: AsyncSession, *, org: str, person: str, project: str) -> None:
    """Who may read a scope: an org admin reads anything; anyone reads their
    own spend (`user=me`) and their own applications'."""
    if person == "me" or person == user.email:
        return
    if project:
        from models.project import Project
        row = (await db.execute(select(Project).where(Project.short_id == project))).scalar_one_or_none()
        if row is not None and str(row.owner_id) == str(user.id):
            return
    await _require_any_org_admin(user, db)


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
    from services import spending
    from services.build_usage import read_ledger
    await _scope_allowed(user, db, org=org, person=person, project=project)
    if person == "me":
        person = user.email
    projects, _names = await _projects_known(db)
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
    """The account's balance, and where a scope stands against every limit
    that covers it, per period."""
    from services import spending
    from services.build_usage import read_ledger
    await _scope_allowed(user, db, org=org, person=person, project=project)
    if person == "me":
        person = user.email
    projects, _names = await _projects_known(db)
    out = spending.standing(read_ledger(), org=org, user=person, project=project, projects=projects)
    out["policy"] = spending.read_policy()
    out["build_estimate_usd"] = spending.estimate_build_usd(read_ledger())
    return out


class CreditIn(BaseModel):
    amount: float = Field(gt=0)
    note: str = ""


@router.post("/api/spend/credits", status_code=201)
async def post_spend_credit(
    body: CreditIn,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record money put on the account — the opening balance first, then
    every top-up — so the platform can say what is left."""
    from services import spending
    await _require_any_org_admin(user, db)
    try:
        return spending.add_credit(body.amount, note=body.note, by=user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class LimitsIn(BaseModel):
    scope: str
    day: float | None = None
    week: float | None = None
    month: float | None = None
    year: float | None = None


@router.put("/api/spend/limits")
async def put_spend_limits(
    body: LimitsIn,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Spending limits for a scope (`platform`, `org:<id>`, `user:<email>`,
    `project:<id>`) per period; a period left empty has none."""
    from services import spending
    await _require_any_org_admin(user, db)
    try:
        return {"scope": body.scope, "limits": spending.set_limits(
            body.scope, {k: v for k, v in body.model_dump().items() if k in spending.PERIODS})}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

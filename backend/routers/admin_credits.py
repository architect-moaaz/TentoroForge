"""Credits, from the cockpit: every organisation's balance, its history, the
entries that move it, and the limits that bound the platform, an
organisation, a person or an app.

An organisation with no entry is "unknown — limits only": nothing is
refused for a balance nobody recorded. The first entry is its opening
balance; after that top-ups, adjustments either way and refunds, each with
a reason on the record.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.auth import PlatformUser
from models.credits import CREDIT_KINDS
from models.org import Organization
from models.project import Project
from platform_admin import require_super_admin
from services import credits, spending
from services.audit_service import audit_request

router = APIRouter(prefix="/api/admin/credits", tags=["admin-credits"])


def _rows() -> list[dict[str, Any]]:
    from services.build_usage import read_ledger
    return read_ledger()


@router.get("/orgs")
async def org_balances(admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    rows = _rows()
    projects, _ = await credits.projects_known(db)
    return {
        "build_estimate_usd": spending.estimate_build_usd(spending.attributed(rows, projects)),
        "orgs": await credits.all_org_balances(db, rows),
    }


class EntryBody(BaseModel):
    amount_usd: float
    kind: str = Field(default="top_up")
    note: str = Field(min_length=3, max_length=2000)


async def _org_or_404(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.get("/orgs/{org_id}/entries")
async def org_entries(org_id: uuid.UUID, admin: PlatformUser = Depends(require_super_admin),
                      db: AsyncSession = Depends(get_db)):
    org = await _org_or_404(db, org_id)
    standing = await credits.org_standing(db, _rows(), org_id)
    return {"org_id": str(org_id), "name": org.name, "slug": org.slug, "balance": standing["balance"],
            "limits": standing["limits"], "build_estimate_usd": standing["build_estimate_usd"],
            "entries": await credits.entries_of(db, org_id)}


@router.post("/orgs/{org_id}/entries", status_code=201)
async def add_org_entry(org_id: uuid.UUID, body: EntryBody, request: Request,
                        admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    org = await _org_or_404(db, org_id)
    if body.kind not in CREDIT_KINDS:
        raise HTTPException(status_code=400, detail=f"kind is one of {', '.join(CREDIT_KINDS)}")
    if body.amount_usd == 0:
        raise HTTPException(status_code=422, detail="an entry is an amount, not zero")
    try:
        entry = await credits.add_entry(db, org_id, body.amount_usd, body.kind, body.note, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_request(request, db, "credit.entry", "organization", str(org_id),
                        changes={"slug": org.slug, "amount_usd": entry["amount"], "kind": body.kind, "note": body.note},
                        org_id=org_id)
    await db.commit()
    standing = await credits.org_standing(db, _rows(), org_id)
    return {**entry, "by_email": admin.email, "balance": standing["balance"]}


class LimitsBody(BaseModel):
    scope_kind: str
    scope_id: str = ""
    day: float | None = None
    week: float | None = None
    month: float | None = None
    year: float | None = None


async def _scope_exists(db: AsyncSession, scope_kind: str, scope_id: str) -> str:
    """The scope's name for the record; 404 when it names nothing."""
    if scope_kind == "platform":
        return "the platform"
    if scope_kind == "org":
        try:
            org = await db.get(Organization, uuid.UUID(scope_id))
        except ValueError:
            org = None
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return org.name
    if scope_kind == "user":
        user = (await db.execute(select(PlatformUser).where(PlatformUser.email == scope_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="Person not found")
        return user.email
    if scope_kind == "project":
        project = (await db.execute(select(Project).where(Project.short_id == scope_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.name
    raise HTTPException(status_code=400, detail=f"scope_kind is one of {', '.join(spending.SCOPE_KINDS)}")


@router.put("/limits")
async def put_limits(body: LimitsBody, request: Request,
                     admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    """Limits for one scope per period; a period left empty or zero is cleared."""
    name = await _scope_exists(db, body.scope_kind, body.scope_id)
    try:
        clean = await credits.set_limits(db, body.scope_kind, body.scope_id,
                                         {k: v for k, v in body.model_dump().items() if k in spending.PERIODS}, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    org_id = uuid.UUID(body.scope_id) if body.scope_kind == "org" else None
    await audit_request(request, db, "credit.limits", "spend_limit", f"{body.scope_kind}:{body.scope_id}",
                        changes={"scope": name, "limits": clean}, org_id=org_id)
    await db.commit()
    return {"scope_kind": body.scope_kind, "scope_id": body.scope_id if body.scope_kind != "platform" else "",
            "name": name, "limits": clean}


@router.get("/limits")
async def get_limits(admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    return await credits.all_limits(db)


@router.get("/standing")
async def platform_standing(admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    """The platform as a whole: every known balance summed, spend per period,
    the platform's own limits, and what a build is expected to cost."""
    rows = _rows()
    policy = await credits.load_policy(db)
    projects, _ = await credits.projects_known(db)
    attributed = spending.attributed(rows, projects)
    balances = await credits.all_org_balances(db, rows)
    standing = spending.standing(attributed, policy=policy, projects=projects)
    return {
        "balance_total_usd": round(sum(float(b["balance_usd"] or 0) for b in balances if b["known"]), 4),
        "orgs_known": sum(1 for b in balances if b["known"]),
        "orgs": len(balances),
        "limits": standing["limits"],
        "platform_limits": (policy.get("limits") or {}).get(spending.PLATFORM) or {},
        "build_estimate_usd": spending.estimate_build_usd(attributed),
        "spent": {period: round(sum(float(r["cost_usd"]) for r in spending.within(attributed, *spending.period_bounds(period))), 4)
                  for period in spending.PERIODS},
    }

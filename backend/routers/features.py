"""Features per organisation: what members may use, read by the organisation;
switched, per organisation or for the platform, by the super admin."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.features import FeatureSetting
from models.org import Organization
from platform_admin import require_super_admin
from services import features as F
from services.audit_service import audit_request
from services.org_access import require_org_member

router = APIRouter(tags=["features"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/api/orgs/{org_id}/features")
async def org_features(org_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Every feature as it stands for this organisation — name, group,
    whether it may be used. The reason behind a setting is the cockpit's,
    not the members'."""
    await require_org_member(org_id, user, db)
    state = await F.effective(db, org_id)
    return {"org_id": str(org_id), "features": {
        f.key: {"key": f.key, "name": f.name, "description": f.description, "group": f.group,
                "default_on": f.default_on, "source_out": f.source_out, "enforced": f.enforced,
                "enabled": state[f.key]["enabled"], "source": state[f.key]["source"]}
        for f in F.CATALOGUE}}


class SettingBody(BaseModel):
    #: True / False to set; null to clear the setting and inherit.
    enabled: bool | None = None
    reason: str = Field(..., min_length=3, max_length=500)


def _row(row: FeatureSetting | None, emails: dict[uuid.UUID, str]) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"enabled": bool(row.enabled), "reason": row.reason, "at": row.updated_at.isoformat() if row.updated_at else None,
            "by_email": emails.get(row.set_by) if row.set_by else None}


async def _emails(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(PlatformUser.id, PlatformUser.email).where(PlatformUser.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


@admin_router.get("/features")
async def list_features(admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The catalogue with the platform's setting of each feature and how
    many organisations hold a setting of their own."""
    platform = (await F.settings_for(db, None))[F.PLATFORM]
    counts = dict((await db.execute(
        select(FeatureSetting.feature_key, func.count()).where(FeatureSetting.scope_kind == F.ORG)
        .group_by(FeatureSetting.feature_key))).all())
    emails = await _emails(db, {r.set_by for r in platform.values()})
    out = []
    for f in F.CATALOGUE:
        p = platform.get(f.key)
        out.append({**F.catalogue_rows()[[x.key for x in F.CATALOGUE].index(f.key)],
                    "platform": _row(p, emails),
                    "enabled_by_default": bool(p.enabled) if p is not None else f.default_on,
                    "org_overrides": int(counts.get(f.key, 0))})
    return {"groups": list(F.GROUPS), "features": out}


@admin_router.put("/features/{key}")
async def set_platform_feature(key: str, body: SettingBody, request: Request,
                               admin: PlatformUser = Depends(require_super_admin),
                               db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The platform's default for a feature: what every organisation without
    a setting of its own gets. Null clears it back to the catalogue."""
    feature = F.feature_or_404(key)
    before = (await F.settings_for(db, None))[F.PLATFORM].get(key)
    row = await F.set_feature(db, scope_kind=F.PLATFORM, scope_id="", key=key, enabled=body.enabled,
                              reason=body.reason, by=admin)
    await audit_request(request, db, "feature.platform", "feature", key, {
        "enabled": body.enabled, "was": bool(before.enabled) if before is not None else None,
        "default": feature.default_on, "reason": body.reason})
    await db.commit()
    emails = await _emails(db, {row.set_by} if row else set())
    return {"key": key, "platform": _row(row, emails),
            "enabled_by_default": bool(row.enabled) if row is not None else feature.default_on}


async def _org_or_404(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    from fastapi import HTTPException
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


async def _org_view(db: AsyncSession, org: Organization) -> dict[str, Any]:
    rows = await F.settings_for(db, org.id)
    emails = await _emails(db, {r.set_by for r in rows[F.ORG].values()} | {r.set_by for r in rows[F.PLATFORM].values()})
    out = []
    for f in F.CATALOGUE:
        p, o = rows[F.PLATFORM].get(f.key), rows[F.ORG].get(f.key)
        state = F.resolve(f, p, o)
        out.append({"key": f.key, "name": f.name, "description": f.description, "group": f.group,
                    "default_on": f.default_on, "source_out": f.source_out, "enforced": f.enforced,
                    "platform": _row(p, emails), "override": _row(o, emails),
                    "enabled": state["enabled"], "source": state["source"]})
    return {"org_id": str(org.id), "name": org.name, "slug": org.slug, "status": str(org.status), "features": out}


@admin_router.get("/orgs/{org_id}/features")
async def org_features_admin(org_id: uuid.UUID, admin: PlatformUser = Depends(require_super_admin),
                             db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await _org_view(db, await _org_or_404(db, org_id))


@admin_router.put("/orgs/{org_id}/features/{key}")
async def set_org_feature(org_id: uuid.UUID, key: str, body: SettingBody, request: Request,
                          admin: PlatformUser = Depends(require_super_admin),
                          db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """One organisation's setting for a feature; null clears it so the
    organisation inherits the platform's default again."""
    org = await _org_or_404(db, org_id)
    feature = F.feature_or_404(key)
    before = (await F.settings_for(db, org_id))[F.ORG].get(key)
    await F.set_feature(db, scope_kind=F.ORG, scope_id=str(org_id), key=key, enabled=body.enabled,
                        reason=body.reason, by=admin)
    await audit_request(request, db, "feature.org", "feature", key, {
        "enabled": body.enabled, "was": bool(before.enabled) if before is not None else None,
        "default": feature.default_on, "reason": body.reason}, org_id=org_id)
    await db.commit()
    return await _org_view(db, org)

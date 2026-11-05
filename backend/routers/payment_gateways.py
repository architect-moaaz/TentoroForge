"""Settings → Payments: an organisation's payment gateways.

  GET    /api/payment-gateways/providers           what can be connected (no auth needed beyond sign-in)
  GET    /api/orgs/{org}/payment-gateways          every member: to choose one for an app (no keys)
  POST   /api/orgs/{org}/payment-gateways          admin: add one (its keys are checked first)
  PATCH  /api/orgs/{org}/payment-gateways/{id}     admin: name, coverage, currencies, keys, default
  POST   /api/orgs/{org}/payment-gateways/{id}/check   admin: ask the gateway again
  DELETE /api/orgs/{org}/payment-gateways/{id}     admin: remove (the apps that chose it are named)

Keys are never returned. An admin sees each key's last four characters; a
member sees which gateways exist and whether they are ready.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import OrgMemberRole
from services.payments import gateways as G
from services.payments import providers as P

log = logging.getLogger(__name__)
router = APIRouter(tags=["payment-gateways"])


class GatewayBody(BaseModel):
    provider: str | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=200)
    coverage: str | None = Field(default=None, max_length=16)
    homeCountry: str | None = Field(default=None, max_length=8)
    currencies: list[str] | None = Field(default=None, max_length=40)
    isDefault: bool | None = None
    test: dict[str, str] | None = None
    live: dict[str, str] | None = None
    clear: list[str] | None = Field(default=None, max_length=2)


async def _member(org_id: uuid.UUID, user: PlatformUser, db: AsyncSession, *, admin: bool):
    from services.org_access import require_org_member
    return await require_org_member(org_id, user, db, min_role=OrgMemberRole.admin if admin else OrgMemberRole.member)


def _is_admin(membership: Any) -> bool:
    return getattr(membership, "role", None) in (OrgMemberRole.admin, OrgMemberRole.owner)


def _fail(exc: G.GatewayError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/api/payment-gateways/providers")
async def gateway_providers(user: PlatformUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    return P.catalog()


@router.get("/api/orgs/{org_id}/payment-gateways")
async def list_gateways(org_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    membership = await _member(org_id, user, db, admin=False)
    admin = _is_admin(membership)
    rows = await G.listing(db, org_id)
    return {"gateways": [G.view(r, admin=admin) for r in rows], "canManage": admin}


@router.post("/api/orgs/{org_id}/payment-gateways", status_code=201)
async def add_gateway(org_id: uuid.UUID, body: GatewayBody, user: PlatformUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(org_id, user, db, admin=True)
    try:
        row = await G.create(db, org_id, user.id, body.model_dump(exclude_unset=True))
    except G.GatewayError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    await db.refresh(row)
    log.info("[payments] org %s added %s gateway %s", org_id, row.provider, row.id)
    return G.view(row, admin=True)


@router.patch("/api/orgs/{org_id}/payment-gateways/{gateway_id}")
async def edit_gateway(org_id: uuid.UUID, gateway_id: str, body: GatewayBody,
                       user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(org_id, user, db, admin=True)
    try:
        row = await G.get(db, org_id, gateway_id)
        data = body.model_dump(exclude_unset=True)
        if data.get("provider") and data["provider"] != row.provider:
            raise G.GatewayError("A gateway's provider cannot change. Add a new gateway instead.")
        row = await G.edit(db, row, user.id, data)
    except G.GatewayError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    await db.refresh(row)
    return G.view(row, admin=True)


@router.post("/api/orgs/{org_id}/payment-gateways/{gateway_id}/check")
async def check_gateway(org_id: uuid.UUID, gateway_id: str, user: PlatformUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(org_id, user, db, admin=True)
    try:
        row = await G.get(db, org_id, gateway_id)
    except G.GatewayError as exc:
        raise _fail(exc) from exc
    row = await G.recheck(row)
    await db.commit()
    await db.refresh(row)
    return G.view(row, admin=True)


@router.delete("/api/orgs/{org_id}/payment-gateways/{gateway_id}")
async def remove_gateway(org_id: uuid.UUID, gateway_id: str, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(org_id, user, db, admin=True)
    try:
        row = await G.get(db, org_id, gateway_id)
    except G.GatewayError as exc:
        raise _fail(exc) from exc
    apps = await _apps_using(db, org_id, str(row.id))
    heir = await G.remove(db, row)
    await db.commit()
    return {"removed": str(row.id), "apps": apps, "newDefault": {"id": str(heir.id), "label": heir.label} if heir else None}


@router.get("/api/orgs/{org_id}/payment-gateways/{gateway_id}/apps")
async def gateway_apps(org_id: uuid.UUID, gateway_id: str, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The applications that chose this gateway — said before it is removed."""
    await _member(org_id, user, db, admin=False)
    try:
        row = await G.get(db, org_id, gateway_id)
    except G.GatewayError as exc:
        raise _fail(exc) from exc
    return {"apps": await _apps_using(db, org_id, str(row.id))}


async def _apps_using(db: AsyncSession, org_id: uuid.UUID, gateway_id: str) -> list[dict[str, str]]:
    from models.project import Project
    from routers.blueprint_generate import _output_dir
    rows = (await db.execute(select(Project).where(Project.org_id == org_id))).scalars().all()
    dirs = []
    for p in rows:
        try:
            dirs.append((str(p.id), p.name or "", str(_output_dir(p))))
        except Exception:  # noqa: BLE001 — a project with no folder chose nothing
            continue
    return G.apps_using(dirs, gateway_id)


# --------------------------------------------------------------------------- #
# One application's payments
#
#   GET  /api/projects/{id}/payments          what it records, the org's gateways to choose from, its webhooks
#   POST /api/projects/{id}/payments/decide   Forge decides whether it takes money (once per definition)
#   PUT  /api/projects/{id}/payments          the owner's choice: gateways, what it sells, plans, access
# --------------------------------------------------------------------------- #

class ChoiceBody(BaseModel):
    needed: bool
    gateways: list[str] = Field(default_factory=list, max_length=3)
    models: list[str] | None = Field(default=None, max_length=2)
    plans: list[dict[str, Any]] | None = Field(default=None, max_length=8)
    access: str | None = Field(default=None, max_length=8)


async def _project(project_id: uuid.UUID, user: PlatformUser, db: AsyncSession):
    from routers.blueprint_generate import _output_dir
    from services.project_service import get_project_with_auth
    project = await get_project_with_auth(project_id, user, db)
    return project, _output_dir(project)


def _load(out: Any):
    from services.blueprint.service import BlueprintService
    try:
        return BlueprintService.load(output_dir=str(out))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="This app has no definition yet — describe it to Smith first.") from None


async def _payments_view(db: AsyncSession, project: Any, out: Any, user: PlatformUser) -> dict[str, Any]:
    from services.payments import app_payments as AP
    from services.payments import webhooks as W
    from services.org_access import require_org_member
    svc = _load(out)
    membership = await require_org_member(project.org_id, user, db)
    rows = await G.listing(db, project.org_id)
    admin = _is_admin(membership)
    return {"payments": AP.state(svc.doc), "gateways": [G.view(r, admin=False) for r in rows],
            "canManageGateways": admin, "webhooks": await W.setup_for(db, project.id, admin=admin, doc=svc.doc),
            # Whether the published app can take money: each chosen gateway's live keys.
            "readiness": AP.readiness(svc.doc, rows),
            "orgId": str(project.org_id)}


@router.get("/api/projects/{project_id}/payments")
async def project_payments(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    project, out = await _project(project_id, user, db)
    return await _payments_view(db, project, out, user)


@router.post("/api/projects/{project_id}/payments/decide")
async def decide_project_payments(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Forge's decision, made once per definition (a person's is never overruled)."""
    import asyncio
    from services import business_rules
    from services.payments import app_payments as AP
    project, out = await _project(project_id, user, db)
    _load(out)  # 404 before anything, when there is no definition yet
    if business_rules.building(out):
        return await _payments_view(db, project, out, user)
    def locked() -> None:
        with business_rules.write_lock(out, timeout=business_rules.TAB_LOCK_WAIT):
            AP.decide_and_record(_load(out))
    try:
        await asyncio.to_thread(locked)
    except business_rules.RuleError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return await _payments_view(db, project, out, user)


@router.put("/api/projects/{project_id}/payments")
async def choose_project_payments(project_id: uuid.UUID, body: ChoiceBody, user: PlatformUser = Depends(get_current_user),
                                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The owner's choice. Gateways are the organisation's own, by id; one per
    provider; a gateway whose keys were refused cannot be chosen until fixed."""
    import asyncio
    from services import business_rules
    from services.payments import app_payments as AP
    project, out = await _project(project_id, user, db)
    why = business_rules.busy(out)
    if why in ("building", "checking"):
        raise HTTPException(status_code=423, detail="Forge is building this app right now. Choose its payments when the build finishes.")
    rows: list = []
    for gid in body.gateways:
        try:
            row = await G.get(db, project.org_id, gid)
        except G.GatewayError:
            raise HTTPException(status_code=400, detail="That gateway is not one of your organisation's. Reload and choose again.") from None
        if G.status_of(row) == "attention":
            raise HTTPException(status_code=400, detail=f"{row.label}'s keys were refused by {row.provider.title()}. "
                                                        "Fix them in Settings → Payments, then choose it.")
        rows.append(row)
    def locked() -> None:
        with business_rules.write_lock(out, timeout=business_rules.TAB_LOCK_WAIT):
            # Checked again under the lock: a build rewrites the whole definition
            # without taking it, and one that began a moment ago would erase this.
            if business_rules.busy(out) in ("building", "checking"):
                raise business_rules.RuleError(
                    "Forge is building this app right now. Choose its payments when the build finishes.", status=423)
            AP.choose(_load(out), gateways=rows, needed=body.needed, models=body.models, plans=body.plans,
                      access=body.access, by="person", output_dir=str(out))
    try:
        await asyncio.to_thread(locked)
    except AP.ChoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except business_rules.RuleError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    # The preview's environment follows at once: the chosen gateways' test keys.
    try:
        from services.env_writer import write_env_local_from_platform
        await write_env_local_from_platform(project.output_dir, project.org_id, db)
    except Exception:  # noqa: BLE001 — the next sync writes it
        log.warning("[payments] the preview environment of %s could not be refreshed", project.id, exc_info=True)
    return await _payments_view(db, project, out, user)

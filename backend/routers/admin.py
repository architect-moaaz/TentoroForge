"""The cockpit: the platform as one person sees and runs it.

Every login, every organisation, every app, every membership — read here
under `require_super_admin`, and changed here with a reason that goes on
the record. Nothing in an organisation is reached around its own routes: to
work inside one the super admin impersonates one of its people, and every
request made that way is recorded with the admin's own name beside the
person's (`middleware.impersonation_audit`).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import IMPERSONATION_EXPIRE_MINUTES, create_impersonation_token
from database import get_db
from models.audit import AuditLog
from models.auth import SUPER_ADMIN, PlatformUser
from models.deployment import LIVE_STATUSES, Deployment
from models.org import InviteStatus, Organization, OrgMember, OrgMemberRole, OrgStatus
from models.project import Project, ProjectStatus
from platform_admin import require_super_admin
from schemas.audit import AuditLogResponse
from services.audit_service import audit_request
from services.org_access import ROLE_RANK

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

PAGE_SIZE = 50
PAGE_MAX = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _page(page: int, page_size: int) -> tuple[int, int]:
    size = max(1, min(page_size, PAGE_MAX))
    return size, (max(1, page) - 1) * size


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #

@router.get("/overview")
async def overview(admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    people = (await db.execute(select(func.count(PlatformUser.id)))).scalar() or 0
    super_admins = (await db.execute(
        select(func.count(PlatformUser.id)).where(PlatformUser.platform_role == SUPER_ADMIN))).scalar() or 0
    disabled = (await db.execute(
        select(func.count(PlatformUser.id)).where(PlatformUser.disabled_at.is_not(None)))).scalar() or 0
    by_status = dict((await db.execute(
        select(Organization.status, func.count(Organization.id)).group_by(Organization.status))).all())
    apps = (await db.execute(select(func.count(Project.id)))).scalar() or 0
    deployments = (await db.execute(select(func.count(Deployment.id)))).scalar() or 0
    return {
        "people": people,
        "super_admins": super_admins,
        "disabled_logins": disabled,
        "orgs": {s.value: int(by_status.get(s.value, 0)) for s in OrgStatus},
        "apps": apps,
        "deployments": deployments,
    }


@router.get("/incidents")
async def list_incidents(limit: int = Query(100, ge=1, le=500), admin: PlatformUser = Depends(require_super_admin)):
    """What went wrong on the platform, newest first: turns and builds whose
    process went away, faults the fix loop found to be the engine's."""
    from services import incidents
    return {"incidents": incidents.recent(limit)}


# --------------------------------------------------------------------------- #
# People
# --------------------------------------------------------------------------- #

class ReasonBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


def _person(user: PlatformUser, memberships: list[OrgMember]) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "auth_provider": user.auth_provider,
        "platform_role": user.platform_role,
        "disabled_at": user.disabled_at,
        "disabled_reason": user.disabled_reason,
        "last_sign_in_at": user.last_sign_in_at,
        "created_at": user.created_at,
        "orgs": [{"org_id": str(m.org_id), "org_name": m.organization.name, "slug": m.organization.slug,
                  "role": m.role.value, "status": m.organization.status}
                 for m in memberships if m.invite_status == InviteStatus.accepted],
        "spend_30d": None,
    }


@router.get("/people")
async def list_people(
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE, ge=1, le=PAGE_MAX),
    admin: PlatformUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    size, offset = _page(page, page_size)
    stmt = select(PlatformUser)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(PlatformUser.email.ilike(like), PlatformUser.name.ilike(like)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    users = (await db.execute(stmt.order_by(PlatformUser.email).limit(size).offset(offset))).scalars().all()
    ids = [u.id for u in users]
    memberships: dict[uuid.UUID, list[OrgMember]] = {}
    if ids:
        rows = (await db.execute(
            select(OrgMember).where(OrgMember.user_id.in_(ids)).options(selectinload(OrgMember.organization))
        )).scalars().all()
        for m in rows:
            memberships.setdefault(m.user_id, []).append(m)
    return {"items": [_person(u, memberships.get(u.id, [])) for u in users], "total": total,
            "page": page, "page_size": size}


async def _user_or_404(db: AsyncSession, user_id: uuid.UUID) -> PlatformUser:
    user = await db.get(PlatformUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return user


async def _memberships_of(db: AsyncSession, user_id: uuid.UUID) -> list[OrgMember]:
    return (await db.execute(
        select(OrgMember).where(OrgMember.user_id == user_id).options(selectinload(OrgMember.organization))
    )).scalars().all()


@router.post("/people/{user_id}/disable")
async def disable_person(
    user_id: uuid.UUID, body: ReasonBody, request: Request,
    admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot disable your own login")
    user = await _user_or_404(db, user_id)
    if user.disabled_at is not None:
        raise HTTPException(status_code=409, detail="This login is already disabled")
    user.disabled_at = _now()
    user.disabled_reason = body.reason
    user.disabled_by = admin.id
    await audit_request(request, db, "person.disable", "platform_user", str(user.id),
                        changes={"email": user.email, "reason": body.reason})
    await db.commit()
    return _person(user, await _memberships_of(db, user.id))


@router.post("/people/{user_id}/enable")
async def enable_person(
    user_id: uuid.UUID, request: Request,
    admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db),
):
    user = await _user_or_404(db, user_id)
    if user.disabled_at is None:
        raise HTTPException(status_code=409, detail="This login is not disabled")
    was = user.disabled_reason
    user.disabled_at = None
    user.disabled_reason = None
    user.disabled_by = None
    await audit_request(request, db, "person.enable", "platform_user", str(user.id),
                        changes={"email": user.email, "was_disabled_for": was})
    await db.commit()
    return _person(user, await _memberships_of(db, user.id))


@router.post("/people/{user_id}/super-admin")
async def grant_super_admin(
    user_id: uuid.UUID, request: Request,
    admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own platform role")
    user = await _user_or_404(db, user_id)
    if user.platform_role == SUPER_ADMIN:
        raise HTTPException(status_code=409, detail="Already a super admin")
    user.platform_role = SUPER_ADMIN
    await audit_request(request, db, "person.grant_super_admin", "platform_user", str(user.id),
                        changes={"email": user.email})
    await db.commit()
    return _person(user, await _memberships_of(db, user.id))


@router.delete("/people/{user_id}/super-admin")
async def revoke_super_admin(
    user_id: uuid.UUID, request: Request,
    admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db),
):
    # THE LAST ONE CANNOT LOCK EVERYONE OUT: a super admin never revokes
    # their own role, whoever else holds it.
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own platform role")
    user = await _user_or_404(db, user_id)
    if user.platform_role != SUPER_ADMIN:
        raise HTTPException(status_code=409, detail="Not a super admin")
    user.platform_role = None
    await audit_request(request, db, "person.revoke_super_admin", "platform_user", str(user.id),
                        changes={"email": user.email})
    await db.commit()
    return _person(user, await _memberships_of(db, user.id))


@router.post("/people/{user_id}/impersonate")
async def impersonate(
    user_id: uuid.UUID, request: Request,
    admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db),
):
    """A token to act as the person for `IMPERSONATION_EXPIRE_MINUTES`, no
    refresh. Not another super admin, not a disabled login, not oneself."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You are already yourself")
    user = await _user_or_404(db, user_id)
    if user.platform_role == SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="A super admin cannot be impersonated")
    if user.disabled_at is not None:
        raise HTTPException(status_code=409, detail="This login is disabled")
    memberships = [m for m in await _memberships_of(db, user.id)
                   if m.invite_status == InviteStatus.accepted and not m.organization.is_removed]
    memberships.sort(key=lambda m: (-ROLE_RANK.get(m.role, 0), m.organization.name))
    default_org = memberships[0].org_id if memberships else None
    token = create_impersonation_token(user.id, admin.id)
    expires_at = _now() + timedelta(minutes=IMPERSONATION_EXPIRE_MINUTES)
    await audit_request(request, db, "impersonation.start", "platform_user", str(user.id),
                        changes={"email": user.email, "expires_at": expires_at.isoformat()}, org_id=default_org)
    await db.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": _person(user, memberships),
        "default_org_id": str(default_org) if default_org else None,
    }


# --------------------------------------------------------------------------- #
# Organisations
# --------------------------------------------------------------------------- #

async def _org_or_404(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


async def _org_row(db: AsyncSession, org: Organization) -> dict[str, Any]:
    members = (await db.execute(select(func.count(OrgMember.id)).where(
        OrgMember.org_id == org.id, OrgMember.invite_status == InviteStatus.accepted))).scalar() or 0
    apps = (await db.execute(select(func.count(Project.id)).where(Project.org_id == org.id))).scalar() or 0
    owner = (await db.execute(
        select(PlatformUser.email).join(OrgMember, OrgMember.user_id == PlatformUser.id).where(
            OrgMember.org_id == org.id, OrgMember.role == OrgMemberRole.owner,
            OrgMember.invite_status == InviteStatus.accepted).order_by(OrgMember.created_at).limit(1)
    )).scalar()
    return {
        "id": str(org.id), "name": org.name, "slug": org.slug, "status": org.status,
        "status_reason": org.status_reason, "status_changed_at": org.status_changed_at,
        "members": members, "apps": apps, "owner_email": owner, "created_at": org.created_at,
    }


@router.get("/orgs")
async def list_orgs(
    q: str = Query("", max_length=200),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE, ge=1, le=PAGE_MAX),
    admin: PlatformUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    size, offset = _page(page, page_size)
    stmt = select(Organization)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Organization.name.ilike(like), Organization.slug.ilike(like)))
    if status:
        stmt = stmt.where(Organization.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    orgs = (await db.execute(stmt.order_by(Organization.name).limit(size).offset(offset))).scalars().all()
    return {"items": [await _org_row(db, o) for o in orgs], "total": total, "page": page, "page_size": size}


@router.get("/orgs/{org_id}")
async def get_org(org_id: uuid.UUID, admin: PlatformUser = Depends(require_super_admin),
                  db: AsyncSession = Depends(get_db)):
    return await _org_row(db, await _org_or_404(db, org_id))


async def _set_status(request: Request, db: AsyncSession, org: Organization, admin: PlatformUser,
                      status: OrgStatus, reason: str | None, allowed_from: tuple[OrgStatus, ...]) -> dict[str, Any]:
    if org.status not in {s.value for s in allowed_from}:
        raise HTTPException(status_code=409, detail=f"Organisation is {org.status}")
    was = org.status
    org.status = status.value
    org.status_reason = reason
    org.status_changed_at = _now()
    org.status_changed_by = admin.id
    await audit_request(request, db, f"org.{status.value}", "organization", str(org.id),
                        changes={"slug": org.slug, "from": was, "reason": reason}, org_id=org.id)
    await db.commit()
    return await _org_row(db, org)


@router.post("/orgs/{org_id}/block")
async def block_org(org_id: uuid.UUID, body: ReasonBody, request: Request,
                    admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    org = await _org_or_404(db, org_id)
    return await _set_status(request, db, org, admin, OrgStatus.blocked, body.reason, (OrgStatus.active,))


@router.post("/orgs/{org_id}/remove")
async def remove_org(org_id: uuid.UUID, body: ReasonBody, request: Request,
                     admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    org = await _org_or_404(db, org_id)
    return await _set_status(request, db, org, admin, OrgStatus.removed, body.reason,
                             (OrgStatus.active, OrgStatus.blocked))


@router.post("/orgs/{org_id}/reinstate")
async def reinstate_org(org_id: uuid.UUID, request: Request,
                        admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    org = await _org_or_404(db, org_id)
    return await _set_status(request, db, org, admin, OrgStatus.active, None,
                             (OrgStatus.blocked, OrgStatus.removed))


class PurgeBody(BaseModel):
    confirm_slug: str


@router.post("/orgs/{org_id}/purge")
async def purge_org(org_id: uuid.UUID, body: PurgeBody, request: Request,
                    admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    """Permanent. Only a removed organisation, and only with its slug typed
    back. What could not be removed is reported, never hidden."""
    from services.teardown import purge_organization
    org = await _org_or_404(db, org_id)
    if body.confirm_slug != org.slug:
        raise HTTPException(status_code=400, detail="Type the organisation's slug to confirm")
    if not org.is_removed:
        raise HTTPException(status_code=409, detail="Remove the organisation before purging it")
    await audit_request(request, db, "org.purge", "organization", str(org.id),
                        changes={"slug": org.slug, "name": org.name}, org_id=None)
    await db.commit()
    report = await purge_organization(db, org)
    return {"org_id": str(org_id), "slug": body.confirm_slug, **report}


# --------------------------------------------------------------------------- #
# Memberships and invites
# --------------------------------------------------------------------------- #

class MemberBody(BaseModel):
    email: EmailStr
    role: OrgMemberRole = OrgMemberRole.member


class RoleBody(BaseModel):
    role: OrgMemberRole


class TransferBody(BaseModel):
    user_id: uuid.UUID


def _member_row(m: OrgMember) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "user_id": str(m.user_id) if m.user_id else None,
        "email": m.user.email if m.user else m.invite_email,
        "name": m.user.name if m.user else None,
        "role": m.role.value,
        "invite_status": m.invite_status.value,
        "joined_at": m.joined_at,
        "created_at": m.created_at,
        "disabled": bool(m.user and m.user.disabled_at),
    }


async def _members(db: AsyncSession, org_id: uuid.UUID, *statuses: InviteStatus) -> list[OrgMember]:
    stmt = select(OrgMember).where(OrgMember.org_id == org_id).options(selectinload(OrgMember.user))
    if statuses:
        stmt = stmt.where(OrgMember.invite_status.in_(list(statuses)))
    return (await db.execute(stmt.order_by(OrgMember.created_at))).scalars().all()


async def _owners(db: AsyncSession, org_id: uuid.UUID) -> list[OrgMember]:
    return [m for m in await _members(db, org_id, InviteStatus.accepted) if m.role == OrgMemberRole.owner]


@router.get("/orgs/{org_id}/members")
async def list_members(org_id: uuid.UUID, admin: PlatformUser = Depends(require_super_admin),
                       db: AsyncSession = Depends(get_db)):
    await _org_or_404(db, org_id)
    return [_member_row(m) for m in await _members(db, org_id, InviteStatus.accepted, InviteStatus.pending)]


@router.post("/orgs/{org_id}/members", status_code=201)
async def add_member(org_id: uuid.UUID, body: MemberBody, request: Request,
                     admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    """A person with an account joins at once; one without gets a pending
    invite that accepting (`/api/orgs/{org}/invite/{id}/accept`) completes."""
    org = await _org_or_404(db, org_id)
    email = body.email.lower()
    user = (await db.execute(select(PlatformUser).where(func.lower(PlatformUser.email) == email))).scalar_one_or_none()
    existing = None
    if user is not None:
        existing = (await db.execute(select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == user.id))).scalar_one_or_none()
    if existing is None:
        existing = (await db.execute(select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id.is_(None),
            func.lower(OrgMember.invite_email) == email))).scalar_one_or_none()
    if existing is not None and existing.invite_status == InviteStatus.accepted:
        raise HTTPException(status_code=409, detail="Already a member")
    if existing is not None:
        membership = existing
        membership.role = body.role
    else:
        membership = OrgMember(org_id=org_id, role=body.role, invite_email=email)
        db.add(membership)
    if user is not None:
        membership.user_id = user.id
        membership.invite_status = InviteStatus.accepted
        membership.joined_at = _now()
    else:
        membership.invite_status = InviteStatus.pending
    await db.flush()
    await audit_request(request, db, "org.member_add" if user else "org.invite", "org_member", str(membership.id),
                        changes={"email": email, "role": body.role.value, "slug": org.slug}, org_id=org_id)
    await db.commit()
    await db.refresh(membership, attribute_names=["user"])
    return _member_row(membership)


async def _membership_or_404(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> OrgMember:
    m = (await db.execute(select(OrgMember).where(
        OrgMember.org_id == org_id, OrgMember.user_id == user_id,
        OrgMember.invite_status == InviteStatus.accepted).options(selectinload(OrgMember.user)))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Not a member of this organization")
    return m


@router.patch("/orgs/{org_id}/members/{user_id}")
async def change_member_role(org_id: uuid.UUID, user_id: uuid.UUID, body: RoleBody, request: Request,
                             admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    await _org_or_404(db, org_id)
    m = await _membership_or_404(db, org_id, user_id)
    if m.role == OrgMemberRole.owner and body.role != OrgMemberRole.owner and len(await _owners(db, org_id)) == 1:
        raise HTTPException(status_code=409, detail="An organisation keeps at least one owner")
    was = m.role.value
    m.role = body.role
    await audit_request(request, db, "org.member_role", "org_member", str(m.id),
                        changes={"email": m.user.email if m.user else m.invite_email, "from": was, "to": body.role.value},
                        org_id=org_id)
    await db.commit()
    return _member_row(m)


@router.delete("/orgs/{org_id}/members/{user_id}")
async def remove_member(org_id: uuid.UUID, user_id: uuid.UUID, request: Request,
                        admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    await _org_or_404(db, org_id)
    m = await _membership_or_404(db, org_id, user_id)
    if m.role == OrgMemberRole.owner and len(await _owners(db, org_id)) == 1:
        raise HTTPException(status_code=409, detail="An organisation keeps at least one owner")
    email = m.user.email if m.user else m.invite_email
    await db.delete(m)
    await audit_request(request, db, "org.member_remove", "org_member", str(user_id),
                        changes={"email": email}, org_id=org_id)
    await db.commit()
    return {"removed": True, "user_id": str(user_id)}


@router.post("/orgs/{org_id}/transfer-ownership")
async def transfer_ownership(org_id: uuid.UUID, body: TransferBody, request: Request,
                             admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    """The named member becomes the owner; every other owner becomes an admin."""
    await _org_or_404(db, org_id)
    target = await _membership_or_404(db, org_id, body.user_id)
    demoted = []
    for m in await _owners(db, org_id):
        if m.user_id != target.user_id:
            m.role = OrgMemberRole.admin
            demoted.append(m.user.email if m.user else m.invite_email)
    target.role = OrgMemberRole.owner
    await audit_request(request, db, "org.transfer_ownership", "org_member", str(target.id),
                        changes={"to": target.user.email if target.user else target.invite_email, "from": demoted},
                        org_id=org_id)
    await db.commit()
    return [_member_row(m) for m in await _members(db, org_id, InviteStatus.accepted)]


@router.get("/orgs/{org_id}/invites")
async def list_invites(org_id: uuid.UUID, admin: PlatformUser = Depends(require_super_admin),
                       db: AsyncSession = Depends(get_db)):
    await _org_or_404(db, org_id)
    return [_member_row(m) for m in await _members(db, org_id, InviteStatus.pending)]


async def _invite_or_404(db: AsyncSession, org_id: uuid.UUID, invite_id: uuid.UUID) -> OrgMember:
    m = (await db.execute(select(OrgMember).where(
        OrgMember.id == invite_id, OrgMember.org_id == org_id,
        OrgMember.invite_status == InviteStatus.pending).options(selectinload(OrgMember.user)))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return m


@router.delete("/orgs/{org_id}/invites/{invite_id}")
async def cancel_invite(org_id: uuid.UUID, invite_id: uuid.UUID, request: Request,
                        admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    await _org_or_404(db, org_id)
    m = await _invite_or_404(db, org_id, invite_id)
    email = m.invite_email
    await db.delete(m)
    await audit_request(request, db, "org.invite_cancel", "org_member", str(invite_id),
                        changes={"email": email}, org_id=org_id)
    await db.commit()
    return {"cancelled": True, "invite_id": str(invite_id)}


@router.post("/orgs/{org_id}/invites/{invite_id}/resend")
async def resend_invite(org_id: uuid.UUID, invite_id: uuid.UUID, request: Request,
                        admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    """The invite's accept address, and the email sent again when a template
    for it exists; otherwise the address is handed back to pass on."""
    org = await _org_or_404(db, org_id)
    m = await _invite_or_404(db, org_id, invite_id)
    accept_path = f"/api/orgs/{org_id}/invite/{invite_id}/accept"
    emailed = False
    try:
        from services.email_service import TEMPLATES, send_email
        template = next((t for t in ("org_invite", "invite", "invitation") if t in TEMPLATES), None)
        if template and m.invite_email:
            emailed = bool(await send_email(m.invite_email, template,
                                            {"org_name": org.name, "accept_path": accept_path, "role": m.role.value}))
    except Exception:  # noqa: BLE001 — the address is the answer either way
        logger.warning("[admin] the invite email could not be sent", exc_info=True)
    await audit_request(request, db, "org.invite_resend", "org_member", str(invite_id),
                        changes={"email": m.invite_email, "emailed": emailed}, org_id=org_id)
    await db.commit()
    return {**_member_row(m), "accept_path": accept_path, "emailed": emailed}


# --------------------------------------------------------------------------- #
# Apps
# --------------------------------------------------------------------------- #

def _app_output_dir(project: Project):
    from routers.blueprint_generate import _output_dir
    return _output_dir(project)


def _app_row(project: Project, org: Organization | None, owner_email: str | None,
             deployed_url: str | None) -> dict[str, Any]:
    from preview import get_preview_port
    from routers.blueprint_generate import build_in_flight
    in_flight = None
    try:
        in_flight = build_in_flight(_app_output_dir(project))
    except Exception:  # noqa: BLE001 — a ledger that cannot be read is not a build
        pass
    return {
        "id": str(project.id),
        "short_id": project.short_id,
        "name": project.name,
        "status": project.status.value if hasattr(project.status, "value") else str(project.status),
        "org": {"id": str(org.id), "name": org.name, "slug": org.slug, "status": org.status} if org else None,
        "owner_email": owner_email,
        "deployed_url": deployed_url,
        "build_in_flight": bool(in_flight),
        "preview_running": get_preview_port(project.short_id) is not None,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


async def _deployed_urls(db: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not project_ids:
        return {}
    rows = (await db.execute(
        select(Deployment.project_id, Deployment.url, Deployment.created_at).where(
            Deployment.project_id.in_(project_ids), Deployment.url.is_not(None), Deployment.status.in_(LIVE_STATUSES)
        ).order_by(Deployment.created_at.desc())
    )).all()
    out: dict[uuid.UUID, str] = {}
    for pid, url, _ in rows:
        out.setdefault(pid, url)
    return out


@router.get("/apps")
async def list_apps(
    q: str = Query("", max_length=200),
    org_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE, ge=1, le=PAGE_MAX),
    admin: PlatformUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    size, offset = _page(page, page_size)
    stmt = select(Project, Organization, PlatformUser.email).join(
        Organization, Organization.id == Project.org_id).outerjoin(PlatformUser, PlatformUser.id == Project.owner_id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Project.name.ilike(like), Project.short_id.ilike(like)))
    if org_id:
        stmt = stmt.where(Project.org_id == org_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await db.execute(stmt.order_by(Project.updated_at.desc()).limit(size).offset(offset))).all()
    urls = await _deployed_urls(db, [r[0].id for r in rows])
    return {"items": [_app_row(p, o, email, urls.get(p.id)) for p, o, email in rows],
            "total": total, "page": page, "page_size": size}


async def _project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _app_response(db: AsyncSession, project: Project) -> dict[str, Any]:
    # After a commit `updated_at` (set by the database) is expired, and a lazy
    # load has no greenlet to run on under asyncio: read the row back first.
    await db.refresh(project)
    org = await db.get(Organization, project.org_id)
    owner = await db.get(PlatformUser, project.owner_id) if project.owner_id else None
    urls = await _deployed_urls(db, [project.id])
    return _app_row(project, org, owner.email if owner else None, urls.get(project.id))


@router.post("/apps/{project_id}/stop-build")
async def stop_app_build(project_id: uuid.UUID, request: Request,
                         admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    from services import run_registry
    project = await _project_or_404(db, project_id)
    run_registry.request_stop(str(project.id), _app_output_dir(project))
    await audit_request(request, db, "app.stop_build", "project", str(project.id),
                        changes={"short_id": project.short_id}, org_id=project.org_id)
    await db.commit()
    return {"stopping": True, **await _app_response(db, project)}


@router.post("/apps/{project_id}/stop-preview")
async def stop_app_preview(project_id: uuid.UUID, request: Request,
                           admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    from preview import stop_preview
    project = await _project_or_404(db, project_id)
    was_running = stop_preview(project.short_id)
    await audit_request(request, db, "app.stop_preview", "project", str(project.id),
                        changes={"short_id": project.short_id, "was_running": was_running}, org_id=project.org_id)
    await db.commit()
    return {"stopped": was_running, **await _app_response(db, project)}


@router.post("/apps/{project_id}/archive")
async def archive_app(project_id: uuid.UUID, request: Request,
                      admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    project = await _project_or_404(db, project_id)
    project.status = ProjectStatus.archived
    await audit_request(request, db, "app.archive", "project", str(project.id),
                        changes={"short_id": project.short_id}, org_id=project.org_id)
    await db.commit()
    return await _app_response(db, project)


@router.post("/apps/{project_id}/unarchive")
async def unarchive_app(project_id: uuid.UUID, request: Request,
                        admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    project = await _project_or_404(db, project_id)
    if project.status != ProjectStatus.archived:
        raise HTTPException(status_code=409, detail="The app is not archived")
    project.status = ProjectStatus.ready
    await audit_request(request, db, "app.unarchive", "project", str(project.id),
                        changes={"short_id": project.short_id}, org_id=project.org_id)
    await db.commit()
    return await _app_response(db, project)


class DeleteAppBody(BaseModel):
    confirm_short_id: str


@router.post("/apps/{project_id}/delete")
async def delete_app(project_id: uuid.UUID, body: DeleteAppBody, request: Request,
                     admin: PlatformUser = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    """Permanent, with the app's short id typed back: the one teardown."""
    from services.teardown import remove_project
    project = await _project_or_404(db, project_id)
    if body.confirm_short_id != project.short_id:
        raise HTTPException(status_code=400, detail="Type the app's id to confirm")
    await audit_request(request, db, "app.delete", "project", str(project.id),
                        changes={"short_id": project.short_id, "name": project.name}, org_id=project.org_id)
    await db.commit()
    report = await remove_project(db, project)
    return {"project_id": str(project_id), **report}


# --------------------------------------------------------------------------- #
# Activity
# --------------------------------------------------------------------------- #

@router.get("/audit", response_model=list[AuditLogResponse])
async def list_activity(
    actor_user_id: uuid.UUID | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: PlatformUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).order_by(AuditLog.timestamp.desc())
    if actor_user_id:
        q = q.where(AuditLog.actor_user_id == actor_user_id)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if org_id:
        q = q.where(AuditLog.org_id == org_id)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    if since:
        q = q.where(AuditLog.timestamp >= since)
    if until:
        q = q.where(AuditLog.timestamp <= until)
    return (await db.execute(q.limit(limit).offset(offset))).scalars().all()

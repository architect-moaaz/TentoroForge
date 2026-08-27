"""Organization management endpoints.

Covers: org CRUD, membership/invites, people, departments, teams, roles, groups, bulk import.
"""

import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import EmailStr, validate_email
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import (
    Organization,
    OrgMember,
    OrgMemberRole,
    InviteStatus,
    Department,
    Team,
    OrgPerson,
    OrgRole,
    OrgPersonRole,
    OrgGroup,
    OrgGroupMember,
)
from schemas.org import (
    OrgCreate, OrgUpdate, OrgResponse,
    InviteRequest, InviteResponse,
    DepartmentCreate, DepartmentUpdate, DepartmentResponse,
    TeamCreate, TeamUpdate, TeamResponse,
    PersonCreate, PersonUpdate, PersonResponse,
    RoleCreate, RoleUpdate, RoleResponse,
    GroupCreate, GroupUpdate, GroupMembersUpdate, GroupResponse,
    ImportColumnMapping, ImportRowError, ImportResult,
)

router = APIRouter(tags=["organizations"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_org_member(
    org_id: uuid.UUID,
    user: PlatformUser,
    db: AsyncSession,
    min_role: OrgMemberRole = OrgMemberRole.member,
) -> OrgMember:
    """Verify the user is a member of the org with sufficient role."""
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

    role_hierarchy = {OrgMemberRole.owner: 3, OrgMemberRole.admin: 2, OrgMemberRole.member: 1}
    if role_hierarchy.get(membership.role, 0) < role_hierarchy.get(min_role, 0):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return membership


DEFAULT_ROLES = [
    {"name": "Admin", "description": "Full access to all features"},
    {"name": "Manager", "description": "Can manage team members and approve requests"},
    {"name": "Member", "description": "Standard access"},
]


# ===========================================================================
# Organization CRUD (0.1.4)
# ===========================================================================

@router.post("/api/orgs", response_model=OrgResponse, status_code=201)
async def create_org(
    req: OrgCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check slug uniqueness
    existing = await db.execute(
        select(Organization).where(Organization.slug == req.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Slug already taken")

    org = Organization(name=req.name, slug=req.slug, logo_url=req.logo_url)
    db.add(org)
    await db.flush()

    # Creator becomes owner
    membership = OrgMember(
        user_id=user.id,
        org_id=org.id,
        role=OrgMemberRole.owner,
        invite_status=InviteStatus.accepted,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(membership)

    # Create default roles
    for role_def in DEFAULT_ROLES:
        db.add(OrgRole(
            org_id=org.id, name=role_def["name"],
            description=role_def["description"], is_default=True,
        ))

    await db.commit()
    await db.refresh(org)
    return org


@router.get("/api/orgs", response_model=list[OrgResponse])
async def list_orgs(
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
        .order_by(Organization.name)
    )
    return result.scalars().all()


@router.get("/api/orgs/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.put("/api/orgs/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: uuid.UUID,
    req: OrgUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(org, field, value)

    await db.commit()
    await db.refresh(org)
    return org


@router.post("/api/orgs/{org_id}/logo", response_model=OrgResponse)
async def upload_org_logo(
    org_id: uuid.UUID,
    file: UploadFile = File(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store an uploaded org logo and record its public URL.

    Frontend (`org/[orgId]/settings/page.tsx`) uploads the file to this
    endpoint via multipart form-data. Without this endpoint the UI was
    silently 404ing, so the logo appeared to save but the URL never
    reached the DB (bug B-020.1). File is placed under
    `output/org-logos/{orgId}.{ext}`; the static mount at
    `/static/org-logos/…` in main.py serves it back.
    """
    from pathlib import Path
    import os

    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Constrain accepted types — reject video / archive / random binary
    # so a mis-picked file surfaces immediately instead of ending up as
    # a broken <img>. 2 MiB cap matches Caddy request_body limit / 25 with
    # comfortable headroom for typical PNG/SVG brand marks.
    ctype = (file.content_type or "").lower()
    ext_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/svg+xml": "svg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    if ctype not in ext_map:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {ctype or 'unknown'}. Use PNG, JPG, SVG, WebP, or GIF.",
        )
    ext = ext_map[ctype]

    body = await file.read()
    if len(body) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Logo file too large (max 2 MB)")
    if len(body) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Same directory main.py declares as the static mount. Filename uses
    # the org id so overwriting the same org's logo replaces cleanly and
    # never leaks the uploader's original filename.
    logos_dir = Path(__file__).resolve().parent.parent.parent / "output" / "org-logos"
    logos_dir.mkdir(parents=True, exist_ok=True)
    # Remove any prior extension for this org before writing — otherwise a
    # png→svg swap leaves the png orphaned and the static-file resolver
    # (which picks the first match by content-type) may still return it.
    for old in logos_dir.glob(f"{org_id}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    target = logos_dir / f"{org_id}.{ext}"
    target.write_bytes(body)

    # Cache-bust with mtime so the browser picks up the new file the
    # instant the mutation resolves — StaticFiles serves with
    # 'immutable'-friendly ETags but the URL itself must change to defeat
    # in-memory client caches.
    org.logo_url = f"/static/org-logos/{org_id}.{ext}?v={int(target.stat().st_mtime)}"
    await db.commit()
    await db.refresh(org)
    return org


# ===========================================================================
# Membership & Invitations (0.1.5)
# ===========================================================================

@router.post("/api/orgs/{org_id}/invite", response_model=InviteResponse, status_code=201)
async def invite_member(
    org_id: uuid.UUID,
    req: InviteRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)

    # Check if already a member
    existing = await db.execute(
        select(OrgMember).join(PlatformUser).where(
            OrgMember.org_id == org_id,
            PlatformUser.email == req.email,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already a member or invited")

    # Find user by email (may not exist yet)
    user_result = await db.execute(
        select(PlatformUser).where(PlatformUser.email == req.email)
    )
    target_user = user_result.scalar_one_or_none()

    membership = OrgMember(
        user_id=target_user.id if target_user else user.id,  # placeholder if no user
        org_id=org_id,
        role=OrgMemberRole(req.role),
        invite_status=InviteStatus.pending,
        invite_email=req.email,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return InviteResponse(
        id=membership.id,
        invite_email=membership.invite_email,
        role=membership.role.value,
        invite_status=membership.invite_status.value,
    )


@router.post("/api/orgs/{org_id}/invite/{invite_id}/accept")
async def accept_invite(
    org_id: uuid.UUID,
    invite_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.id == invite_id,
            OrgMember.org_id == org_id,
            OrgMember.invite_status == InviteStatus.pending,
        )
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    if invite.invite_email != user.email:
        raise HTTPException(status_code=403, detail="This invite is not for you")

    invite.user_id = user.id
    invite.invite_status = InviteStatus.accepted
    invite.joined_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "accepted"}


# ===========================================================================
# People CRUD (0.1.6)
# ===========================================================================

@router.get("/api/orgs/{org_id}/people", response_model=list[PersonResponse])
async def list_people(
    org_id: uuid.UUID,
    search: str | None = None,
    department_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)

    query = select(OrgPerson).where(OrgPerson.org_id == org_id)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            (OrgPerson.first_name.ilike(pattern))
            | (OrgPerson.last_name.ilike(pattern))
            | (OrgPerson.email.ilike(pattern))
        )
    if department_id:
        query = query.where(OrgPerson.department_id == department_id)
    if team_id:
        query = query.where(OrgPerson.team_id == team_id)
    if is_active is not None:
        query = query.where(OrgPerson.is_active == is_active)

    query = query.order_by(OrgPerson.last_name, OrgPerson.first_name)
    query = query.offset((page - 1) * limit).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/api/orgs/{org_id}/people", response_model=PersonResponse, status_code=201)
async def create_person(
    org_id: uuid.UUID,
    req: PersonCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)

    person = OrgPerson(org_id=org_id, **req.model_dump())
    db.add(person)
    await db.commit()
    await db.refresh(person)
    return person


@router.put("/api/orgs/{org_id}/people/{person_id}", response_model=PersonResponse)
async def update_person(
    org_id: uuid.UUID,
    person_id: uuid.UUID,
    req: PersonUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(
        select(OrgPerson).where(OrgPerson.id == person_id, OrgPerson.org_id == org_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    await db.commit()
    await db.refresh(person)
    return person


@router.delete("/api/orgs/{org_id}/people/{person_id}", status_code=204)
async def delete_person(
    org_id: uuid.UUID,
    person_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(
        select(OrgPerson).where(OrgPerson.id == person_id, OrgPerson.org_id == org_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    await db.delete(person)
    await db.commit()


# ===========================================================================
# Departments CRUD (0.1.7)
# ===========================================================================

@router.get("/api/orgs/{org_id}/departments", response_model=list[DepartmentResponse])
async def list_departments(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    result = await db.execute(
        select(Department).where(Department.org_id == org_id).order_by(Department.name)
    )
    return result.scalars().all()


@router.post("/api/orgs/{org_id}/departments", response_model=DepartmentResponse, status_code=201)
async def create_department(
    org_id: uuid.UUID,
    req: DepartmentCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    dept = Department(org_id=org_id, **req.model_dump())
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    return dept


@router.put("/api/orgs/{org_id}/departments/{dept_id}", response_model=DepartmentResponse)
async def update_department(
    org_id: uuid.UUID,
    dept_id: uuid.UUID,
    req: DepartmentUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(
        select(Department).where(Department.id == dept_id, Department.org_id == org_id)
    )
    dept = result.scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(dept, field, value)
    await db.commit()
    await db.refresh(dept)
    return dept


@router.delete("/api/orgs/{org_id}/departments/{dept_id}", status_code=204)
async def delete_department(
    org_id: uuid.UUID,
    dept_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(
        select(Department).where(Department.id == dept_id, Department.org_id == org_id)
    )
    dept = result.scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    await db.delete(dept)
    await db.commit()


# ===========================================================================
# Teams CRUD (0.1.7)
# ===========================================================================

@router.get("/api/orgs/{org_id}/teams", response_model=list[TeamResponse])
async def list_teams(
    org_id: uuid.UUID,
    department_id: uuid.UUID | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    query = select(Team).where(Team.org_id == org_id)
    if department_id:
        query = query.where(Team.department_id == department_id)
    result = await db.execute(query.order_by(Team.name))
    return result.scalars().all()


@router.post("/api/orgs/{org_id}/teams", response_model=TeamResponse, status_code=201)
async def create_team(
    org_id: uuid.UUID,
    req: TeamCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    team = Team(org_id=org_id, **req.model_dump())
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


@router.put("/api/orgs/{org_id}/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    org_id: uuid.UUID,
    team_id: uuid.UUID,
    req: TeamUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(
        select(Team).where(Team.id == team_id, Team.org_id == org_id)
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(team, field, value)
    await db.commit()
    await db.refresh(team)
    return team


@router.delete("/api/orgs/{org_id}/teams/{team_id}", status_code=204)
async def delete_team(
    org_id: uuid.UUID,
    team_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(
        select(Team).where(Team.id == team_id, Team.org_id == org_id)
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await db.delete(team)
    await db.commit()


# ===========================================================================
# Roles (0.1.8)
# ===========================================================================

@router.get("/api/orgs/{org_id}/roles", response_model=list[RoleResponse])
async def list_roles(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    result = await db.execute(
        select(OrgRole).where(OrgRole.org_id == org_id).order_by(OrgRole.name)
    )
    return result.scalars().all()


@router.post("/api/orgs/{org_id}/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    org_id: uuid.UUID,
    req: RoleCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    role = OrgRole(org_id=org_id, **req.model_dump())
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


@router.put("/api/orgs/{org_id}/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    req: RoleUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(
        select(OrgRole).where(OrgRole.id == role_id, OrgRole.org_id == org_id)
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    await db.commit()
    await db.refresh(role)
    return role


@router.delete("/api/orgs/{org_id}/roles/{role_id}", status_code=204)
async def delete_role(
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    result = await db.execute(
        select(OrgRole).where(OrgRole.id == role_id, OrgRole.org_id == org_id)
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete default roles")
    await db.delete(role)
    await db.commit()


# Assign / unassign roles to people
@router.post("/api/orgs/{org_id}/people/{person_id}/roles/{role_id}", status_code=201)
async def assign_role(
    org_id: uuid.UUID,
    person_id: uuid.UUID,
    role_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    assignment = OrgPersonRole(person_id=person_id, role_id=role_id)
    db.add(assignment)
    await db.commit()
    return {"status": "assigned"}


@router.delete("/api/orgs/{org_id}/people/{person_id}/roles/{role_id}", status_code=204)
async def unassign_role(
    org_id: uuid.UUID,
    person_id: uuid.UUID,
    role_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    await db.execute(
        delete(OrgPersonRole).where(
            OrgPersonRole.person_id == person_id,
            OrgPersonRole.role_id == role_id,
        )
    )
    await db.commit()


# ===========================================================================
# Groups (0.1.9)
# ===========================================================================

@router.get("/api/orgs/{org_id}/groups", response_model=list[GroupResponse])
async def list_groups(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    result = await db.execute(
        select(
            OrgGroup,
            func.count(OrgGroupMember.id).label("member_count"),
        )
        .outerjoin(OrgGroupMember)
        .where(OrgGroup.org_id == org_id)
        .group_by(OrgGroup.id)
        .order_by(OrgGroup.name)
    )
    groups = []
    for row in result.all():
        g = row[0]
        groups.append(GroupResponse(
            id=g.id, name=g.name, description=g.description,
            member_count=row[1], created_at=g.created_at,
        ))
    return groups


@router.post("/api/orgs/{org_id}/groups", response_model=GroupResponse, status_code=201)
async def create_group(
    org_id: uuid.UUID,
    req: GroupCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)
    group = OrgGroup(org_id=org_id, **req.model_dump())
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return GroupResponse(
        id=group.id, name=group.name, description=group.description,
        member_count=0, created_at=group.created_at,
    )


@router.put("/api/orgs/{org_id}/groups/{group_id}/members")
async def set_group_members(
    org_id: uuid.UUID,
    group_id: uuid.UUID,
    req: GroupMembersUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)

    # Verify group belongs to org
    result = await db.execute(
        select(OrgGroup).where(OrgGroup.id == group_id, OrgGroup.org_id == org_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Group not found")

    # Replace all members
    await db.execute(
        delete(OrgGroupMember).where(OrgGroupMember.group_id == group_id)
    )
    for pid in req.person_ids:
        db.add(OrgGroupMember(group_id=group_id, person_id=pid))
    await db.commit()
    return {"status": "updated", "member_count": len(req.person_ids)}


# ===========================================================================
# Bulk Import (0.1.10)
# ===========================================================================

@router.post("/api/orgs/{org_id}/people/import", response_model=ImportResult)
async def import_people(
    org_id: uuid.UUID,
    file: UploadFile = File(...),
    column_mapping: str = Form("{}"),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk import people from CSV or JSON file.

    Accepts:
      - CSV files (.csv) with header row
      - JSON files (.json) as array of objects

    The column_mapping form field is a JSON string mapping source column names
    to person fields (email, first_name, last_name, title, department, team, manager_email).
    If omitted, source columns are matched by their names directly.
    """
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)

    # Parse column mapping
    try:
        mapping_dict = json.loads(column_mapping) if column_mapping else {}
        mapping = ImportColumnMapping(**mapping_dict)
    except (json.JSONDecodeError, Exception):
        raise HTTPException(status_code=400, detail="Invalid column_mapping JSON")

    # Read file content
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # Handle BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    # Parse rows based on file type
    filename = (file.filename or "").lower()
    if filename.endswith(".json"):
        try:
            rows = json.loads(text)
            if not isinstance(rows, list):
                raise HTTPException(status_code=400, detail="JSON must be an array of objects")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")
    else:
        # Default to CSV
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)

    if not rows:
        return ImportResult(total_rows=0, imported=0, skipped=0, errors=[])

    # Pre-load existing departments and teams for name matching
    dept_result = await db.execute(
        select(Department).where(Department.org_id == org_id)
    )
    dept_by_name = {d.name.lower(): d.id for d in dept_result.scalars().all()}

    team_result = await db.execute(
        select(Team).where(Team.org_id == org_id)
    )
    team_by_name = {t.name.lower(): t.id for t in team_result.scalars().all()}

    # Pre-load existing people emails for duplicate detection + manager lookup
    people_result = await db.execute(
        select(OrgPerson).where(OrgPerson.org_id == org_id)
    )
    existing_emails = {p.email.lower(): p.id for p in people_result.scalars().all()}

    errors: list[ImportRowError] = []
    imported = 0
    skipped = 0
    # Track newly created people for manager resolution in second pass
    new_people: list[tuple[OrgPerson, str | None]] = []  # (person, manager_email)

    for idx, row in enumerate(rows, start=1):
        # Extract fields using column mapping
        email_raw = _get_field(row, mapping.email)
        first_name = _get_field(row, mapping.first_name)
        last_name = _get_field(row, mapping.last_name)
        title = _get_field(row, mapping.title)
        dept_name = _get_field(row, mapping.department)
        team_name = _get_field(row, mapping.team)
        manager_email = _get_field(row, mapping.manager_email)

        # Validate required fields
        if not email_raw or not email_raw.strip():
            errors.append(ImportRowError(row=idx, field="email", message="Email is required"))
            skipped += 1
            continue
        email = email_raw.strip().lower()

        try:
            validate_email(email)
        except Exception:
            errors.append(ImportRowError(
                row=idx, field="email", message="Invalid email format", value=email,
            ))
            skipped += 1
            continue

        if not first_name or not first_name.strip():
            errors.append(ImportRowError(row=idx, field="first_name", message="First name is required"))
            skipped += 1
            continue

        if not last_name or not last_name.strip():
            errors.append(ImportRowError(row=idx, field="last_name", message="Last name is required"))
            skipped += 1
            continue

        # Skip duplicates
        if email in existing_emails:
            errors.append(ImportRowError(
                row=idx, field="email", message="Person with this email already exists", value=email,
            ))
            skipped += 1
            continue

        # Resolve department and team by name
        department_id = None
        if dept_name and dept_name.strip():
            department_id = dept_by_name.get(dept_name.strip().lower())
            if not department_id:
                errors.append(ImportRowError(
                    row=idx, field="department",
                    message=f"Department not found: '{dept_name.strip()}'", value=dept_name.strip(),
                ))

        team_id = None
        if team_name and team_name.strip():
            team_id = team_by_name.get(team_name.strip().lower())
            if not team_id:
                errors.append(ImportRowError(
                    row=idx, field="team",
                    message=f"Team not found: '{team_name.strip()}'", value=team_name.strip(),
                ))

        person = OrgPerson(
            org_id=org_id,
            email=email,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            title=title.strip() if title else None,
            department_id=department_id,
            team_id=team_id,
        )
        db.add(person)
        existing_emails[email] = None  # Mark as seen (ID filled after flush)
        new_people.append((person, manager_email.strip().lower() if manager_email and manager_email.strip() else None))
        imported += 1

    # Flush to get IDs for manager resolution
    if new_people:
        await db.flush()

        # Update existing_emails with real IDs
        for person, _ in new_people:
            existing_emails[person.email.lower()] = person.id

        # Second pass: resolve manager_email → manager_id
        for person, mgr_email in new_people:
            if mgr_email:
                manager_id = existing_emails.get(mgr_email)
                if manager_id:
                    person.manager_id = manager_id
                else:
                    errors.append(ImportRowError(
                        row=0, field="manager_email",
                        message=f"Manager not found: '{mgr_email}'",
                        value=mgr_email,
                    ))

    await db.commit()

    return ImportResult(
        total_rows=len(rows),
        imported=imported,
        skipped=skipped,
        errors=errors,
    )


def _get_field(row: dict, field_name: str | None) -> str | None:
    """Extract a field value from a row dict, case-insensitive."""
    if not field_name:
        return None
    # Try exact match first
    if field_name in row:
        return row[field_name]
    # Case-insensitive fallback
    for key in row:
        if key.lower() == field_name.lower():
            return row[key]
    return None


# ===========================================================================
# Org Chart API (0.1.11)
# ===========================================================================

@router.get("/api/orgs/{org_id}/org-chart")
async def get_org_chart(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns the full org tree: departments → teams → people with reporting lines."""
    await _require_org_member(org_id, user, db)

    # Load all data
    depts = (await db.execute(
        select(Department).where(Department.org_id == org_id)
    )).scalars().all()

    teams = (await db.execute(
        select(Team).where(Team.org_id == org_id)
    )).scalars().all()

    people = (await db.execute(
        select(OrgPerson).where(OrgPerson.org_id == org_id, OrgPerson.is_active == True)
    )).scalars().all()

    # Build department tree
    dept_map = {d.id: {
        "id": str(d.id), "name": d.name, "description": d.description,
        "parent_id": str(d.parent_id) if d.parent_id else None,
        "head_person_id": str(d.head_person_id) if d.head_person_id else None,
        "teams": [], "people": [],
    } for d in depts}

    team_map = {t.id: {
        "id": str(t.id), "name": t.name, "description": t.description,
        "department_id": str(t.department_id) if t.department_id else None,
        "lead_person_id": str(t.lead_person_id) if t.lead_person_id else None,
        "people": [],
    } for t in teams}

    person_list = [{
        "id": str(p.id), "email": p.email,
        "first_name": p.first_name, "last_name": p.last_name,
        "title": p.title,
        "department_id": str(p.department_id) if p.department_id else None,
        "team_id": str(p.team_id) if p.team_id else None,
        "manager_id": str(p.manager_id) if p.manager_id else None,
    } for p in people]

    # Assign people to teams/departments
    for p in person_list:
        if p["team_id"] and uuid.UUID(p["team_id"]) in team_map:
            team_map[uuid.UUID(p["team_id"])]["people"].append(p)
        elif p["department_id"] and uuid.UUID(p["department_id"]) in dept_map:
            dept_map[uuid.UUID(p["department_id"])]["people"].append(p)

    # Assign teams to departments
    for t in team_map.values():
        if t["department_id"] and uuid.UUID(t["department_id"]) in dept_map:
            dept_map[uuid.UUID(t["department_id"])]["teams"].append(t)

    # Build hierarchy (root departments first)
    root_depts = [d for d in dept_map.values() if d["parent_id"] is None]
    unassigned = [p for p in person_list if not p["department_id"] and not p["team_id"]]
    orphan_teams = [t for t in team_map.values() if not t["department_id"]]

    return {
        "departments": root_depts,
        "unassigned_teams": orphan_teams,
        "unassigned_people": unassigned,
    }

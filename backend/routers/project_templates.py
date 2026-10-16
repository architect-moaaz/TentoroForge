"""Templates made from an organisation's own applications.

Save one from any project with a definition; list them in the gallery; start a
new project from one. What a template holds, and how it is used once the new
project's Smith asks "the exact same app, or something like it?", is
`services.project_templates`.

Every route checks membership of the organisation the template belongs to: a
template carries a whole application's definition, so it is as private as the
project it was taken from.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import InviteStatus, OrgMember, OrgMemberRole
from schemas.project import ProjectResponse
from services import project_templates as templates
from services.project_service import create_project, get_project_with_auth

router = APIRouter(tags=["project-templates"])


class SaveTemplateRequest(BaseModel):
    name: str = Field(default="", max_length=templates.NAME_MAX)
    description: str = Field(default="", max_length=templates.DESCRIPTION_MAX)
    category: str = Field(default="", max_length=60)


class UpdateTemplateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=templates.NAME_MAX)
    description: str | None = Field(default=None, max_length=templates.DESCRIPTION_MAX)


class UseTemplateRequest(BaseModel):
    template_id: str
    name: str = Field(min_length=1, max_length=255)


async def _membership(db: AsyncSession, org_id: str, user: PlatformUser) -> OrgMember | None:
    try:
        org_uuid = uuid.UUID(str(org_id))
    except ValueError:
        return None
    result = await db.execute(select(OrgMember).where(
        OrgMember.org_id == org_uuid, OrgMember.user_id == user.id,
        OrgMember.invite_status == InviteStatus.accepted))
    return result.scalar_one_or_none()


async def _visible(db: AsyncSession, template_id: str, user: PlatformUser) -> tuple[dict, OrgMember]:
    """The template, if the caller belongs to its organisation — else 404, so a
    template id from another organisation reveals nothing about it."""
    meta = templates.get(template_id)
    member = await _membership(db, meta["org_id"], user) if meta else None
    if not meta or not member:
        raise HTTPException(status_code=404, detail="Template not found")
    return meta, member


def _may_manage(meta: dict, member: OrgMember, user: PlatformUser) -> bool:
    return (str(meta.get("created_by")) == str(user.id)
            or member.role in (OrgMemberRole.owner, OrgMemberRole.admin))


def _public(meta: dict, user: PlatformUser, member: OrgMember | None = None) -> dict:
    out = {k: meta.get(k) for k in (
        "id", "org_id", "name", "description", "category", "created_by", "created_by_name",
        "source_project_id", "created_at", "updated_at", "summary")}
    out["can_manage"] = bool(member) and _may_manage(meta, member, user)
    return out


@router.get("/api/orgs/{org_id}/project-templates")
async def list_org_templates(org_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    member = await _membership(db, str(org_id), user)
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return {"templates": [_public(m, user, member) for m in templates.list_for_org(str(org_id))]}


@router.post("/api/projects/{project_id}/templates", status_code=201)
async def save_project_as_template(project_id: uuid.UUID, req: SaveTemplateRequest,
                                   user: PlatformUser = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    """Save this project's application as a template — at any point once it has
    a definition, built or not."""
    project = await get_project_with_auth(project_id, user, db)
    from routers.blueprint_generate import _output_dir
    try:
        meta = templates.save(output_dir=_output_dir(project), org_id=str(project.org_id),
                              created_by=str(user.id), created_by_name=user.name or "",
                              source_project_id=str(project.id), name=req.name,
                              description=req.description, category=req.category)
    except templates.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    member = await _membership(db, str(project.org_id), user)
    return _public(meta, user, member)


@router.get("/api/project-templates/{template_id}")
async def get_template(template_id: str, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    meta, member = await _visible(db, template_id, user)
    return _public(meta, user, member)


@router.patch("/api/project-templates/{template_id}")
async def update_template(template_id: str, req: UpdateTemplateRequest,
                          user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    meta, member = await _visible(db, template_id, user)
    if not _may_manage(meta, member, user):
        raise HTTPException(status_code=403, detail="Only its creator or an admin can change it")
    try:
        meta = templates.update(template_id, name=req.name, description=req.description)
    except templates.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _public(meta, user, member)


@router.delete("/api/project-templates/{template_id}", status_code=204)
async def delete_template(template_id: str, user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    meta, member = await _visible(db, template_id, user)
    if not _may_manage(meta, member, user):
        raise HTTPException(status_code=403, detail="Only its creator or an admin can delete it")
    templates.delete(template_id)


@router.post("/api/orgs/{org_id}/projects/from-project-template", response_model=ProjectResponse,
             status_code=201)
async def create_from_project_template(org_id: uuid.UUID, req: UseTemplateRequest,
                                       user: PlatformUser = Depends(get_current_user),
                                       db: AsyncSession = Depends(get_db)):
    """A new project, with the template staged in it. Nothing is defined yet:
    the project's Smith asks whether the person wants the exact same app or
    one like it, and uses the template accordingly."""
    if not await _membership(db, str(org_id), user):
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    meta = templates.get(req.template_id)
    if not meta or str(meta.get("org_id")) != str(org_id):
        raise HTTPException(status_code=404, detail="Template not found")
    project = await create_project(org_id=org_id, owner_id=user.id, name=req.name.strip(),
                                   description=meta.get("description") or "", db=db)
    from routers.blueprint_generate import _output_dir
    try:
        templates.stage(req.template_id, _output_dir(project))
    except templates.TemplateError as exc:
        await db.rollback()
        import shutil
        shutil.rmtree(_output_dir(project), ignore_errors=True)  # no orphan folder
        raise HTTPException(status_code=400, detail=str(exc))
    project.brief = {**(project.brief or {}),
                     "template": {"id": meta["id"], "name": meta["name"]}}
    await db.commit()
    await db.refresh(project)
    return project

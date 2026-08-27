"""Template gallery and create-from-template endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.template import AppTemplate
from models.org import OrgMember, OrgMemberRole, InviteStatus, Department
from schemas.template import (
    TemplateResponse,
    TemplateDetailResponse,
    TemplateListResponse,
    CreateFromTemplateRequest,
    SuggestedTemplateResponse,
    SuggestedTemplatesResponse,
)
from schemas.project import ProjectResponse
from services.project_service import create_project
from services.suggestion_service import get_suggested_templates

router = APIRouter(tags=["templates"])


# ---------------------------------------------------------------------------
# Template gallery
# ---------------------------------------------------------------------------

@router.get("/api/templates", response_model=TemplateListResponse)
async def list_templates(
    category: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List published templates, optionally filtered by category."""
    q = select(AppTemplate).where(AppTemplate.is_published == True)
    if category:
        q = q.where(AppTemplate.category == category)
    if search:
        pattern = f"%{search}%"
        q = q.where(
            AppTemplate.name.ilike(pattern) | AppTemplate.description.ilike(pattern)
        )
    q = q.order_by(AppTemplate.category, AppTemplate.name)
    result = await db.execute(q)
    templates = result.scalars().all()

    # Collect unique categories
    cat_result = await db.execute(
        select(AppTemplate.category)
        .where(AppTemplate.is_published == True)
        .distinct()
        .order_by(AppTemplate.category)
    )
    categories = [row[0] for row in cat_result.all()]

    return TemplateListResponse(
        templates=[TemplateResponse.model_validate(t) for t in templates],
        categories=categories,
    )


@router.get("/api/templates/{slug}", response_model=TemplateDetailResponse)
async def get_template(slug: str, db: AsyncSession = Depends(get_db)):
    """Get template details including the plan JSON."""
    result = await db.execute(
        select(AppTemplate).where(AppTemplate.slug == slug)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


# ---------------------------------------------------------------------------
# Create project from template
# ---------------------------------------------------------------------------

@router.post("/api/orgs/{org_id}/projects/from-template", response_model=ProjectResponse, status_code=201)
async def create_from_template(
    org_id: uuid.UUID,
    req: CreateFromTemplateRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project from a template and kick off generation."""
    # Verify org membership
    membership = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
    )
    if not membership.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    # Find template
    result = await db.execute(
        select(AppTemplate).where(AppTemplate.slug == req.template_slug)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Create project
    project = await create_project(
        org_id=org_id,
        owner_id=user.id,
        name=req.name,
        description=template.description,
        db=db,
    )
    await db.commit()
    await db.refresh(project)
    return project


# ---------------------------------------------------------------------------
# Suggested apps for an org
# ---------------------------------------------------------------------------

@router.get("/api/orgs/{org_id}/suggested-apps", response_model=SuggestedTemplatesResponse)
async def suggested_apps(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get template suggestions based on the org's departments."""
    # Verify membership
    membership = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
    )
    if not membership.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    results = await get_suggested_templates(org_id, db)

    # Get department names for response
    dept_result = await db.execute(
        select(Department.name).where(Department.org_id == org_id)
    )
    dept_names = [row[0] for row in dept_result.all()]

    suggestions = [
        SuggestedTemplateResponse(
            template=TemplateResponse.model_validate(r["template"]),
            score=r["score"],
            matching_departments=r["matching_departments"],
            reason=r["reason"],
        )
        for r in results
    ]

    return SuggestedTemplatesResponse(
        suggestions=suggestions,
        org_departments=dept_names,
    )


# ---------------------------------------------------------------------------
# Seed templates (admin endpoint)
# ---------------------------------------------------------------------------

@router.post("/api/templates/seed", status_code=201)
async def seed_templates(db: AsyncSession = Depends(get_db)):
    """Seed the database with default templates."""
    from seeds.templates import TEMPLATE_SEEDS

    count = 0
    for tmpl_data in TEMPLATE_SEEDS:
        # Check if slug already exists
        existing = await db.execute(
            select(AppTemplate).where(AppTemplate.slug == tmpl_data["slug"])
        )
        if existing.scalar_one_or_none():
            continue
        template = AppTemplate(**tmpl_data, is_published=True)
        db.add(template)
        count += 1

    await db.commit()
    return {"seeded": count}

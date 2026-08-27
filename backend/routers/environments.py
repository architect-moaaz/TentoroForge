"""Environment endpoints — CRUD environments per project."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.environment import Environment
from services.project_service import get_project_with_auth

router = APIRouter(tags=["environments"])


class EnvironmentCreate(BaseModel):
    name: str
    description: str | None = None
    config: dict | None = None


class EnvironmentUpdate(BaseModel):
    description: str | None = None
    config: dict | None = None
    secrets: dict | None = None
    is_active: bool | None = None


class EnvironmentResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    config: dict | None
    is_active: bool

    model_config = {"from_attributes": True}


@router.get(
    "/api/projects/{project_id}/environments",
    response_model=list[EnvironmentResponse],
)
async def list_environments(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(Environment)
        .where(Environment.project_id == project_id)
        .order_by(Environment.name)
    )
    return result.scalars().all()


@router.post(
    "/api/projects/{project_id}/environments",
    response_model=EnvironmentResponse,
    status_code=201,
)
async def create_environment(
    project_id: uuid.UUID,
    req: EnvironmentCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    env = Environment(
        project_id=project_id,
        name=req.name,
        description=req.description,
        config=req.config or {},
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return env


@router.put(
    "/api/projects/{project_id}/environments/{env_id}",
    response_model=EnvironmentResponse,
)
async def update_environment(
    project_id: uuid.UUID,
    env_id: uuid.UUID,
    req: EnvironmentUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(Environment).where(
            Environment.id == env_id,
            Environment.project_id == project_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(env, field, value)

    await db.commit()
    await db.refresh(env)
    return env


@router.delete(
    "/api/projects/{project_id}/environments/{env_id}",
    status_code=204,
)
async def delete_environment(
    project_id: uuid.UUID,
    env_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(Environment).where(
            Environment.id == env_id,
            Environment.project_id == project_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    await db.delete(env)
    await db.commit()

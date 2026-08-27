"""Module system endpoints — CRUD, dependencies, and connections map."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from schemas.module import (
    ModuleCreate,
    ModuleUpdate,
    ModuleResponse,
    ModuleDetailResponse,
    ModuleDependencyResponse,
    DependenciesUpdateRequest,
    ModuleConnectionsResponse,
)
from services.module_service import (
    create_module,
    get_module,
    list_modules,
    update_module,
    delete_module,
    get_dependencies,
    update_dependencies,
    get_connections_map,
)
from services.project_service import get_project_with_auth

router = APIRouter(tags=["modules"])


# ---------------------------------------------------------------------------
# Module CRUD
# ---------------------------------------------------------------------------

@router.post(
    "/api/projects/{project_id}/modules",
    response_model=ModuleResponse,
    status_code=201,
)
async def create_module_endpoint(
    project_id: uuid.UUID,
    req: ModuleCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    module = await create_module(
        project_id=project_id,
        name=req.name,
        description=req.description,
        dependency_ids=req.dependencies,
        db=db,
    )
    await db.commit()
    await db.refresh(module)
    return module


@router.get(
    "/api/projects/{project_id}/modules",
    response_model=list[ModuleResponse],
)
async def list_modules_endpoint(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    return await list_modules(project_id, db)


@router.get(
    "/api/projects/{project_id}/modules/connections",
    response_model=ModuleConnectionsResponse,
)
async def get_module_connections(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    return await get_connections_map(project_id, db)


@router.get(
    "/api/projects/{project_id}/modules/{module_id}",
    response_model=ModuleDetailResponse,
)
async def get_module_endpoint(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    return await get_module(project_id, module_id, db)


@router.put(
    "/api/projects/{project_id}/modules/{module_id}",
    response_model=ModuleResponse,
)
async def update_module_endpoint(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    req: ModuleUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    module = await update_module(
        project_id=project_id,
        module_id=module_id,
        updates=req.model_dump(exclude_unset=True),
        db=db,
    )
    await db.commit()
    await db.refresh(module)
    return module


@router.delete(
    "/api/projects/{project_id}/modules/{module_id}",
    status_code=204,
)
async def delete_module_endpoint(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    await delete_module(project_id, module_id, db)
    await db.commit()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

@router.get(
    "/api/projects/{project_id}/modules/{module_id}/dependencies",
    response_model=list[ModuleDependencyResponse],
)
async def get_module_dependencies(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    return await get_dependencies(project_id, module_id, db)


@router.put(
    "/api/projects/{project_id}/modules/{module_id}/dependencies",
    response_model=list[ModuleDependencyResponse],
)
async def update_module_dependencies(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    req: DependenciesUpdateRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    deps = await update_dependencies(
        project_id=project_id,
        module_id=module_id,
        deps=[d.model_dump() for d in req.dependencies],
        db=db,
    )
    await db.commit()
    return deps

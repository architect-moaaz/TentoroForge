"""Export & deployment endpoints — Dockerfile, docker-compose, README, env, git push."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.project_service import get_project_with_auth
from services.export_service import (
    generate_dockerfile,
    generate_docker_compose,
    generate_env_example,
    generate_readme,
    push_to_git,
    write_production_bundle,
)

router = APIRouter(tags=["export"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class GitPushRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    token: str | None = None


class FileContentResponse(BaseModel):
    filename: str
    content: str


class GitPushResponse(BaseModel):
    success: bool
    branch: str
    repo_url: str
    commit_hash: str | None = None


class ProductionBundleResponse(BaseModel):
    files_written: list[str]
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/api/projects/{project_id}/export/dockerfile",
    response_model=FileContentResponse,
)
async def export_dockerfile(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return a production Dockerfile for the project."""
    project = await get_project_with_auth(project_id, user, db)
    content = generate_dockerfile(project.name)
    return FileContentResponse(filename="Dockerfile", content=content)


@router.post(
    "/api/projects/{project_id}/export/docker-compose",
    response_model=FileContentResponse,
)
async def export_docker_compose(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return a docker-compose.yml for the project."""
    project = await get_project_with_auth(project_id, user, db)
    content = generate_docker_compose(project.name)
    return FileContentResponse(filename="docker-compose.yml", content=content)


@router.post(
    "/api/projects/{project_id}/export/readme",
    response_model=FileContentResponse,
)
async def export_readme(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return a README.md for the project."""
    project = await get_project_with_auth(project_id, user, db)
    content = generate_readme(project.name, project.description)
    return FileContentResponse(filename="README.md", content=content)


@router.post(
    "/api/projects/{project_id}/export/env-example",
    response_model=FileContentResponse,
)
async def export_env_example(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return a .env.example for the project."""
    project = await get_project_with_auth(project_id, user, db)
    content = generate_env_example(project.name)
    return FileContentResponse(filename=".env.example", content=content)


@router.post(
    "/api/projects/{project_id}/export/git-push",
    response_model=GitPushResponse,
)
async def export_git_push(
    project_id: uuid.UUID,
    req: GitPushRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push the generated project code to an external git repository."""
    project = await get_project_with_auth(project_id, user, db)

    if not project.output_dir or not Path(project.output_dir).exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    try:
        result = await push_to_git(
            output_dir=project.output_dir,
            repo_url=req.repo_url,
            branch=req.branch,
            token=req.token,
        )
        return GitPushResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/api/projects/{project_id}/export/production-bundle",
    response_model=ProductionBundleResponse,
)
async def export_production_bundle(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate all production deployment files and add them to the project output directory."""
    project = await get_project_with_auth(project_id, user, db)

    if not project.output_dir or not Path(project.output_dir).exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    try:
        files_written = write_production_bundle(
            output_dir=project.output_dir,
            app_name=project.name,
            description=project.description,
        )
        return ProductionBundleResponse(
            files_written=files_written,
            message=f"Successfully generated {len(files_written)} production files.",
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

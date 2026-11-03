"""File storage endpoints — upload/download with auth via S3.

Every key is `projects/<project id>/<file name>`, and every route checks the
caller is a member of that project's organisation: a signed-in person could
read or delete any organisation's file by key, and a `../` in an uploaded
name wrote outside the project (audit, 2026-11-01).
"""

import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services import storage_service
from services.project_service import get_project_with_auth

router = APIRouter(prefix="/api/files", tags=["files"])


def _project_of(key: str) -> uuid.UUID:
    parts = (key or "").split("/")
    if len(parts) < 3 or parts[0] != "projects" or any(p in ("", ".", "..") for p in parts[2:]):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        return uuid.UUID(parts[1])
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")


@router.post("/upload")
async def upload_file(
    project_id: uuid.UUID = Query(...),
    file: UploadFile = File(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file to S3 storage."""
    if not storage_service.is_configured():
        raise HTTPException(status_code=501, detail="File storage not configured")
    await get_project_with_auth(project_id, user, db)
    name = PurePosixPath((file.filename or "").replace("\\", "/")).name
    if name in ("", ".", ".."):
        raise HTTPException(status_code=422, detail="The file needs a name")

    key = f"projects/{project_id}/{name}"
    result = await storage_service.upload_file(
        key=key,
        file_obj=file.file,
        content_type=file.content_type or "application/octet-stream",
    )

    if not result:
        raise HTTPException(status_code=500, detail="Upload failed")

    signed_url = await storage_service.generate_signed_url(key)
    return {"key": key, "filename": name, "url": signed_url}


@router.get("/download")
async def download_file(
    key: str = Query(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a signed download URL for a file."""
    if not storage_service.is_configured():
        raise HTTPException(status_code=501, detail="File storage not configured")
    await get_project_with_auth(_project_of(key), user, db)

    url = await storage_service.generate_signed_url(key)
    if not url:
        raise HTTPException(status_code=404, detail="File not found")

    return {"url": url}


@router.delete("")
async def delete_file(
    key: str = Query(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file from storage."""
    if not storage_service.is_configured():
        raise HTTPException(status_code=501, detail="File storage not configured")
    await get_project_with_auth(_project_of(key), user, db)

    deleted = await storage_service.delete_file(key)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")

    return {"deleted": True}

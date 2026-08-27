"""File storage endpoints — upload/download with auth via S3."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services import storage_service

router = APIRouter(prefix="/api/files", tags=["files"])


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

    key = f"projects/{project_id}/{file.filename}"
    result = await storage_service.upload_file(
        key=key,
        file_obj=file.file,
        content_type=file.content_type or "application/octet-stream",
    )

    if not result:
        raise HTTPException(status_code=500, detail="Upload failed")

    signed_url = await storage_service.generate_signed_url(key)
    return {"key": key, "filename": file.filename, "url": signed_url}


@router.get("/download")
async def download_file(
    key: str = Query(...),
    user: PlatformUser = Depends(get_current_user),
):
    """Get a signed download URL for a file."""
    if not storage_service.is_configured():
        raise HTTPException(status_code=501, detail="File storage not configured")

    url = await storage_service.generate_signed_url(key)
    if not url:
        raise HTTPException(status_code=404, detail="File not found")

    return {"url": url}


@router.delete("")
async def delete_file(
    key: str = Query(...),
    user: PlatformUser = Depends(get_current_user),
):
    """Delete a file from storage."""
    if not storage_service.is_configured():
        raise HTTPException(status_code=501, detail="File storage not configured")

    deleted = await storage_service.delete_file(key)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")

    return {"deleted": True}

"""The editor's phone preview — build it, say where it stands, and serve it.

    POST /api/projects/{project_id}/phone-preview/build    start (or restart) the build; answers the status
    GET  /api/projects/{project_id}/phone-preview/status   where it stands: none | building | ready | failed | unavailable
    GET  /api/projects/{short_id}/phone/serve/{path}       the built screens, as a static site

The first two are the editor's and need the person's session. The third is loaded by an iframe, which cannot send the
platform's bearer token (the same reason `preview_proxy` is open): it serves only the exported screens and sample data
of a project whose short id the page already knows.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import Project
from services import phone_live, phone_preview

router = APIRouter()


async def _project(project_id: str, user: PlatformUser, db: AsyncSession) -> Project:
    # By id or short id, for a member of the project's organisation.
    from services.project_service import project_for
    return await project_for(project_id, user, db)


@router.post("/api/projects/{project_id}/phone-preview/build")
async def build(project_id: str, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=404, detail="Nothing has been built into this project yet.")
    try:
        return phone_preview.start(project.output_dir, project.short_id)
    except phone_preview.PhonePreviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/api/projects/{project_id}/phone-preview/status")
async def preview_status(project_id: str, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    if not project.output_dir:
        return {"state": "unavailable", "reason": "Nothing has been built into this project yet.",
                "servePath": phone_preview.serve_path(project.short_id)}
    return {**phone_preview.status(project.output_dir, project.short_id), "live": phone_live.status(project.short_id)}


@router.get("/api/projects/{short_id}/phone/serve/{path:path}", include_in_schema=False)
@router.get("/api/projects/{short_id}/phone/serve", include_in_schema=False)
async def serve(short_id: str, path: str = "", db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(Project.output_dir).where(Project.short_id == short_id))).first()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="No such project.")
    root = phone_preview.dist_dir(row[0]).resolve()
    if not (root / "index.html").is_file():
        raise HTTPException(status_code=404, detail="The phone preview has not been built yet.")
    target = (root / path).resolve() if path else root / "index.html"
    # Inside the built folder only; a path that leaves it, or names nothing, is the app's own page (its router decides).
    if root not in target.parents and target != root / "index.html":
        raise HTTPException(status_code=404, detail="Not found.")
    if not target.is_file():
        target = root / "index.html"
    media = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(Path(target), media_type=media, headers={"Cache-Control": "no-store"})

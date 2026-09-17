"""Handing an owner their own data back.

`services.smith.data_export` writes the file into the project's own tree; this
is the pair of endpoints that lists what has been produced and serves one
back, so the link in Smith's answer is something a browser can follow.

Deliberately shaped like ``routers/attachments.py`` and for the same reason:
the file lives on the persistent volume the rest of the pipeline uses rather
than in S3, so an export works on a laptop with no cloud config.

TWO THINGS THAT MUST NOT GO WRONG
---------------------------------
1. **A project's data is that project's.** Every request goes through
   ``get_project_with_auth`` before a path is even built, so the URL cannot
   be a way to read another tenant's customer list.

2. **The name in the URL is attacker-controlled.** ``data_export.path_of``
   matches it against the produced files rather than joining it onto a path —
   ``../../.env`` is a legal thing for a browser to ask for, and an export
   endpoint that serves it would be the most direct file-read this codebase
   could have.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import Project
from services.project_service import get_project_with_auth
from services.smith import data_export

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["exports"])

#: What a .csv and a .zip are served as. Anything else is not produced here,
#: so it is not served here either.
_MEDIA = {".csv": "text/csv; charset=utf-8", ".zip": "application/zip"}


async def _project(project_id: str, user: PlatformUser, db: AsyncSession) -> Project:
    """The project behind either spelling of its id, auth-checked.

    A project is addressed two ways in this codebase: the DB uuid, and the
    SHORT ID that names its directory under `output/` — and a Smith seam only
    ever has `output_dir`, so the link it writes into an answer carries
    whichever it knows (`services.smith.data_export.link_for`). Resolving both
    here is what `routers/output_projects._resolve_root` does for the editor's
    disk endpoints; unlike those, this one authorises, because it hands back
    the business's own records.
    """
    try:
        pid = uuid.UUID(str(project_id))
    except (ValueError, AttributeError):
        found = (await db.execute(
            select(Project).where(Project.short_id == str(project_id))
        )).scalar_one_or_none()
        if not found:
            raise HTTPException(status_code=404, detail="Project not found")
        pid = found.id
    return await get_project_with_auth(pid, user, db)


@router.get("/{project_id}/exports")
async def list_exports(
    project_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Everything this project has had exported, newest first."""
    project = await _project(project_id, user, db)
    return {"exports": data_export.produced(project.output_dir)}


@router.get("/{project_id}/exports/{name}")
async def download_export(
    project_id: str,
    name: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve one produced file as a download."""
    project = await _project(project_id, user, db)

    path = data_export.path_of(project.output_dir, name)
    if path is None:
        # 404 for a traversal attempt as well as for a name that is simply
        # gone: the answer must not say which of the two it was.
        raise HTTPException(status_code=404, detail="No such export")

    media = _MEDIA.get(path.suffix.lower())
    if media is None:
        raise HTTPException(status_code=404, detail="No such export")
    logger.info("export served: project=%s file=%s bytes=%d",
                project_id, path.name, path.stat().st_size)
    return FileResponse(path, media_type=media, filename=path.name)

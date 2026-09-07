"""Chat attachments — upload images and documents for a project's conversation.

Deliberately NOT routed through ``routers/files.py``: that endpoint requires
S3 (``storage_service.is_configured()`` is false without a bucket) and returns
501 otherwise. Chat attachments must work on a laptop with no cloud config, so
they land on the same persistent volume the rest of the pipeline already uses.

The upload is a separate round-trip from the chat turn on purpose. A 10 MB
screenshot base64-encoded inside a JSON chat body would make the message
itself huge, break the SSE turn on retry, and give the user no feedback
between "picked a file" and "the whole answer arrived". Uploading first means
the composer can show a chip immediately and the turn carries only ids.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services import chat_attachments, design_reference, project_assets
from services.chat_attachments import AttachmentError
from services.project_service import get_project_with_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["attachments"])


@router.post("/{project_id}/attachments")
async def upload_attachment(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store one attachment; return the record the composer should hold.

    The returned ``id`` is what the client sends back in
    ``ChatRequest.attachment_ids``.
    """
    await get_project_with_auth(project_id, user, db)

    data = await file.read()
    try:
        rec = chat_attachments.save_attachment(
            chat_attachments.attachments_root(),
            str(project_id),
            file.filename or "attachment",
            file.content_type or "",
            data,
        )
    except AttachmentError as exc:
        # 400, not 500 — this is a user-correctable problem (wrong file type,
        # too big) and the message is written to be shown verbatim.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("attachment saved: project=%s kind=%s bytes=%d",
                project_id, rec["kind"], rec["bytes"])
    return rec


@router.get("/{project_id}/attachments/{attachment_id}")
async def get_attachment(
    project_id: uuid.UUID,
    attachment_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve one attachment back — so the chat transcript can show the
    thumbnail the user attached, on reload and for teammates."""
    await get_project_with_auth(project_id, user, db)

    from fastapi.responses import Response

    blob = chat_attachments.read_attachment(
        chat_attachments.attachments_root(), str(project_id), attachment_id)
    if blob is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    data, media_type = blob
    return Response(content=data, media_type=media_type)


async def _project_for_ref(ref: str, user: PlatformUser, db: AsyncSession):
    """Resolve a project by DB UUID *or* by short id, then authorise.

    The visual editor addresses projects by SHORT id — `VisualEditorWorkspace`
    is handed `project.short_id` and `persistence.ts` saves through
    `/api/_debug/project-file/{short_id}/…`. Everything under `/api/projects`
    is keyed by the DB UUID. Accepting both here is what lets the editor's
    image control call this route without first doing a UUID lookup it has no
    reason to know about. Authorisation is `get_project_with_auth` either way,
    so the short-id door is not a weaker one.
    """
    from sqlalchemy import select

    from models.project import Project

    try:
        pid = uuid.UUID(str(ref))
    except (ValueError, AttributeError, TypeError):
        row = (await db.execute(
            select(Project).where(Project.short_id == str(ref))
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Project not found")
        pid = row.id
    return await get_project_with_auth(pid, user, db)


@router.post("/{project_ref}/images")
async def upload_project_image(
    project_ref: str,
    file: UploadFile = File(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store an image for the editor and return the URL to put in the schema.

    Separate from `/attachments` because the two have opposite reachability
    requirements: an attachment is fetched by our own authenticated client, so
    it may sit behind `HTTPBearer`; an image referenced by a schema is fetched
    by an `<img>` tag in two different Next.js apps that send no Authorization
    header at all. See services/project_assets.py for the full reasoning and
    for why the bytes are written to more than one directory.
    """
    project = await _project_for_ref(project_ref, user, db)

    from pathlib import Path as _Path

    from services.project_service import OUTPUT_BASE

    base = _Path(project.output_dir) if project.output_dir else None
    if base is None or not base.is_dir():
        base = OUTPUT_BASE / project.short_id
    if not base.is_dir():
        raise HTTPException(
            status_code=409,
            detail="This project has no output directory yet — generate the app "
                   "once before uploading images into it.")

    data = await file.read()
    try:
        rec = project_assets.save_project_image(
            base,
            # The URL segment is the DIRECTORY NAME, because both copies of
            # resolveProject() join it straight onto OUTPUT_ROOT. `short_id` is
            # normally the same string, but a project whose output_dir was
            # renamed would emit a URL that resolves to nothing if we trusted
            # the column instead of the path we actually wrote to.
            base.name,
            file.filename or "image",
            file.content_type or "",
            data,
        )
    except AttachmentError as exc:
        # 400, not 500 — wrong type or too big is user-correctable and the
        # message is written to be shown verbatim in the control.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"url": rec["url"], "file": rec["file"],
            "media_type": rec["media_type"], "bytes": rec["bytes"]}


class DesignReferenceRequest(BaseModel):
    """Which uploaded attachments are THIS project's visual direction."""
    attachment_ids: list[str] = Field(default_factory=list)


@router.put("/{project_id}/design-references")
async def put_design_references(
    project_id: uuid.UUID,
    body: DesignReferenceRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Designate uploaded images as the app's DESIGN REFERENCE.

    The next generation reads these, extracts palette / type scale / radius
    from them (services.brief_from_screenshot) and locks those fields in the
    design brief — the same contract the Figma path uses.

    Designation is explicit because most attached screenshots are bug
    reports, not direction; see services/design_reference.py. Sending an
    empty list clears the designation and returns the app to the normal
    brief-authoring path.
    """
    await get_project_with_auth(project_id, user, db)
    ids = design_reference.set_design_references(
        chat_attachments.attachments_root(), str(project_id), body.attachment_ids)
    return {"attachment_ids": ids}


@router.get("/{project_id}/design-references")
async def get_design_references(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The currently designated references, so the UI can show them selected."""
    await get_project_with_auth(project_id, user, db)
    return {"attachment_ids": design_reference.read_design_references(
        chat_attachments.attachments_root(), str(project_id))}

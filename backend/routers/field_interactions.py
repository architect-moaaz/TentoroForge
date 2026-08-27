"""HTTP surface for field-interaction authoring.

Backs the editor's "Interactions" panel — same validator/writer Smith
calls via ``set_field_interaction`` tool. One endpoint, no bespoke
diff logic: the resolver already produces a diff summary.

Endpoint:
    POST /api/projects/{project_id}/field-interactions
        body: {page, field, interaction?, mode?}
        → {applied, edited_paths, diff_summary, reason?, errors?, warnings?}

Auth: piggy-backs on the existing project-auth dependency used
elsewhere in this file's neighbours (get_project_output_dir).
"""

from __future__ import annotations

import uuid
from pathlib import Path as FsPath
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.auth import PlatformUser
from auth import get_current_user
from services.set_field_interaction import set_field_interaction
from services.project_service import get_project_with_auth


router = APIRouter(prefix="/api/projects", tags=["field-interactions"])


class SetInteractionRequest(BaseModel):
    page: str = Field(..., description="Page id/route/schema path (see resolver docs).")
    field: str = Field(..., description="Field name (case-sensitive; falls back to case-insensitive).")
    interaction: dict[str, Any] | None = Field(
        default=None,
        description="Interaction block. Ignored when mode='remove'.",
    )
    mode: str = Field(
        default="merge",
        description="merge | replace | remove",
    )


class SetInteractionResponse(BaseModel):
    applied: bool
    edited_paths: list[str] = []
    diff_summary: str | None = None
    reason: str | None = None
    errors: list[str] = []
    warnings: list[str] = []
    changed: bool | None = None
    field: str | None = None


@router.post(
    "/{project_id}/field-interactions",
    response_model=SetInteractionResponse,
)
async def set_interaction(
    body: SetInteractionRequest,
    project_id: uuid.UUID = Path(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SetInteractionResponse:
    """Author or update the ``interaction`` block on one form field.

    Delegates to :func:`services.set_field_interaction.set_field_interaction`
    which validates + writes atomically + mirrors to plan.json.
    """
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="project has no output_dir")
    root = FsPath(project.output_dir)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"output_dir missing: {root}")

    result = set_field_interaction(
        str(root),
        page=body.page,
        field=body.field,
        interaction=body.interaction,
        mode=body.mode,
    )
    # Never raise on user-visible errors; the client renders them inline.
    return SetInteractionResponse(**result)

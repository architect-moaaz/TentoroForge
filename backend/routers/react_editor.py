"""The visual React editor's API — pages, transactions, history, Smith.

Every mutation names the revision it was made against and returns the one it
committed; a mismatch is a 409 with the current revision, so the client
reloads rather than overwriting. Auth is the project's org membership, as
everywhere else; the source is read and written under the project's own
directory only.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.project_paths import project_root
from services.project_service import get_project_with_auth
from services.react_editor import service, smith
from services.react_editor.service import EditorError, Project

router = APIRouter(tags=["react-editor"])


def _locate(project: Any) -> Project:
    recorded = getattr(project, "output_dir", None)
    return service.locate(recorded or project_root(str(project.id)))


async def _project(project_id: uuid.UUID, user: PlatformUser, db: AsyncSession) -> Project:
    project = await get_project_with_auth(project_id, user, db)
    return _locate(project)


def _raise(exc: EditorError) -> None:
    raise HTTPException(status_code=exc.status, detail=exc.as_dict())


async def _run(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except EditorError as exc:
        _raise(exc)


# ---------------------------------------------------------------------------

class ApplyRequest(BaseModel):
    baseRevision: str
    ops: list[dict[str, Any]] = Field(default_factory=list)
    label: str = "Edit"


class RestoreRequest(BaseModel):
    revision: str
    expectedRevision: str


class SmithRequest(BaseModel):
    baseRevision: str
    prompt: str
    selection: dict[str, Any]
    scope: dict[str, Any] = Field(default_factory=dict)
    annotation: str = ""
    breakpoint: str = "desktop"
    proposalId: str | None = None
    prior: dict[str, Any] | None = None


class SmithApplyRequest(BaseModel):
    baseRevision: str
    allowScopeExpansion: bool = False


@router.get("/api/projects/{project_id}/react-editor/pages")
async def list_pages(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    svc = await _run(service.load_blueprint, project)
    return service.pages(svc.doc)


@router.get("/api/projects/{project_id}/react-editor/pages/{page_id}")
async def open_page(project_id: uuid.UUID, page_id: str, user: PlatformUser = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(service.open_page, project, page_id)


@router.post("/api/projects/{project_id}/react-editor/pages/{page_id}/apply")
async def apply_transaction(project_id: uuid.UUID, page_id: str, req: ApplyRequest,
                            user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(service.apply, project, page_id, base_revision=req.baseRevision, ops=req.ops,
                      label=req.label[:120])


@router.get("/api/projects/{project_id}/react-editor/pages/{page_id}/history")
async def page_history(project_id: uuid.UUID, page_id: str, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return {"history": await _run(service.history, project, page_id)}


@router.post("/api/projects/{project_id}/react-editor/pages/{page_id}/restore")
async def restore_revision(project_id: uuid.UUID, page_id: str, req: RestoreRequest,
                           user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(service.restore, project, page_id, revision=req.revision, expected=req.expectedRevision)


@router.get("/api/projects/{project_id}/react-editor/pages/{page_id}/check")
async def check_page(project_id: uuid.UUID, page_id: str, user: PlatformUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(service.check_page, project, page_id)


@router.post("/api/projects/{project_id}/react-editor/pages/{page_id}/smith")
async def smith_propose(project_id: uuid.UUID, page_id: str, req: SmithRequest,
                        user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(smith.propose, project, page_id, base_revision=req.baseRevision, prompt=req.prompt,
                      selection=req.selection, scope=req.scope, annotation=req.annotation,
                      breakpoint=req.breakpoint, client=smith.default_client(), proposal_id=req.proposalId,
                      prior=req.prior)


@router.get("/api/projects/{project_id}/react-editor/pages/{page_id}/smith/{proposal_id}")
async def smith_get(project_id: uuid.UUID, page_id: str, proposal_id: str,
                    user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    proposal = await _run(smith.get_proposal, project, proposal_id)
    return {k: v for k, v in proposal.items() if k not in ("viewAfter", "loadAfter")}


@router.post("/api/projects/{project_id}/react-editor/pages/{page_id}/smith/{proposal_id}/apply")
async def smith_apply(project_id: uuid.UUID, page_id: str, proposal_id: str, req: SmithApplyRequest,
                      user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(smith.apply_proposal, project, page_id, proposal_id, base_revision=req.baseRevision,
                      allow_scope_expansion=req.allowScopeExpansion)


@router.post("/api/projects/{project_id}/react-editor/pages/{page_id}/smith/{proposal_id}/discard")
async def smith_discard(project_id: uuid.UUID, page_id: str, proposal_id: str,
                        user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(smith.discard, project, proposal_id)

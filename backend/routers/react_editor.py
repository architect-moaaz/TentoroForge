"""The visual React editor's API — pages, transactions, history, Smith.

Every mutation names the revision it was made against and returns the one it
committed; a mismatch is a 409 with the current revision, so the client
reloads rather than overwriting. Auth is the project's org membership, as
everywhere else; the source is read and written under the project's own
directory only.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.project_paths import project_root
from services.project_service import get_project_with_auth
from services.react_editor import assets, jit, pages, service, smith, theme, widgets
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
    #: A whole source (view, load) to save as one revision — what a draft becomes.
    source: dict[str, str] | None = None


class DraftRequest(BaseModel):
    baseRevision: str
    ops: list[dict[str, Any]] = Field(default_factory=list)
    source: dict[str, str] | None = None


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


class WidgetRequest(BaseModel):
    spec: dict[str, Any]
    pageRevision: str | None = None


class PageRequest(BaseModel):
    spec: dict[str, Any]


class NavigationRequest(BaseModel):
    spec: dict[str, Any]


class SmithApplyRequest(BaseModel):
    baseRevision: str
    allowScopeExpansion: bool = False


@router.get("/api/projects/{project_id}/react-editor/pages")
async def list_pages(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    svc = await _run(service.load_blueprint, project)
    return service.pages(svc.doc)


@router.post("/api/projects/{project_id}/react-editor/pages")
async def create_page(project_id: uuid.UUID, req: PageRequest, user: PlatformUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """A new blank page in the Blueprint, in the menu when asked, written out."""
    project = await _project(project_id, user, db)
    return await _run(pages.create, project, req.spec)


@router.patch("/api/projects/{project_id}/react-editor/pages/{page_id}")
async def update_page(project_id: uuid.UUID, page_id: str, req: PageRequest,
                      user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(pages.update, project, page_id, req.spec)


@router.get("/api/projects/{project_id}/react-editor/pages/{page_id}/consequences")
async def page_consequences(project_id: uuid.UUID, page_id: str, user: PlatformUser = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """What removing the page takes with it — said before it is done."""
    project = await _project(project_id, user, db)
    return await _run(pages.consequences, project, page_id)


@router.delete("/api/projects/{project_id}/react-editor/pages/{page_id}")
async def delete_page(project_id: uuid.UUID, page_id: str, user: PlatformUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(pages.remove, project, page_id)


@router.get("/api/projects/{project_id}/react-editor/navigation")
async def get_navigation(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    svc = await _run(service.load_blueprint, project)
    return pages.navigation(svc.doc)


@router.put("/api/projects/{project_id}/react-editor/navigation")
async def put_navigation(project_id: uuid.UUID, req: NavigationRequest, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(pages.set_navigation, project, req.spec)


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
                      label=req.label[:120], source=req.source)


@router.post("/api/projects/{project_id}/react-editor/pages/{page_id}/draft")
async def draft_transaction(project_id: uuid.UUID, page_id: str, req: DraftRequest,
                            user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """An edit onto the page's draft — kept until the person saves."""
    project = await _project(project_id, user, db)
    return await _run(service.draft_apply, project, page_id, base_revision=req.baseRevision, ops=req.ops, source=req.source)


@router.delete("/api/projects/{project_id}/react-editor/pages/{page_id}/draft")
async def drop_draft(project_id: uuid.UUID, page_id: str,
                     user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(service.discard_draft, project, page_id)


@router.get("/api/projects/{project_id}/react-editor/vendor")
async def vendor_script(project_id: uuid.UUID, fresh: bool = Query(default=False),
                        user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The shared script every instant page runs on — fetched once per app."""
    project = await _project(project_id, user, db)
    out = await _run(jit.vendor, project, fresh=fresh)
    return {k: v for k, v in out.items() if k != "candidates"}


@router.get("/api/projects/{project_id}/react-editor/pages/{page_id}/jit")
async def render_page(project_id: uuid.UUID, page_id: str, params: str | None = Query(default=None),
                      search: str | None = Query(default=None), fresh: bool = Query(default=False),
                      draft: bool = Query(default=False),
                      user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The page bundled on demand with sample data — no dev server needed. `draft`: its unsaved edits."""
    project = await _project(project_id, user, db)

    def _dict(raw: str | None) -> dict[str, str]:
        try:
            out = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            out = {}
        return {str(k): str(v) for k, v in out.items()} if isinstance(out, dict) else {}
    return await _run(jit.build, project, page_id, params=_dict(params), search=_dict(search), fresh=fresh, draft=draft)


@router.post("/api/projects/{project_id}/react-editor/pages/{page_id}/widgets")
async def create_widget(project_id: uuid.UUID, page_id: str, req: WidgetRequest,
                        user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """A chart or number tile on the page, written through the Blueprint and checked."""
    project = await _project(project_id, user, db)
    return await _run(widgets.create, project, page_id, req.spec)


@router.patch("/api/projects/{project_id}/react-editor/widgets/{widget_id}")
async def update_widget(project_id: uuid.UUID, widget_id: str, req: WidgetRequest,
                        user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(widgets.update, project, widget_id, req.spec, page_revision=req.pageRevision)


@router.delete("/api/projects/{project_id}/react-editor/widgets/{widget_id}")
async def remove_widget(project_id: uuid.UUID, widget_id: str,
                        user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return await _run(widgets.remove, project, widget_id)


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


# ---------------------------------------------------------------------------
# Pictures: uploaded into the app's public files, served back to the canvas
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/react-editor/assets")
async def upload_asset(project_id: uuid.UUID, file: UploadFile = File(...),
                       user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    data = await file.read()
    try:
        return assets.save(project, file.filename or "", data)
    except EditorError as e:
        _raise(e)


@router.get("/api/projects/{project_id}/react-editor/assets")
async def list_assets(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    return {"assets": assets.listing(project)}


@router.get("/api/projects/{project_id}/react-editor/public/{path:path}")
async def public_asset(project_id: uuid.UUID, path: str,
                       user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    try:
        file, ctype = assets.resolve(project, path)
    except EditorError as e:
        _raise(e)
    return FileResponse(file, media_type=ctype, headers={"Cache-Control": "private, max-age=60"})


# ---------------------------------------------------------------------------
# The application's look
# ---------------------------------------------------------------------------

class ThemePatch(BaseModel):
    colors: dict[str, str] | None = None
    font: str | None = None
    headingFont: str | None = None
    baseSize: str | None = None
    radius: str | None = None
    density: str | None = None


@router.get("/api/projects/{project_id}/react-editor/theme")
async def get_theme(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    try:
        return await asyncio.to_thread(theme.get, project)
    except EditorError as e:
        _raise(e)


@router.put("/api/projects/{project_id}/react-editor/theme")
async def set_theme(project_id: uuid.UUID, body: ThemePatch,
                    user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _project(project_id, user, db)
    try:
        return await asyncio.to_thread(theme.update, project, body.model_dump(exclude_none=True))
    except EditorError as e:
        _raise(e)

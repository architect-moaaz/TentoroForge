"""Project CRUD, file browsing, conversations, and version history endpoints."""
import re

import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import OrgMember, OrgMemberRole, InviteStatus
from models.project import (
    Project,
    ProjectStatus,
    Conversation,
    AgentJob,
    Version,
)
from schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ConversationResponse,
    AgentJobResponse,
    VersionResponse,
)
from services.project_service import create_project, copy_project, get_project_with_auth
from preview import start_preview, stop_preview, get_preview_port, health_check

router = APIRouter(tags=["projects"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_org_member(
    org_id: uuid.UUID,
    user: PlatformUser,
    db: AsyncSession,
    min_role: OrgMemberRole = OrgMemberRole.member,
) -> OrgMember:
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    role_hierarchy = {OrgMemberRole.owner: 3, OrgMemberRole.admin: 2, OrgMemberRole.member: 1}
    if role_hierarchy.get(membership.role, 0) < role_hierarchy.get(min_role, 0):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return membership


# ===========================================================================
# Project CRUD
# ===========================================================================

@router.post("/api/orgs/{org_id}/projects", response_model=ProjectResponse, status_code=201)
async def create_project_endpoint(
    org_id: uuid.UUID,
    req: ProjectCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    project = await create_project(
        org_id=org_id,
        owner_id=user.id,
        name=req.name,
        description=req.description,
        db=db,
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/api/orgs/{org_id}/projects", response_model=list[ProjectResponse])
async def list_projects(
    org_id: uuid.UUID,
    status: str | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    q = select(Project).where(
        Project.org_id == org_id,
        Project.status != ProjectStatus.archived,
    )
    if status:
        q = q.where(Project.status == status)
    q = q.order_by(Project.updated_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_project_with_auth(project_id, user, db)


@router.put("/api/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    req: ProjectUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/api/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)

    # Stop preview if running
    stop_preview(project.short_id)

    # Delete output directory from disk
    if project.output_dir:
        output_path = Path(project.output_dir)
        if output_path.exists():
            shutil.rmtree(output_path)

    # Delete via raw SQL to avoid ORM lazy-loading backrefs
    # for tables that may not exist (e.g. decision_tables)
    pid = project.id
    db.expunge(project)
    await db.execute(delete(Version).where(Version.project_id == pid))
    await db.execute(delete(AgentJob).where(AgentJob.project_id == pid))
    await db.execute(delete(Conversation).where(Conversation.project_id == pid))
    await db.execute(delete(Project).where(Project.id == pid))
    await db.commit()


@router.post("/api/projects/{project_id}/copy", response_model=ProjectResponse, status_code=201)
async def copy_project_endpoint(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await get_project_with_auth(project_id, user, db)
    project = await copy_project(source=source, db=db)
    await db.commit()
    await db.refresh(project)
    return project


# ===========================================================================
# File browsing
# ===========================================================================

@router.get("/api/projects/{project_id}/files")
async def list_project_files(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    project_dir = Path(project.output_dir) if project.output_dir else None
    if not project_dir or not project_dir.exists():
        return {"project_id": str(project.id), "files": []}

    files = []
    skip_dirs = {"node_modules", ".next", ".git", "__pycache__"}
    for path in sorted(project_dir.rglob("*")):
        if path.is_file() and not any(part in skip_dirs for part in path.parts):
            # `.as_posix()` — same contract as main.py: FileTree.tsx splits
            # these on "/" to build the tree, and the path round-trips back
            # as the read-file query param.
            rel = path.relative_to(project_dir).as_posix()
            files.append(rel)
    return {"project_id": str(project.id), "files": files}


@router.get("/api/projects/{project_id}/file")
async def read_project_file(
    project_id: uuid.UUID,
    path: str = Query(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    project_dir = Path(project.output_dir) if project.output_dir else None
    if not project_dir:
        raise HTTPException(status_code=404, detail="Project directory not found")

    file_path = project_dir / path
    if not file_path.resolve().is_relative_to(project_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    content = file_path.read_text(errors="replace", encoding="utf-8")
    return {"path": path, "content": content}


@router.get("/api/projects/{project_id}/download")
async def download_project(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    project_dir = Path(project.output_dir) if project.output_dir else None
    if not project_dir or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    skip_dirs = {"node_modules", ".next", ".git"}
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(project_dir.rglob("*")):
            if path.is_file() and not any(part in skip_dirs for part in path.parts):
                arcname = str(path.relative_to(project_dir))
                zf.write(path, arcname)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={project.short_id}.zip"},
    )


# ===========================================================================
# Conversations
# ===========================================================================

@router.get("/api/projects/{project_id}/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.project_id == project.id)
        # Order by the monotonic insertion key (seq); created_at is the shared
        # transaction timestamp and can't order rows written together. COALESCE
        # keeps any pre-migration rows (seq NULL) roughly in place via created_at.
        .order_by(Conversation.seq.asc().nullslast(), Conversation.created_at.asc())
    )
    rows = result.scalars().all()
    # Control-signal messages ([APPROVE_PLAN], [SELECT_TEMPLATE:x], …) are hidden
    # in the LIVE chat but were persisted as user rows; on reload they resurfaced
    # as raw text bubbles, making the restored transcript look different/broken.
    # Filter them out of the restored history (they carry no display value).
    return [c for c in rows if not _is_control_signal(getattr(c, "content", ""))]


_SIGNAL_NAMES = frozenset({
    "APPROVE_DISCOVERY", "APPROVE_PLAN", "APPROVE", "SELECT_TEMPLATE",
    "REJECT_PLAN", "ADJUST_PLAN", "BEGIN_QUEST", "START_BUILD",
    "GENERATION_PROFILE", "SELECT_PROFILE", "APPLY_FIX", "SEED_DATA",
    "VALIDATE_REPAIR", "DONE",
})
# Matches "[SIGNAL]", "[SIGNAL:arg]", AND the JSON-payload forms the UI actually
# sends — "[APPROVE_DISCOVERY] {\"mode\":\"fast\"}", "[SELECT_TEMPLATE:id] {...}".
# The OLD check required the string to END with "]", so every JSON-payload signal
# slipped through and rendered as a raw bubble on reload (verified live).
_SIGNAL_RE = re.compile(r"^\[([A-Z_]+)(?::[^\]]*)?\]\s*(\{.*\})?\s*$", re.DOTALL)


def _is_control_signal(content: str) -> bool:
    """A machine control token the user never typed (mirrors the frontend's
    live `isSignal` skip in ChatPanel). These must not render as chat bubbles."""
    m = _SIGNAL_RE.match((content or "").strip())
    return bool(m) and m.group(1) in _SIGNAL_NAMES


# ===========================================================================
# Versions
# ===========================================================================

@router.get("/api/projects/{project_id}/versions", response_model=list[VersionResponse])
async def list_versions(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Build history — every commit in the app's git repo, augmented
    with any metadata already sitting on a matching Version row
    (agent_job_id, files_changed).

    Reconcile-on-read: only the initial full generation writes a Version
    row directly. Every subsequent edit (Smith, refine, page/rule
    editors, seams) creates a real git commit but never touched this
    table — so the sidebar used to freeze on "Initial generation". This
    endpoint now backfills any commit missing from the DB so the view
    always reflects git truth.
    """
    from datetime import datetime as _dt
    from services.git_service import git_log

    project = await get_project_with_auth(project_id, user, db)

    # 1. Existing rows keyed by commit_hash.
    result = await db.execute(
        select(Version)
        .where(Version.project_id == project.id)
        .order_by(Version.created_at.desc())
    )
    rows = list(result.scalars().all())
    by_hash: dict[str, Version] = {
        r.commit_hash: r for r in rows if r.commit_hash
    }

    # 2. Read git log (source of truth). Skip if the project has no
    #    output_dir yet — nothing to reconcile against.
    if project.output_dir:
        try:
            entries = await git_log(project.output_dir, limit=50)
        except Exception:
            entries = []

        # 3. Insert a Version for every commit we don't already have.
        new_rows: list[Version] = []
        for e in entries:
            h = e.get("hash")
            if not h or h in by_hash:
                continue
            try:
                # git log emits ISO 8601 with a space separator; normalize.
                dt = _dt.fromisoformat(str(e.get("date")).replace(" ", "T", 1))
            except Exception:
                dt = None
            v = Version(
                project_id=project.id,
                commit_hash=h,
                message=str(e.get("message") or "")[:2000],
            )
            if dt is not None:
                v.created_at = dt
            db.add(v)
            new_rows.append(v)
            by_hash[h] = v
        if new_rows:
            try:
                await db.commit()
                for v in new_rows:
                    await db.refresh(v)
            except Exception:
                await db.rollback()

        # 4. Rebuild the return list, ordered by git history (newest first),
        #    then append any DB-only rows (e.g. rows whose commit was garbage-
        #    collected) at the end.
        ordered: list[Version] = []
        used: set[uuid.UUID] = set()
        for e in entries:
            h = e.get("hash")
            if h and h in by_hash:
                v = by_hash[h]
                ordered.append(v)
                used.add(v.id)
        for r in rows:
            if r.id not in used:
                ordered.append(r)
        return ordered

    return rows


# ===========================================================================
# Preview
# ===========================================================================

@router.post("/api/projects/{project_id}/preview/start")
async def preview_start(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir or not Path(project.output_dir).exists():
        raise HTTPException(status_code=404, detail="Project directory not found")
    try:
        port = await start_preview(project.short_id, project.output_dir)
        project.preview_port = port
        await db.commit()
        return {"port": port}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/projects/{project_id}/preview/stop")
async def preview_stop(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    stopped = stop_preview(project.short_id)
    if stopped:
        project.preview_port = None
        await db.commit()
    return {"stopped": stopped}


@router.get("/api/projects/{project_id}/preview/status")
async def preview_status(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    port = get_preview_port(project.short_id)
    return {"running": port is not None, "port": port}


@router.get("/api/projects/{project_id}/preview/health")
async def preview_health(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Health check for a project's preview server."""
    project = await get_project_with_auth(project_id, user, db)
    result = await health_check(project.short_id)
    return result


# ===========================================================================
# Blueprint — manual rebuild
# ===========================================================================

@router.post("/api/projects/{project_id}/rebuild-blueprint")
async def rebuild_blueprint(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Force-rebuild the app's ``BLUEPRINT.md``.

    Returns ``{written, path, byte_size}``. Callers use this after
    external edits (e.g. someone hand-edited a schema file) to bring
    the blueprint back into agreement with what's actually on disk.
    """
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="project has no output_dir")
    if not Path(project.output_dir).is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"output_dir missing: {project.output_dir}",
        )

    from services.blueprint_writer import write_blueprint_safe
    result = write_blueprint_safe(
        project.output_dir,
        source="manual",
        summary=f"Manual rebuild by user {user.email or user.id}",
    )
    return result


@router.get("/api/projects/{project_id}/blueprint-drift")
async def blueprint_drift(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report whether the on-disk ``BLUEPRINT.md`` matches what a fresh
    rebuild would produce.

    A ``stale: true`` result means someone edited a schema / contract /
    workflow outside the four wire-in seams — the blueprint is behind
    reality. Callers use this to prompt the user to click "Rebuild
    Blueprint" (or automate the rebuild themselves).

    Returns the full drift report from
    :func:`services.blueprint_drift.check_drift`.
    """
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="project has no output_dir")
    if not Path(project.output_dir).is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"output_dir missing: {project.output_dir}",
        )

    from services.blueprint_drift import check_drift
    return check_drift(project.output_dir)

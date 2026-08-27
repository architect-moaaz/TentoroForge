"""POST /api/projects/{project_id}/publish — SSE-streamed deploy pipeline.

Also:
  GET  /api/projects/{project_id}/deployments — history for the DeploymentHistory UI
  POST /api/deployments/{deployment_id}/rollback — re-promote an earlier Vercel deployment

The publish endpoint uses SSE (text/event-stream) so the editor UI can
show live progress: snapshot → provision_db → upload → build → activate → done.
The provider yields DeployEvent objects; we format each as an SSE frame.

Spec: docs/superpowers/plans/2026-07-23-generated-app-deploy-vercel.md
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.deployment import Deployment
from models.platform_integration import PlatformIntegration
from models.project import Project
from services.deploy.provider import DeploySnapshot
from services.deploy.vercel_client import VercelClient
from services.deploy.vercel_provider import VercelDeployProvider
from services.platform_integrations_crypto import CryptoError, decrypt

log = logging.getLogger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _require_project(
    project_id: uuid.UUID, user: PlatformUser, db: AsyncSession
) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    # Owner or org-member check would go here; for MVP any authenticated
    # user with the project id can publish. Tightening left as a follow-up.
    return project


async def _collect_integrations(
    org_id: uuid.UUID, db: AsyncSession
) -> dict[str, str]:
    """Decrypt every set integration for this org into a flat dict the
    env-sync module can merge. Ciphertext failures are logged and skipped
    so a single corrupted row doesn't block the whole publish."""
    res = await db.execute(
        select(PlatformIntegration).where(PlatformIntegration.org_id == org_id)
    )
    out: dict[str, str] = {}
    for row in res.scalars().all():
        if not row.value_ct or not row.value_iv:
            continue
        try:
            out[row.key] = decrypt(row.provider, row.value_ct, row.value_iv)
        except CryptoError as e:
            log.warning(
                "skipping corrupted integration row org=%s key=%s: %s",
                row.org_id, row.key, e,
            )
    return out


# --------------------------------------------------------------------------- #
# POST /publish — SSE progress stream
# --------------------------------------------------------------------------- #


@router.post("/api/projects/{project_id}/publish")
async def publish(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Fire the deploy pipeline for this project; stream progress as SSE."""
    project = await _require_project(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(
            400,
            "project has no generated output yet — run generation first",
        )
    integrations = await _collect_integrations(project.org_id, db)
    snapshot = DeploySnapshot(
        project_id=str(project.id),
        project_slug=project.short_id,
        output_dir=project.output_dir,
        integrations=integrations,
        triggered_by=str(user.id),
    )

    provider = VercelDeployProvider(db=db)

    async def stream():
        try:
            async for evt in provider.publish(snapshot):
                payload = {
                    "stage": evt.stage,
                    "message": evt.message,
                    "progress": evt.progress,
                    "data": evt.data,
                }
                yield f"data: {json.dumps(payload)}\n\n"
        except Exception as exc:
            # Belt-and-suspenders — the provider promises to catch its
            # own errors, but if something slips through, emit a final
            # error frame so the UI doesn't hang on a dead stream.
            log.exception("publish stream leaked exception")
            err = {"stage": "error", "message": str(exc)}
            yield f"data: {json.dumps(err)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: don't buffer SSE
        },
    )


# --------------------------------------------------------------------------- #
# GET /deployments — DeploymentHistory feed
# --------------------------------------------------------------------------- #


@router.get("/api/projects/{project_id}/deployments/latest")
async def latest_deployment(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    """Newest Deployment row for this project, regardless of status.
    UI hits this when the Publish modal opens (so a returning user sees
    the last successful URL instead of a stuck spinner), and after the
    SSE stream closes (to reconcile if the network dropped the terminal
    frame). DB is source of truth — SSE is best-effort progress."""
    await _require_project(project_id, user, db)
    res = await db.execute(
        select(Deployment)
        .where(Deployment.project_id == project_id)
        .order_by(Deployment.created_at.desc())
        .limit(1)
    )
    r = res.scalars().first()
    if r is None:
        return None
    return {
        "id": str(r.id),
        "target": r.target,
        "status": r.status,
        "url": r.url,
        "error": r.error,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


@router.get("/api/projects/{project_id}/deployments")
async def list_deployments(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """History view: newest 20 deployments with status, URL, timing,
    and who triggered each one (resolved to name/email so the UI shows
    a human, not a uuid). `duration_seconds` is null while a row is
    still running."""
    await _require_project(project_id, user, db)
    res = await db.execute(
        select(Deployment)
        .where(Deployment.project_id == project_id)
        .order_by(Deployment.created_at.desc())
        .limit(20)
    )
    rows = res.scalars().all()

    # Resolve triggered_by uuids to human labels in one round-trip.
    user_ids = {r.triggered_by for r in rows if r.triggered_by is not None}
    users_by_id: dict[uuid.UUID, tuple[str, str]] = {}
    if user_ids:
        ures = await db.execute(
            select(PlatformUser).where(PlatformUser.id.in_(user_ids))
        )
        for u in ures.scalars().all():
            users_by_id[u.id] = (u.name, u.email)

    out: list[dict] = []
    for r in rows:
        # Prefer explicit started_at → finished_at; fall back to created_at
        # for older rows that never set started_at.
        start = r.started_at or r.created_at
        finish = r.finished_at
        duration_seconds: float | None = None
        if start and finish:
            duration_seconds = (finish - start).total_seconds()

        triggered_by_name: str | None = None
        triggered_by_email: str | None = None
        if r.triggered_by and r.triggered_by in users_by_id:
            triggered_by_name, triggered_by_email = users_by_id[r.triggered_by]
        elif r.triggered_by is None:
            # Rows we filled in from Smith's background task record no
            # user id; surface that transparently rather than "unknown".
            triggered_by_name = "Smith"

        out.append({
            "id": str(r.id),
            "target": r.target,
            "status": r.status,
            "url": r.url,
            "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_seconds": duration_seconds,
            "triggered_by_name": triggered_by_name,
            "triggered_by_email": triggered_by_email,
            "git_sha": r.git_sha,
            "git_sha_short": r.git_sha[:7] if r.git_sha else None,
            "git_commit_subject": r.git_commit_subject,
            "app_version": r.app_version,
            "vercel_deployment_id": r.vercel_deployment_id,
        })
    return out


# --------------------------------------------------------------------------- #
# POST /rollback — re-promote an earlier deployment
# --------------------------------------------------------------------------- #


@router.post("/api/deployments/{deployment_id}/rollback")
async def rollback(
    deployment_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    d = await db.get(Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "deployment not found")
    if d.target != "vercel" or not d.vercel_deployment_id:
        raise HTTPException(
            400, "only Vercel deployments with a deployment id can be rolled back"
        )
    if d.status != "succeeded":
        raise HTTPException(
            400, f"cannot roll back to a {d.status} deployment"
        )

    vc = VercelClient()
    try:
        await vc.promote_deployment(d.vercel_deployment_id)
    finally:
        await vc.close()

    # Record the rollback as a new Deployment row so the History shows it.
    row = Deployment(
        id=uuid.uuid4(),
        project_id=d.project_id,
        target="vercel",
        status="succeeded",
        url=d.url,
        vercel_project_id=d.vercel_project_id,
        vercel_deployment_id=d.vercel_deployment_id,
        neon_project_id=d.neon_project_id,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        triggered_by=user.id,
    )
    db.add(row)
    await db.commit()

    return {"url": d.url, "rollback_id": str(row.id)}

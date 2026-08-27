"""SV-4 — REST + SSE endpoints for Self-Verify Pass runs.

- POST /api/projects/{id}/verify          → kick off a run, return run row
- GET  /api/projects/{id}/verify           → list recent runs
- GET  /api/projects/{id}/verify/{run_id}  → single run + report
- GET  /api/projects/{id}/verify/{run_id}/stream — SSE progress

SV-4 keeps `fix=False` (diagnose-only). SV-6 flips the fix path on via
the self_verify_pass module.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import Project
from models.verify_run import VerifyRun
from services.forge_verify_client import ForgeVerifyClient, ForgeVerifyError
from services.interaction_extractor import extract_interactions

router = APIRouter(prefix="/api/projects/{project_id}/verify", tags=["verify"])


class VerifyRunRequest(BaseModel):
    target: Literal["preview", "deploy"] = "preview"
    scope: str = Field(default="*", max_length=255)
    # User-invoked runs default to fix-on-fault: the click IS the
    # authorisation. Diagnose-only is opt-in via {"fix": false}.
    fix: bool = True


class VerifyRunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    invoked_by: str
    target: str
    scope: str
    status: str
    interactions_run: int | None
    interactions_passed: int | None
    faults_count: int | None
    rounds_run: int | None
    created_at: datetime
    completed_at: datetime | None
    error: str | None

    class Config:
        from_attributes = True


async def _load_project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = (await db.execute(
        select(Project).where(Project.id == project_id),
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(404, f"project {project_id} not found")
    return project


def _preview_base_url(project: Project) -> str:
    # B-013 reverse-proxy path: /api/projects/<id>/preview/serve/
    # JV-27/A1 — env-configurable host; default "backend:6500" only
    # resolves inside docker-compose, so a local dev box needs
    # FORGE_INTERNAL_BASE_URL=http://localhost:6500 (set in start-all.sh).
    host = os.environ.get("FORGE_INTERNAL_BASE_URL", "http://localhost:6500").rstrip("/")
    return f"{host}/api/projects/{project.id}/preview/serve"


@router.post("", response_model=VerifyRunOut, status_code=202)
async def start_verify(
    project_id: uuid.UUID,
    body: VerifyRunRequest,
    db: AsyncSession = Depends(get_db),
    user: PlatformUser = Depends(get_current_user),
) -> VerifyRun:
    """User-invoked Self-Verify Pass.

    Routes through the full orchestrator so the fix loop runs
    automatically when faults are found (gated by FORGE_VERIFY_SMITH_FIX).
    Returns a pending row immediately; run_self_verify creates the real
    row inside its background task and streams progress via the SSE
    endpoint keyed on runner_run_id.
    """
    project = await _load_project(db, project_id)
    # Peek at interactions so the 422 fires synchronously before we
    # commit a placeholder row the user would see stuck at 'pending'.
    interactions = extract_interactions(project.output_dir or "", scope=body.scope)
    if not interactions:
        raise HTTPException(422, "no interactions extractable (missing contracts?)")

    row = VerifyRun(
        project_id=project.id,
        triggered_by=user.id,
        invoked_by="user_ui",
        target=body.target,
        scope=body.scope,
        status="pending",
        interactions_run=len(interactions),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    from services.self_verify_pass import run_self_verify as _sv_run
    asyncio.create_task(_sv_run(
        str(project.id),
        target=body.target,
        scope=body.scope,
        fix=body.fix,
        invoked_by="user_ui",
        triggered_by=user.id,
        existing_row_id=row.id,
    ))
    return row


@router.get("", response_model=list[VerifyRunOut])
async def list_verify(
    project_id: uuid.UUID,
    limit: int = Query(default=25, le=100),
    db: AsyncSession = Depends(get_db),
    _user: PlatformUser = Depends(get_current_user),
) -> list[VerifyRun]:
    q = (
        select(VerifyRun)
        .where(VerifyRun.project_id == project_id)
        .order_by(VerifyRun.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(q)).scalars().all())


@router.get("/events")
async def stream_verify_events(project_id: uuid.UUID):
    """JV-21 — Live SSE stream of in-flight verify events for a project.

    IMPORTANT: this route MUST be declared before ``/{run_id}`` — FastAPI
    matches routes in declaration order and ``/{run_id}``'s auth
    dependency fires before UUID validation would reject "events",
    which surfaces as a spurious 401 on this stream.

    Subscribes to the process-wide verify-events pubsub and forwards
    every event for the given project — verify_start, journey_result,
    journey_gate, journey_remediation, verify_autofix_dispatched,
    verify_end. A client opens this on chip mount, closes it on
    ``verify_end`` or unmount.

    Auth: intentionally NOT gated on ``get_current_user`` — EventSource
    cannot cleanly send auth headers cross-origin, and the existing
    project-scoped stream at ``/api/projects/{id}/events`` follows the
    same pattern. Knowing the project UUID is the gate.

    Uses ``EventSourceResponse`` from sse_starlette (same as
    ``/api/projects/{id}/events``) — it flushes headers on connect and
    sends pings, so intermediate proxies (Next.js rewrite) don't close
    the stream before the first real event arrives.
    """
    from sse_starlette.sse import EventSourceResponse
    from services.verify_events import subscribe, unsubscribe

    queue = subscribe(project_id)

    async def gen():
        # Hello event so onopen fires promptly.
        yield {"event": "verify_events_ready", "data": "{}"}
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    # EventSourceResponse's own ping keeps the socket
                    # alive; we just loop and wait for the next event.
                    continue
                kind = evt.get("event") or "message"
                data = evt.get("data") or "{}"
                yield {"event": kind, "data": data}
                # JV-26 — do NOT break on verify_end. The ChatPanel opens
                # ONE ES for the whole project view; if we close after the
                # first run, subsequent runs in the same session never
                # get their verify_end (chip stays "Verifying…" forever).
                # unsubscribe fires on client disconnect (finally: below).
        finally:
            unsubscribe(project_id, queue)

    return EventSourceResponse(gen())


@router.post("/{run_id}/cancel", status_code=202)
async def cancel_verify(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: PlatformUser = Depends(get_current_user),
) -> dict:
    """JV-27/#4 — user-invoked cancel for an in-flight verify run.

    Marks the DB row `cancelled` (self_verify_pass's `_should_cancel`
    gate re-reads status each poll so the background task exits within
    ~1.5s) and best-effort DELETE at the sidecar so Playwright stops
    spinning immediately. Publishes verify_end so the chip flips to a
    grey `Cancelled` state without waiting for the poll to unwind.
    """
    row = (await db.execute(
        select(VerifyRun).where(
            VerifyRun.id == run_id, VerifyRun.project_id == project_id,
        ),
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "run not found")
    if row.status not in ("pending", "running"):
        # Already terminal — nothing to cancel, don't churn the UI.
        return {"status": row.status, "already_terminal": True}

    row.status = "cancelled"
    row.error = "cancelled by user"
    row.completed_at = datetime.now(timezone.utc)
    row.updated_at = row.completed_at
    await db.commit()

    # Best-effort sidecar kill. Older forge-verify builds may not have
    # DELETE — log and continue; the row is cancelled either way and the
    # background pass's `_should_cancel` check will bail on the next
    # poll (≤1.5s).
    if row.runner_run_id:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=5.0) as _c:
                await _c.delete(
                    f"{_default_verify_base()}/run/{row.runner_run_id}",
                )
        except Exception as e:  # noqa: BLE001
            import logging as _logging
            _logging.getLogger(__name__).info(
                "[verify-cancel] sidecar DELETE failed for %s (%s); "
                "row is cancelled, background poll will bail on next check",
                row.runner_run_id, e,
            )

    # Fire verify_end so the chip transitions immediately — the eventual
    # verify_end from the bg task will also fire, but the payload's
    # status="cancelled" matches so the store idempotently confirms.
    try:
        from services.verify_events import publish_lifecycle
        publish_lifecycle(
            project_id, "verify_end", run_id=str(row.id),
            status="cancelled",
            interactions_run=row.interactions_run,
            interactions_passed=row.interactions_passed or 0,
            faults_count=row.faults_count or 0,
        )
    except Exception:
        pass

    return {"status": "cancelled", "run_id": str(row.id)}


def _default_verify_base() -> str:
    """Same rule as services.forge_verify_client._default_base_url."""
    return os.environ.get("FORGE_VERIFY_URL", "http://forge-verify:6600").rstrip("/")


@router.get("/{run_id}", response_model=VerifyRunOut)
async def get_verify(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: PlatformUser = Depends(get_current_user),
) -> VerifyRun:
    row = (await db.execute(
        select(VerifyRun).where(
            VerifyRun.id == run_id, VerifyRun.project_id == project_id,
        ),
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "run not found")
    return row


@router.post("/deploy/{deployment_id}", response_model=VerifyRunOut, status_code=202)
async def verify_deployment(
    project_id: uuid.UUID,
    deployment_id: uuid.UUID,
    fix: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    user: PlatformUser = Depends(get_current_user),
) -> VerifyRun:
    """SV-8 — verify a specific deployment against its Vercel URL.

    Called by the "Verify deployed app" button on the publish result +
    deployment history panel. Fix-and-report by default (spec §5.11):
    Smith fixes source, chip prompts republish. Set fix=False for
    diagnose-only.
    """
    from services.self_verify_pass import resolve_deploy_base_url

    project = await _load_project(db, project_id)
    # Resolve early so a bad deployment_id 4xxs before we commit a row.
    await resolve_deploy_base_url(db, project.id, deployment_id)
    interactions = extract_interactions(project.output_dir or "")
    if not interactions:
        raise HTTPException(422, "no interactions extractable")

    row = VerifyRun(
        project_id=project.id,
        triggered_by=user.id,
        invoked_by="user_ui",
        target="deploy",
        scope="*",
        status="pending",
        interactions_run=len(interactions),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    from services.self_verify_pass import run_self_verify as _sv_run
    asyncio.create_task(_sv_run(
        str(project.id),
        target="deploy",
        scope="*",
        fix=fix,
        invoked_by="user_ui",
        triggered_by=user.id,
        existing_row_id=row.id,
    ))
    return row


async def _drive_deploy_run(
    row_id: uuid.UUID, project: Project, interactions: list,
    base_url: str, fix: bool,
) -> None:
    """Deploy-mode driver — uses resolve_deploy_base_url output as-is."""
    from database import async_session
    from services.forge_verify_client import ForgeVerifyClient, ForgeVerifyError

    async with async_session() as db:
        row = (await db.execute(
            select(VerifyRun).where(VerifyRun.id == row_id),
        )).scalar_one()
        try:
            async with ForgeVerifyClient() as client:
                row.status = "running"
                row.updated_at = datetime.now(timezone.utc)
                await db.commit()

                runner_id = await client.run(
                    project_id=str(project.id),
                    target="deploy",
                    base_url=base_url,
                    interactions=interactions,
                )
                row.runner_run_id = runner_id
                await db.commit()

                resp = await client.poll_until_done(runner_id)
                report = resp.get("report") or {}
                row.report = report
                row.interactions_passed = report.get("interactions_passed")
                row.faults_count = len(report.get("faults") or [])
                row.status = resp.get("status") or "done"
                row.completed_at = datetime.now(timezone.utc)
                row.updated_at = row.completed_at
                await db.commit()
        except ForgeVerifyError as e:
            row.status = "failed"
            row.error = str(e)
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as e:
            row.status = "failed"
            row.error = f"{type(e).__name__}: {e}"
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()


@router.get("/{run_id}/stream")
async def stream_verify(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: PlatformUser = Depends(get_current_user),
) -> StreamingResponse:
    row = (await db.execute(
        select(VerifyRun).where(
            VerifyRun.id == run_id, VerifyRun.project_id == project_id,
        ),
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "run not found")
    if not row.runner_run_id:
        raise HTTPException(409, "run has not started on the runner yet")

    async def gen():
        async with ForgeVerifyClient() as client:
            try:
                async for ev in client.stream(row.runner_run_id):
                    import json as _json
                    yield f"event: {ev['type']}\ndata: {_json.dumps(ev['data'])}\n\n"
            except ForgeVerifyError as e:
                yield f"event: verify.failed\ndata: {{\"error\": \"{e}\"}}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── Background driver (imported by SV-5 auto trigger too) ────────────────


async def _drive_run(
    row_id: uuid.UUID, project: Project, interactions: list, target: str,
) -> None:
    """Send the run to forge-verify, poll to completion, persist the report.

    Runs in a fire-and-forget task; owns its own DB session because the
    request session that spawned it may already be closed.
    """
    from database import async_session
    from services.forge_verify_client import ForgeVerifyClient, ForgeVerifyError

    async with async_session() as db:
        row = (await db.execute(
            select(VerifyRun).where(VerifyRun.id == row_id),
        )).scalar_one()
        try:
            async with ForgeVerifyClient() as client:
                # Deploy target base URL comes from the project's latest
                # successful Deployment; SV-8 will add that lookup. For SV-4
                # we only support preview.
                if target == "deploy":
                    row.status = "failed"
                    row.error = "deploy verify not wired until SV-8"
                    row.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    return

                base_url = _preview_base_url(project)
                row.status = "running"
                row.updated_at = datetime.now(timezone.utc)
                await db.commit()

                runner_id = await client.run(
                    project_id=str(project.id),
                    target=target,
                    base_url=base_url,
                    interactions=interactions,
                )
                row.runner_run_id = runner_id
                await db.commit()

                resp = await client.poll_until_done(runner_id)
                report = resp.get("report") or {}
                row.report = report
                row.interactions_passed = report.get("interactions_passed")
                row.faults_count = len(report.get("faults") or [])
                row.status = resp.get("status") or "done"
                row.completed_at = datetime.now(timezone.utc)
                row.updated_at = row.completed_at
                await db.commit()
        except ForgeVerifyError as e:
            row.status = "failed"
            row.error = str(e)
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as e:  # broader safety net — background task must not leak
            row.status = "failed"
            row.error = f"{type(e).__name__}: {e}"
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

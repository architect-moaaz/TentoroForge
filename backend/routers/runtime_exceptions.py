"""Runtime-exception ingest + query API.

The generated app POSTs every caught runtime error to
``POST /api/projects/:id/runtime-exceptions``. The endpoint deduplicates
by content hash, persists the row, and — when a NEW exception is
recorded — schedules Smith's self-heal loop as a background task.

The POST endpoint is deliberately UNAUTHENTICATED (any caller who
knows the project id can report an error). The public surface is bounded
by rate limits in :mod:`services.self_heal` and by the fact that
persistence side-effects are limited to writing rows into a project's
own ledger.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.project import Project
from models.runtime_exception import (
    RuntimeException,
    RuntimeExceptionKind,
    RuntimeExceptionStatus,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["runtime-exceptions"])


# --------------------------------------------------------------------------- #
# Request / response shapes
# --------------------------------------------------------------------------- #

class RuntimeExceptionIn(BaseModel):
    """Body the generated app POSTs. Only `kind` and `message` are required —
    every other locator is optional so a lightweight fetch on the client can
    still report something."""
    kind: RuntimeExceptionKind = Field(
        default=RuntimeExceptionKind.unhandled,
        description="Where the error happened (workflow / api_route / …).",
    )
    message: str = Field(min_length=1, max_length=4000)
    stack: Optional[str] = Field(default=None, max_length=32_000)
    source_file: Optional[str] = Field(default=None, max_length=512)
    source_line: Optional[int] = None
    workflow_id: Optional[str] = Field(default=None, max_length=255)
    node_id: Optional[str] = Field(default=None, max_length=255)
    page_route: Optional[str] = Field(default=None, max_length=512)
    request_url: Optional[str] = Field(default=None, max_length=2048)
    request_method: Optional[str] = Field(default=None, max_length=16)
    request_body: Optional[dict] = None
    user_context: Optional[dict] = None


class RuntimeExceptionOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    message: str
    stack: Optional[str] = None
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    workflow_id: Optional[str] = None
    node_id: Optional[str] = None
    page_route: Optional[str] = None
    dedup_key: str
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    status: str
    heal_attempts: int
    resolved_at: Optional[datetime] = None
    resolution_commit: Optional[str] = None
    resolution_summary: Optional[str] = None

    class Config:
        from_attributes = True


# --------------------------------------------------------------------------- #
# Dedup
# --------------------------------------------------------------------------- #

def _compute_dedup_key(body: RuntimeExceptionIn) -> str:
    """The dedup fingerprint. Same (kind, message-first-line, source_file,
    source_line, workflow_id, node_id) → same key.

    Stack traces are excluded so a crash with an ephemeral request id in
    its stack still collapses to one row. Message is trimmed to the first
    line + first 200 chars to survive tiny formatting churn."""
    msg = (body.message or "").split("\n")[0][:200]
    parts = "\x1f".join([
        body.kind.value,
        msg,
        body.source_file or "",
        str(body.source_line or ""),
        body.workflow_id or "",
        body.node_id or "",
    ])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------------------- #
# POST — ingest
# --------------------------------------------------------------------------- #

@router.post("/api/projects/{project_id}/runtime-exceptions",
             response_model=RuntimeExceptionOut, status_code=201)
async def ingest_runtime_exception(
    project_id: uuid.UUID = Path(...),
    body: RuntimeExceptionIn = ...,
    background: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
) -> RuntimeExceptionOut:
    """Record a runtime error and (on first occurrence) schedule self-heal."""

    # Project exists?  We keep this lookup deliberately non-authenticated —
    # the generated app has no session cookie to prove itself; the shape
    # we protect against is a random caller POSTing garbage, and the dedup
    # + rate limits below cap that damage.
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")

    dedup_key = _compute_dedup_key(body)
    now = datetime.now(timezone.utc)

    # UPSERT on (project_id, dedup_key). First hit → INSERT + kick self-heal.
    # Subsequent hits → UPDATE occurrence_count + last_seen_at only.
    existing = (await db.execute(
        select(RuntimeException).where(
            RuntimeException.project_id == project_id,
            RuntimeException.dedup_key == dedup_key,
        )
    )).scalar_one_or_none()

    if existing is not None:
        existing.occurrence_count = (existing.occurrence_count or 0) + 1
        existing.last_seen_at = now
        # If the previous heal marked it `unresolvable` and we're seeing it
        # again, reset to `open` so the next window's heal budget can try
        # once more. `resolved` stays sticky — user has to re-open to retry.
        if existing.status == RuntimeExceptionStatus.unresolvable:
            existing.status = RuntimeExceptionStatus.open
        await db.commit()
        await db.refresh(existing)
        logger.info(
            "[runtime-exc] repeat #%d project=%s dedup=%s",
            existing.occurrence_count, project_id, dedup_key,
        )
        return RuntimeExceptionOut.model_validate(existing)

    row = RuntimeException(
        project_id=project_id,
        kind=body.kind,
        message=body.message,
        stack=body.stack,
        source_file=body.source_file,
        source_line=body.source_line,
        workflow_id=body.workflow_id,
        node_id=body.node_id,
        page_route=body.page_route,
        request_url=body.request_url,
        request_method=body.request_method,
        request_body=body.request_body,
        user_context=body.user_context,
        dedup_key=dedup_key,
        occurrence_count=1,
        first_seen_at=now,
        last_seen_at=now,
        status=RuntimeExceptionStatus.open,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info(
        "[runtime-exc] NEW project=%s kind=%s file=%s:%s workflow=%s node=%s",
        project_id, body.kind.value, body.source_file, body.source_line,
        body.workflow_id, body.node_id,
    )

    # Kick self-heal in the background — feature-gated so we can flip it
    # off if it misbehaves in prod.
    if _self_heal_enabled():
        if background is not None:
            background.add_task(_schedule_self_heal, project_id, row.id)
        else:
            asyncio.create_task(_schedule_self_heal(project_id, row.id))

    return RuntimeExceptionOut.model_validate(row)


# --------------------------------------------------------------------------- #
# GET — list + fetch (for the UI to render + for the tests)
# --------------------------------------------------------------------------- #

@router.get("/api/projects/{project_id}/runtime-exceptions",
            response_model=list[RuntimeExceptionOut])
async def list_runtime_exceptions(
    project_id: uuid.UUID,
    status: Optional[RuntimeExceptionStatus] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[RuntimeExceptionOut]:
    q = select(RuntimeException).where(RuntimeException.project_id == project_id)
    if status is not None:
        q = q.where(RuntimeException.status == status)
    q = q.order_by(RuntimeException.last_seen_at.desc()).limit(min(limit, 200))
    rows = (await db.execute(q)).scalars().all()
    return [RuntimeExceptionOut.model_validate(r) for r in rows]


@router.get("/api/projects/{project_id}/runtime-exceptions/{exc_id}",
            response_model=RuntimeExceptionOut)
async def get_runtime_exception(
    project_id: uuid.UUID, exc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> RuntimeExceptionOut:
    row = await db.get(RuntimeException, exc_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "not found")
    return RuntimeExceptionOut.model_validate(row)


# --------------------------------------------------------------------------- #
# Feature flag + self-heal scheduler
# --------------------------------------------------------------------------- #

def _self_heal_enabled() -> bool:
    from services.flag_profile import is_on
    return is_on("FORGE_SELF_HEAL")


async def _schedule_self_heal(project_id: uuid.UUID, exc_id: uuid.UUID) -> None:
    """Thin wrapper around services.self_heal.invoke_smith_on_exception so
    exceptions raised in the background task don't crash the request."""
    try:
        from services.self_healing import invoke_smith_on_exception
        await invoke_smith_on_exception(project_id, exc_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "[self-heal] background task failed project=%s exc=%s",
            project_id, exc_id,
        )

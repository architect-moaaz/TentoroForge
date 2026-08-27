"""MOBILE-C — endpoints for creating + reading mobile builds.

Three endpoints:

    POST /api/projects/{project_id}/mobile-builds
        Creates a MobileBuild row, kicks off the EAS build in a
        background task, returns the row immediately with status=pending.
        The task polls EAS until the build is terminal, updating the
        same row.

    GET  /api/projects/{project_id}/mobile-builds
        Lists builds for the project, newest first. Slice D's UI polls
        this to keep the history list live.

    GET  /api/projects/{project_id}/mobile-builds/{build_id}
        Fetches one row — used by the download button to check whether
        the artifact URL is ready.

Auth: the standard org-membership gate via ``get_project_with_auth``.
Gating:
  * requires the project to have a ``mobile/`` folder (Slice A output)
  * requires the project to have a deployed URL (or the shell has
    nothing to point at)
  * requires the org's EAS credentials via Slice B's loader
  * production builds additionally require Apple ASC (iOS) or Google
    Play (Android) credentials — the loader surfaces the specific gaps
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import async_session, get_db
from models.auth import PlatformUser
from models.mobile_build import MobileBuild
from models.project import Project
from services.eas_client import (
    BuildState,
    EasClientError,
    create_build,
    is_terminal,
    normalize_status,
    poll_build,
)
from services.mobile_credentials import (
    MissingRequired,
    MobileCredentials,
    load_mobile_credentials,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["mobile-builds"])

# Poll cadence — EAS builds run 10–20 min; a check every 30s gives us
# a snappy UI without hammering their API.
_POLL_INTERVAL_SEC = 30
# Cap the poller lifetime — an hour is well past the p99 build time,
# and lets an orphaned poller die gracefully if something's very wrong.
_POLL_MAX_SECONDS = 60 * 60


# --------------------------------------------------------------------------- #
# Request / response schemas                                                   #
# --------------------------------------------------------------------------- #

class CreateBuildRequest(BaseModel):
    """One build request. ``profile`` picks between installable preview
    (APK / device IPA / simulator IPA) and store-ready production
    (AAB / IPA). ``platform`` picks android or ios."""
    profile: str = Field(..., description="preview | preview-simulator | production")
    platform: str = Field(..., description="android | ios")
    deployed_url: Optional[str] = Field(
        None,
        description=(
            "URL the WebView shell will point at. If omitted, the endpoint "
            "reads the project's latest deployed URL. Required for the "
            "shell to actually load anything."
        ),
    )


class MobileBuildResponse(BaseModel):
    id: str
    project_id: str
    profile: str
    platform: str
    status: str
    eas_build_id: Optional[str] = None
    artifact_url: Optional[str] = None
    logs_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: MobileBuild) -> "MobileBuildResponse":
        return cls(
            id=str(row.id),
            project_id=str(row.project_id),
            profile=row.profile,
            platform=row.platform,
            status=row.status,
            eas_build_id=row.eas_build_id,
            artifact_url=row.artifact_url,
            logs_url=row.logs_url,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
        )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

async def _resolve_project(
    project_id: uuid.UUID,
    user: PlatformUser,
    db: AsyncSession,
) -> Project:
    from services.project_service import get_project_with_auth
    return await get_project_with_auth(project_id, user, db)


def _apple_env(creds: MobileCredentials) -> dict[str, str]:
    """Bundle Apple credentials as env vars for the eas subprocess.
    Only fields that are present get exported — EAS treats missing
    values as "use existing credentials cached in the EAS project"."""
    env: dict[str, str] = {}
    if creds.apple.team_id:
        env["APPLE_TEAM_ID"] = creds.apple.team_id
    if creds.apple.key_id:
        env["APPLE_ASC_KEY_ID"] = creds.apple.key_id
    if creds.apple.issuer_id:
        env["APPLE_ASC_ISSUER_ID"] = creds.apple.issuer_id
    if creds.apple.private_key:
        env["APPLE_ASC_PRIVATE_KEY"] = creds.apple.private_key
    return env


def _google_env(creds: MobileCredentials) -> dict[str, str]:
    env: dict[str, str] = {}
    if creds.google.service_account_json:
        env["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"] = creds.google.service_account_json
    return env


async def _run_build_and_poll(
    build_row_id: uuid.UUID,
    mobile_dir: str,
    profile: str,
    platform: str,
    creds: MobileCredentials,
    deployed_url: str,
) -> None:
    """Background task: kick off the EAS build, then poll until terminal.

    Any failure updates the DB row with a human-readable
    ``error_message`` so the UI surfaces it — the task itself never
    re-raises to avoid noisy tracebacks in the background scheduler.
    """
    try:
        state = await create_build(
            mobile_dir,
            profile=profile,
            platform=platform,
            expo_token=creds.expo_eas_token,
            deployed_url=deployed_url,
            apple_env=_apple_env(creds) if platform == "ios" else None,
            google_env=_google_env(creds) if platform == "android" else None,
        )
    except EasClientError as exc:
        await _mark_failed(build_row_id, str(exc))
        return

    await _apply_state(build_row_id, state)

    # Poll loop.
    started = asyncio.get_event_loop().time()
    while True:
        # Re-read to see if someone canceled the row externally.
        async with async_session() as sess:
            row = await sess.get(MobileBuild, build_row_id)
            if row is None or is_terminal(row.status):
                return
        if asyncio.get_event_loop().time() - started > _POLL_MAX_SECONDS:
            await _mark_failed(
                build_row_id,
                "Timed out waiting for EAS build to finish (>1h).",
            )
            return
        await asyncio.sleep(_POLL_INTERVAL_SEC)
        try:
            state = await poll_build(
                mobile_dir, state.build_id,
                expo_token=creds.expo_eas_token,
            )
        except EasClientError as exc:
            logger.warning("poll_build failed for %s: %s", state.build_id, exc)
            continue
        await _apply_state(build_row_id, state)


async def _apply_state(build_row_id: uuid.UUID, state: BuildState) -> None:
    """Persist a fresh :class:`BuildState` onto the row."""
    async with async_session() as sess:
        row = await sess.get(MobileBuild, build_row_id)
        if row is None:
            return
        db_status = normalize_status(state.status)
        row.status = db_status
        if state.build_id and not row.eas_build_id:
            row.eas_build_id = state.build_id
        if state.artifact_url:
            row.artifact_url = state.artifact_url
        if state.logs_url:
            row.logs_url = state.logs_url
        if state.error_message and not row.error_message:
            row.error_message = state.error_message
        if is_terminal(db_status) and row.completed_at is None:
            row.completed_at = datetime.now(timezone.utc)
        await sess.commit()


async def _mark_failed(build_row_id: uuid.UUID, message: str) -> None:
    async with async_session() as sess:
        row = await sess.get(MobileBuild, build_row_id)
        if row is None:
            return
        row.status = "failed"
        row.error_message = message
        row.completed_at = datetime.now(timezone.utc)
        await sess.commit()


# --------------------------------------------------------------------------- #
# Endpoints                                                                    #
# --------------------------------------------------------------------------- #

@router.post(
    "/api/projects/{project_id}/mobile-builds",
    response_model=MobileBuildResponse,
    status_code=202,
)
async def create_mobile_build(
    project_id: uuid.UUID,
    req: CreateBuildRequest,
    background: BackgroundTasks,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MobileBuildResponse:
    """Queue a new EAS build.

    Returns 202 with the created row (status=pending). The background
    task drives the row through in_progress → completed / failed.
    """
    project = await _resolve_project(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(
            status_code=400,
            detail="This project doesn't have generated output yet.",
        )
    mobile_dir = Path(project.output_dir) / "mobile"
    if not mobile_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail=(
                "This project's mobile/ scaffolding is missing. Re-run "
                "generation to produce it."
            ),
        )

    if req.platform not in ("android", "ios"):
        raise HTTPException(
            status_code=400,
            detail="platform must be 'android' or 'ios'.",
        )
    if req.profile not in ("preview", "preview-simulator", "production"):
        raise HTTPException(
            status_code=400,
            detail=(
                "profile must be 'preview', 'preview-simulator', or "
                "'production'."
            ),
        )

    # Credentials — required. Missing EAS token is a 400 with a clear
    # pointer to Settings → Integrations.
    try:
        creds = await load_mobile_credentials(project.org_id, db)
    except MissingRequired as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "missing_keys": exc.keys,
                "action": "add_credentials",
            },
        ) from exc

    # Store-submission credentials — gated per platform.
    if req.profile == "production":
        if req.platform == "ios" and not creds.can_submit_ios():
            raise HTTPException(
                status_code=400,
                detail={
                    "message": (
                        "A production iOS build requires an Apple App Store "
                        "Connect API key + team id. Add them in "
                        "Settings → Integrations."
                    ),
                    "missing_keys": creds.missing_ios_keys(),
                    "action": "add_credentials",
                },
            )
        if req.platform == "android" and not creds.can_submit_android():
            raise HTTPException(
                status_code=400,
                detail={
                    "message": (
                        "A production Android build requires a Google Play "
                        "service-account JSON. Add it in "
                        "Settings → Integrations."
                    ),
                    "missing_keys": creds.missing_android_keys(),
                    "action": "add_credentials",
                },
            )

    # Determine the URL the WebView will point at. Request wins; fall
    # back to the project's most recent successful deployment.
    deployed_url = (req.deployed_url or "").strip()
    if not deployed_url:
        deployed_url = await _latest_deployed_url(project.id) or ""
    if not deployed_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "No deployed URL is available for this project. Publish "
                "the web app first, then build the mobile shell."
            ),
        )

    row = MobileBuild(
        project_id=project.id,
        triggered_by=user.id,
        profile=req.profile,
        platform=req.platform,
        status="pending",
    )
    db.add(row)
    await db.flush()
    await db.commit()
    await db.refresh(row)

    background.add_task(
        _run_build_and_poll,
        row.id,
        str(mobile_dir),
        req.profile,
        req.platform,
        creds,
        deployed_url,
    )

    return MobileBuildResponse.from_row(row)


@router.get(
    "/api/projects/{project_id}/mobile-builds",
    response_model=list[MobileBuildResponse],
)
async def list_mobile_builds(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 25,
) -> list[MobileBuildResponse]:
    """Newest-first list of builds for the project. Used by Slice D's
    history panel."""
    await _resolve_project(project_id, user, db)
    stmt = (
        select(MobileBuild)
        .where(MobileBuild.project_id == project_id)
        .order_by(desc(MobileBuild.created_at))
        .limit(max(1, min(200, limit)))
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [MobileBuildResponse.from_row(r) for r in rows]


@router.get(
    "/api/projects/{project_id}/mobile-builds/{build_id}",
    response_model=MobileBuildResponse,
)
async def get_mobile_build(
    project_id: uuid.UUID,
    build_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MobileBuildResponse:
    """Read one build. UI polls this to detect terminal status."""
    await _resolve_project(project_id, user, db)
    row = await db.get(MobileBuild, build_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Build not found.")
    return MobileBuildResponse.from_row(row)


# --------------------------------------------------------------------------- #
# Latest deployed URL lookup                                                   #
# --------------------------------------------------------------------------- #

async def _latest_deployed_url(project_id: uuid.UUID) -> Optional[str]:
    """Find the URL of the most recent succeeded deployment. Nullable —
    a project without any deployment gets a 400 above."""
    try:
        from models.deployment import Deployment
    except Exception:  # noqa: BLE001
        return None
    async with async_session() as sess:
        stmt = (
            select(Deployment.url)
            .where(
                Deployment.project_id == project_id,
                Deployment.status == "succeeded",
                Deployment.url.isnot(None),
            )
            .order_by(desc(Deployment.created_at))
            .limit(1)
        )
        result = await sess.execute(stmt)
        return result.scalar_one_or_none()

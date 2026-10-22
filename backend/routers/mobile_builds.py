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
  * builds the project's own Expo project when it is a native app (``mobile.native.enabled``: ``native/``), else the
    ``mobile/`` shell (Slice A output). A native build is prepared and checked first (``services.native_build``): the
    phone project made current from the Blueprint, the web app's address written into it, and every reason it cannot
    work said before an EAS build is queued
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
from sqlalchemy import desc, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import async_session, get_db
from models.auth import PlatformUser
from models.mobile_build import MobileBuild
from models.project import Project
from services import native_build
from services.eas_client import (
    NO_VCS,
    BuildState,
    EasClientError,
    create_build,
    is_terminal,
    normalize_status,
    poll_build,
    submit_build,
)
from services.mobile_credentials import (
    MissingRequired,
    MobileCredentials,
    load_mobile_credentials,
)
from services.features import feature_gate


logger = logging.getLogger(__name__)

router = APIRouter(tags=["mobile-builds"], dependencies=[Depends(feature_gate("mobile_builds"))])

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
    submit_status: Optional[str] = None      # None | submitting | submitted | submit_failed
    submit_message: Optional[str] = None
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
            submit_status=row.submit_status,
            submit_message=row.submit_message,
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


def _blueprint_of(output_dir: str) -> dict:
    """The project's Blueprint, or {} for one that has none (a project from before Blueprints)."""
    try:
        from services.blueprint.service import BlueprintService
        return BlueprintService.load(output_dir=output_dir).doc
    except Exception:  # noqa: BLE001 - no Blueprint is the shell's case, not an error
        return {}


async def _run_build_and_poll(
    build_row_id: uuid.UUID,
    mobile_dir: str,
    profile: str,
    platform: str,
    creds: MobileCredentials,
    deployed_url: str,
    kind: str = "shell",
) -> None:
    """Background task: kick off the EAS build, then poll until terminal.

    ``kind`` is "native" for the project's own Expo project and "shell" for a PWA's WebView app: each is linked to an EAS
    project first (once), built from a clean staged copy, and EAS is told the folder has no git repository.

    Any failure updates the DB row with a human-readable
    ``error_message`` so the UI surfaces it — the task itself never
    re-raises to avoid noisy tracebacks in the background scheduler.
    """
    staged = None
    try:
        build_dir = mobile_dir
        if kind in ("native", "shell"):
            # Expo reads the app's plugins on this machine first, so the phone project's packages must be installed.
            await native_build.ensure_packages(Path(mobile_dir))
            await native_build.ensure_eas_project(Path(mobile_dir), creds.expo_eas_token)
            # EAS is run in a clean copy of the phone project, alone: see `native_build.stage`.
            staged = native_build.stage(Path(mobile_dir))
            build_dir = str(staged)
        state = await create_build(
            build_dir,
            profile=profile,
            platform=platform,
            expo_token=creds.expo_eas_token,
            deployed_url=deployed_url,
            apple_env=_apple_env(creds) if platform == "ios" else None,
            google_env=_google_env(creds) if platform == "android" else None,
            extra_env=NO_VCS,
        )
    except (EasClientError, native_build.NativeBuildError) as exc:
        await _mark_failed(build_row_id, str(exc))
        return
    except OSError as exc:
        await _mark_failed(build_row_id, f"The phone project could not be copied for the build: {exc}")
        return
    finally:
        if staged is not None:
            native_build.unstage(staged)

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
    # WHAT IS BUILT: a native app's own Expo project (`native/`), else the shell (`mobile/`).
    doc = _blueprint_of(project.output_dir)
    target = native_build.choose_target(project.output_dir, doc)
    if target is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "This project's mobile/ scaffolding is missing. Re-run "
                "generation to produce it."
            ),
        )
    mobile_dir = target.dir

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
        # A store build runs against the live app; a preview build against the
        # test version when there is one.
        deployed_url = await _latest_deployed_url(
            project.id, environment="production" if req.profile == "production" else None) or ""
    if not deployed_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "No deployed URL is available for this project. Publish "
                "the web app first, then build the mobile shell."
            ),
        )

    # A PWA'S PHONE APP IS THE SHELL: made now if the application has none, with the address it opens.
    if target.kind == "shell":
        try:
            native_build.prepare_shell(project.output_dir, doc, deployed_url)
        except native_build.NativeBuildError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "problems": [str(exc)], "action": "fix_app"}) from exc

    # A NATIVE BUILD IS PREPARED AND CHECKED BEFORE IT IS QUEUED: the phone project made current, the web app's address
    # written into it, and every reason it cannot work said now, not 15 minutes into an EAS build.
    if target.kind == "native":
        try:
            native_build.prepare(project.output_dir, doc, deployed_url)
        except native_build.NativeBuildError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "problems": [str(exc)], "action": "fix_app"}) from exc
        report = native_build.preflight(mobile_dir, doc, profile=req.profile, platform=req.platform, deployed_url=deployed_url)
        if not report.ok:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "The phone app cannot be built yet: " + " ".join(report.problems),
                    "problems": report.problems,
                    "warnings": report.warnings,
                    "action": "fix_app",
                },
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
        target.kind,
    )

    return MobileBuildResponse.from_row(row)


async def _mark_submit(build_row_id: uuid.UUID, status: str, message: str) -> None:
    async with async_session() as sess:
        row = await sess.get(MobileBuild, build_row_id)
        if row is None:
            return
        row.submit_status = status
        row.submit_message = message
        await sess.commit()


async def _run_submit(build_row_id: uuid.UUID, native_dir: str, eas_build_id: str, platform: str, creds: MobileCredentials) -> None:
    """Background task: send the finished build to its store from a staged copy that holds the keys, then say how it went.
    Never re-raises: the outcome is written on the row for the panel to show."""
    staged = None
    try:
        staged = native_build.stage(Path(native_dir))
        native_build.write_submit_keys(
            staged, platform,
            google_json=creds.google.service_account_json or "", apple=creds.apple,
        )
        said = await submit_build(
            str(staged), build_id=eas_build_id, platform=platform,
            expo_token=creds.expo_eas_token, extra_env=NO_VCS,
        )
    except (EasClientError, native_build.NativeBuildError, OSError) as exc:
        await _mark_submit(build_row_id, "submit_failed", str(exc))
        return
    finally:
        if staged is not None:
            native_build.unstage(staged)
    where = "Google Play (Internal testing)" if platform == "android" else "App Store Connect (TestFlight)"
    await _mark_submit(build_row_id, "submitted", f"Sent to {where}. {said}".strip())


@router.post(
    "/api/projects/{project_id}/mobile-builds/{build_id}/submit",
    response_model=MobileBuildResponse,
    status_code=202,
)
async def submit_mobile_build(
    project_id: uuid.UUID,
    build_id: uuid.UUID,
    background: BackgroundTasks,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MobileBuildResponse:
    """Send a finished production build to its store (`eas submit`). Returns at once; the row's ``submit_status`` goes
    submitting → submitted / submit_failed."""
    project = await _resolve_project(project_id, user, db)
    row = await db.get(MobileBuild, build_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Build not found.")
    if row.profile != "production":
        raise HTTPException(status_code=400, detail="Only a store build (production) can be sent to a store; a preview build is for testing.")
    if row.status != "completed" or not row.eas_build_id:
        raise HTTPException(status_code=400, detail="This build has not finished, so there is nothing to submit yet.")
    if row.submit_status in ("submitting", "submitted"):
        raise HTTPException(status_code=409, detail=(
            "This build is already being submitted."
            if row.submit_status == "submitting"
            else "This build has already been sent to its store."))
    doc = _blueprint_of(project.output_dir or "")
    target = native_build.choose_target(project.output_dir or "", doc)
    if target is None or target.kind != "native":
        raise HTTPException(status_code=400, detail="Submitting to a store is available for a native app's own phone project.")
    try:
        creds = await load_mobile_credentials(project.org_id, db)
    except MissingRequired as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "missing_keys": exc.keys, "action": "add_credentials"}) from exc
    if row.platform == "android":
        missing = creds.missing_android_keys()
        gone = "A Google Play service-account key is needed to submit."
    else:
        missing = creds.missing_ios_keys() + ([] if creds.apple.app_id else ["APPLE_ASC_APP_ID"])
        gone = "Apple App Store Connect keys and the app's App Store Connect id are needed to submit."
    if missing:
        raise HTTPException(status_code=400, detail={"message": gone, "missing_keys": missing, "action": "add_credentials"})
    # Claim the submit atomically: only a build that is not already in flight or sent (submit_status unset, or a prior
    # attempt that failed) moves to "submitting". Two requests that race past the check above, or a double click, cannot
    # both send the same build to the store — the second claims nothing and is told so.
    claimed = await db.execute(
        update(MobileBuild)
        .where(MobileBuild.id == row.id,
               or_(MobileBuild.submit_status.is_(None), MobileBuild.submit_status == "submit_failed"))
        .values(submit_status="submitting", submit_message=None))
    await db.commit()
    if claimed.rowcount == 0:
        raise HTTPException(status_code=409, detail="This build has already been sent to its store, or is being sent now.")
    await db.refresh(row)
    background.add_task(_run_submit, row.id, str(target.dir), row.eas_build_id, row.platform, creds)
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

async def _latest_deployed_url(project_id: uuid.UUID, environment: Optional[str] = None) -> Optional[str]:
    """Find the URL of the most recent succeeded deployment — of that side
    when `environment` is given; otherwise the test version when one is
    live, else production. Nullable — a project without any deployment
    gets a 400 above."""
    if environment is None:
        return (await _latest_deployed_url(project_id, "test")
                or await _latest_deployed_url(project_id, "production"))
    try:
        from models.deployment import LIVE_STATUSES, Deployment
    except Exception:  # noqa: BLE001
        return None
    async with async_session() as sess:
        stmt = (
            select(Deployment.url)
            .where(
                Deployment.project_id == project_id,
                Deployment.environment == environment,
                Deployment.status.in_(LIVE_STATUSES),
                Deployment.url.isnot(None),
            )
            .order_by(desc(Deployment.created_at))
            .limit(1)
        )
        result = await sess.execute(stmt)
        return result.scalar_one_or_none()

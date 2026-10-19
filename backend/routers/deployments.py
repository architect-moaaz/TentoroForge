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
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.deployment import LIVE_STATUSES, Deployment
from models.platform_integration import PlatformIntegration
from models.project import Project
from services.deploy.provider import DeploySnapshot
from services.deploy.vercel_client import VercelClient
from services.deploy.vercel_provider import VercelDeployProvider
from services.platform_integrations_crypto import CryptoError, decrypt
from services.features import feature_gate

log = logging.getLogger(__name__)
router = APIRouter()


class PublishRequest(BaseModel):
    """What Publish is asked to do. Everything is optional: no body publishes
    to the side the app's switch is on, as the button always did."""
    #: "test" or "production"; the app's switch when left out.
    environment: str | None = None
    #: Send exactly what Test runs to production.
    promote: bool = False
    #: Test only: start the test data again from demo data first.
    reset_test_data: bool = False


class PublishTarget(BaseModel):
    target: str


def _side_view(r: Deployment | None) -> dict | None:
    if r is None:
        return None
    return {"id": str(r.id), "status": r.status, "url": r.url, "deployment_url": r.deployment_url,
            "environment": r.environment, "app_version": r.app_version, "source_digest": r.source_digest,
            "promoted_from": str(r.promoted_from) if r.promoted_from else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None}


async def _latest_live(db: AsyncSession, project_id: uuid.UUID, environment: str) -> Deployment | None:
    res = await db.execute(
        select(Deployment)
        .where(Deployment.project_id == project_id, Deployment.environment == environment,
               Deployment.status.in_(LIVE_STATUSES))
        .order_by(Deployment.created_at.desc()).limit(1))
    return res.scalars().first()


async def _member_emails(org_id: uuid.UUID, db: AsyncSession) -> tuple[str, ...]:
    """Who the test side may email: the organisation's accepted members."""
    from models.org import InviteStatus, OrgMember
    res = await db.execute(
        select(PlatformUser.email).join(OrgMember, OrgMember.user_id == PlatformUser.id)
        .where(OrgMember.org_id == org_id, OrgMember.invite_status == InviteStatus.accepted))
    return tuple(sorted({str(e).lower() for (e,) in res.all() if e}))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _deploy_app_dir(output_dir: str) -> str:
    """The application directory to ship — `<output>/app` for a Blueprint app.

    The Blueprint engine projects the application into `<output>/app` (beside
    `.forge` and `contracts`), while earlier generators wrote it at the output
    root. Deploying the root then fails vendor refresh with `package.json
    missing: <output>/package.json`, because package.json is one level down.
    Prefer the `app/` subdir when it holds the app — the same rule
    resolveProject.ts and the preview follow.
    """
    nested = Path(output_dir) / "app"
    if (nested / "package.json").exists() or (nested / "src" / "schemas").is_dir():
        return str(nested)
    return output_dir


async def _require_project(
    project_id: uuid.UUID, user: PlatformUser, db: AsyncSession
) -> Project:
    # A PUBLISH IS THE ORGANISATION'S. Any signed-in person who knew a
    # project's id could publish it; now only a member of its organisation
    # can, and not while the organisation is blocked.
    from services.project_service import get_project_with_auth
    return await get_project_with_auth(project_id, user, db)


async def _collect_integrations(
    org_id: uuid.UUID, db: AsyncSession
) -> dict[str, str]:
    """Decrypt every set integration for this org into a flat dict the
    env-sync module can merge. Ciphertext failures are logged and skipped
    so a single corrupted row doesn't block the whole publish.

    THIS IS WHERE A CONNECTED SERVICE'S CREDENTIAL ENTERS A PUBLISHED APP.
    The Blueprint records the service and the NAMES of its variables
    (`services.smith.email_connect`); the owner sets the value once, here, on
    the platform, encrypted per organisation; and this publish is what puts it
    in the deployment's environment, where the app's `getSecret` reads it. No
    credential is ever typed into a conversation, written into the Blueprint
    or committed to the generated app — so a connection that is live in
    production and one that is only declared differ by exactly one row in this
    table, which is why the app asks for presence by name and says so when it
    is missing.
    """
    res = await db.execute(
        select(PlatformIntegration).where(PlatformIntegration.org_id == org_id)
    )
    from services.node_config_specs import platform_only_keys
    platform_only = platform_only_keys()
    out: dict[str, str] = {}
    for row in res.scalars().all():
        if not row.value_ct or not row.value_iv or row.key in platform_only:
            continue
        try:
            out[row.key] = decrypt(row.provider, row.value_ct, row.value_iv)
        except CryptoError as e:
            log.warning(
                "skipping corrupted integration row org=%s key=%s: %s",
                row.org_id, row.key, e,
            )
    # THE ORGANISATION'S MCP SERVERS TRAVEL WITH IT. A published app's
    # `mcp_tool_call` resolves a server from MCP_SERVER_* in its environment,
    # and nothing put them there, so a Firecrawl step that ran nowhere else
    # could not run published either.
    from models.platform_mcp_server import PlatformMcpServer
    from services.env_writer import mcp_env
    mcp = await db.execute(select(PlatformMcpServer).where(
        PlatformMcpServer.org_id == org_id, PlatformMcpServer.enabled.is_(True)))
    out.update(mcp_env(mcp.scalars().all()))
    return out


# --------------------------------------------------------------------------- #
# POST /publish — SSE progress stream
# --------------------------------------------------------------------------- #


@router.post("/api/projects/{project_id}/publish", dependencies=[Depends(feature_gate("publish"))])
async def publish(
    project_id: uuid.UUID,
    body: PublishRequest | None = Body(default=None),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Fire the deploy pipeline for this project; stream progress as SSE.
    It goes to the side the request names, else the side the app's switch is
    on (`services.deploy.environments`); `promote` sends exactly what Test
    runs to production."""
    from services.deploy import environments as envs
    project = await _require_project(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(
            400,
            "project has no generated output yet — run generation first",
        )
    req = body or PublishRequest()
    try:
        side = envs.normalise(req.environment or project.publish_target or envs.PRODUCTION)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    promote_from = None
    if req.promote:
        tested = await _latest_live(db, project.id, envs.TEST)
        if tested is None:
            raise HTTPException(400, "There is no live test version to promote. Publish to Test first.")
        side, promote_from = envs.PRODUCTION, str(tested.id)
    integrations = await _collect_integrations(project.org_id, db)
    snapshot = DeploySnapshot(
        project_id=str(project.id),
        project_slug=project.short_id,
        output_dir=_deploy_app_dir(project.output_dir),
        integrations=integrations,
        triggered_by=str(user.id),
        environment=side,
        promote_from=promote_from,
        reset_test_data=bool(req.reset_test_data and side == envs.TEST),
        test_recipients=await _member_emails(project.org_id, db) if side == envs.TEST else (),
    )

    # THE PUBLISH IS THE SERVER'S TO FINISH. It runs on its own task and its
    # own session (the request's closes with the response); this response only
    # relays its progress, so a dialog closed half-way no longer cancels the
    # publish and strands its row at "snapshot" (`services.deploy.runs`).
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from services.deploy import runs
    queue = runs.start(lambda own: VercelDeployProvider(db=own).publish(snapshot),
                       async_sessionmaker(db.bind, expire_on_commit=False))

    return StreamingResponse(
        runs.frames(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: don't buffer SSE
        },
    )


# --------------------------------------------------------------------------- #
# GET /deployments — DeploymentHistory feed
# --------------------------------------------------------------------------- #


@router.get("/api/projects/{project_id}/check")
async def app_check_state(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """What the build found when it used the application, for the Publish
    dialog to say before anything goes live: pages and processes that still do
    not work, by name (`app_check.publish_note`). A warning, never a gate."""
    project = await _require_project(project_id, user, db)
    if not project.output_dir:
        return {"checked": False, "pages": 0, "working": 0, "failing": [], "processes": []}
    from services.blueprint.app_check import publish_note
    return publish_note(str(project.output_dir))


@router.get("/api/projects/{project_id}/deployments/latest")
async def latest_deployment(
    project_id: uuid.UUID,
    environment: str | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    """Newest Deployment row for this project, regardless of status.
    UI hits this when the Publish modal opens (so a returning user sees
    the last successful URL instead of a stuck spinner), and after the
    SSE stream closes (to reconcile if the network dropped the terminal
    frame). DB is source of truth — SSE is best-effort progress."""
    await _require_project(project_id, user, db)
    from services.deploy.runs import close_stale
    await close_stale(db, project_id)
    conditions = [Deployment.project_id == project_id]
    if environment:
        conditions.append(Deployment.environment == environment)
    res = await db.execute(
        select(Deployment)
        .where(*conditions)
        .order_by(Deployment.created_at.desc())
        .limit(1)
    )
    r = res.scalars().first()
    if r is None:
        return None
    return {
        "id": str(r.id),
        "environment": r.environment,
        "target": r.target,
        "status": r.status,
        "url": r.url,
        "deployment_url": r.deployment_url,
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
    from services.deploy.runs import close_stale
    await close_stale(db, project_id)
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
            "deployment_url": r.deployment_url,
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
            "environment": r.environment,
            "promoted_from": str(r.promoted_from) if r.promoted_from else None,
        })
    return out


# --------------------------------------------------------------------------- #
# Test and Production: the switch and where each side stands
# --------------------------------------------------------------------------- #


@router.get("/api/projects/{project_id}/publish-status")
async def publish_status(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Where Publish sends the app, what each side runs, and whether the app
    has changed since it was tried on Test (`untested_changes`) or Test runs a
    newer version than production (`test_ahead`)."""
    from services.deploy import environments as envs
    from services.deploy.runs import close_stale
    project = await _require_project(project_id, user, db)
    await close_stale(db, project.id)
    test = await _latest_live(db, project.id, envs.TEST)
    prod = await _latest_live(db, project.id, envs.PRODUCTION)
    current = None
    if project.output_dir:
        try:
            from services.deploy.snapshot import snapshot_digest
            current = snapshot_digest(Path(_deploy_app_dir(project.output_dir)))
        except Exception:  # noqa: BLE001 — the comparison is a hint
            current = None
    untested = bool(current and (test is None or test.source_digest != current))
    test_ahead = bool(test and (prod is None or (test.source_digest and test.source_digest != prod.source_digest
                                                 and test.created_at > prod.created_at)))
    from services.deploy.domains import live_address
    from services.deploy.vercel_provider import _slugify
    # THE LIVE APP'S ADDRESS is its main one (own domain, else apps.tentoro.ai)
    # once that answers; until then the Vercel address it was published at.
    production_address = (live_address(project.output_dir, project.short_id) or prod.url) if prod else None
    return {"target": project.publish_target or envs.PRODUCTION,
            "test": _side_view(test), "production": _side_view(prod),
            "test_address": f"https://{envs.test_alias(_slugify(project.short_id))}",
            "production_address": production_address,
            "untested_changes": untested, "test_ahead": test_ahead}


@router.put("/api/projects/{project_id}/publish-target", dependencies=[Depends(feature_gate("publish"))])
async def set_publish_target(
    project_id: uuid.UUID,
    body: PublishTarget,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Move the app's switch: Publish goes to Test or to Production from now."""
    from services.deploy import environments as envs
    project = await _require_project(project_id, user, db)
    try:
        project.publish_target = envs.normalise(body.target)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {"target": project.publish_target}


# --------------------------------------------------------------------------- #
# POST /rollback — re-promote an earlier deployment
# --------------------------------------------------------------------------- #


@router.post("/api/deployments/{deployment_id}/rollback", dependencies=[Depends(feature_gate("publish"))])
async def rollback(
    deployment_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from services.deploy import environments as envs
    d = await db.get(Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "deployment not found")
    # A ROLLBACK IS THE ORGANISATION'S, like a publish: only its members.
    project = await _require_project(d.project_id, user, db)
    if d.target != "vercel" or not d.vercel_deployment_id:
        raise HTTPException(
            400, "only Vercel deployments with a deployment id can be rolled back"
        )
    if d.status not in LIVE_STATUSES:
        raise HTTPException(
            400, f"cannot roll back to a {d.status} deployment"
        )

    vc = VercelClient()
    try:
        if d.environment == envs.TEST:
            # The test side's fixed address goes back to that build; production is not touched.
            from services.deploy.vercel_provider import _slugify
            await vc.alias_deployment(d.vercel_deployment_id, envs.test_alias(_slugify(project.short_id)))
        else:
            await vc.promote_deployment(d.vercel_deployment_id)
    finally:
        await vc.close()

    # Record the rollback as a new Deployment row so the History shows it.
    row = Deployment(
        id=uuid.uuid4(),
        project_id=d.project_id,
        target="vercel",
        status="succeeded",
        # The app's address serves this build again; the build's own address is its own.
        url=d.url,
        deployment_url=d.deployment_url or d.url,
        vercel_project_id=d.vercel_project_id,
        vercel_deployment_id=d.vercel_deployment_id,
        neon_project_id=d.neon_project_id,
        environment=d.environment,
        source_digest=d.source_digest,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        triggered_by=user.id,
    )
    db.add(row)
    await db.commit()

    return {"url": d.url, "deployment_url": d.deployment_url or d.url, "rollback_id": str(row.id)}

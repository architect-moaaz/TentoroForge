"""A PWA's phone app is built once, when the app is first published, so the person is offered the install without asking.

Choosing PWA means the website is what people install; its phone app is the WebView shell that opens it, and the shell
needs the published address to open. So the moment a PWA reaches production, its Android app is queued: the same build
the Publish dialog's button queues, started for the person. It is built ONCE per address: the shell loads the live site,
so a republish changes nothing in the app and must not spend a build (Expo's free plan has a monthly allowance).

Nothing here may fail a publish: the app is live whatever this does, and every reason it does not start is logged."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import desc, select

logger = logging.getLogger(__name__)

#: Tasks the loop must not forget while a build runs in the background.
_RUNNING: set[asyncio.Task] = set()


def decide(surface: Optional[str], url: str, builds: Sequence[tuple[str, str]], built_for: str) -> str:
    """"" when the phone app should be built now, else the reason it should not.

    `builds` is `(profile, status)` of this application's Android builds, newest first; `built_for` the address the shell
    on disk was last written for."""
    from services.native_build import SHELL_SURFACES

    if surface not in SHELL_SURFACES:
        return "this application's phone app is not the WebView shell"
    if not str(url or "").strip():
        return "there is no published address for the app to open yet"
    mine = [status for profile, status in builds if profile == "preview"]
    if any(status in ("pending", "in_progress") for status in mine):
        return "its phone app is already being built"
    if "completed" in mine and built_for.rstrip("/") == url.rstrip("/"):
        return "its phone app is already built for this address"
    return ""


def _shell_address(output_dir: str) -> str:
    try:
        data = json.loads((Path(output_dir) / "mobile" / "app.json").read_text(encoding="utf-8"))
        return str(((data.get("expo") or {}).get("extra") or {}).get("appUrl") or "")
    except (OSError, ValueError):
        return ""


async def start_phone_app(project_id: uuid.UUID, user_id: Optional[uuid.UUID]) -> Optional[str]:
    """After a production publish: queue the Android app of a PWA. The build row's id, or None when nothing was started.
    Never raises."""
    try:
        return await _start(project_id, user_id)
    except Exception:  # noqa: BLE001 - a publish is never failed by the phone app
        logger.exception("[autobuild] the phone app could not be started for %s", project_id)
        return None


async def _start(project_id: uuid.UUID, user_id: Optional[uuid.UUID]) -> Optional[str]:
    from database import async_session
    from models.mobile_build import MobileBuild
    from models.project import Project
    from routers import mobile_builds as mb
    from services import features, native_build
    from services.mobile_credentials import MissingRequired, load_mobile_credentials

    async with async_session() as db:
        project = await db.get(Project, project_id)
        if project is None or not project.output_dir:
            return None
        doc = mb._blueprint_of(project.output_dir)
        surface = str(((doc.get("mobile") or {}).get("surface")) or "") or None
        if surface not in native_build.SHELL_SURFACES:
            return None
        if not await features.is_enabled(db, project.org_id, "mobile_builds"):
            logger.info("[autobuild] %s: mobile builds are off for this organisation", project.short_id)
            return None
        try:
            creds = await load_mobile_credentials(project.org_id, db)
        except MissingRequired:
            logger.info("[autobuild] %s: no Expo token is saved, so there is nothing to build with", project.short_id)
            return None
        rows = (await db.execute(
            select(MobileBuild.profile, MobileBuild.status)
            .where(MobileBuild.project_id == project.id, MobileBuild.platform == "android")
            .order_by(desc(MobileBuild.created_at)).limit(10))).all()
    url = await mb._latest_deployed_url(project.id) or ""
    why_not = decide(surface, url, [(r[0], r[1]) for r in rows], _shell_address(project.output_dir))
    if why_not:
        logger.info("[autobuild] %s: not building: %s", project.short_id, why_not)
        return None
    try:
        shell = native_build.prepare_shell(project.output_dir, doc, url)
    except native_build.NativeBuildError as exc:
        logger.warning("[autobuild] %s: the phone app could not be written: %s", project.short_id, exc)
        return None
    async with async_session() as db:
        row = MobileBuild(project_id=project.id, triggered_by=user_id, profile="preview", platform="android", status="pending")
        db.add(row)
        await db.commit()
        await db.refresh(row)
        row_id = row.id
    task = asyncio.create_task(mb._run_build_and_poll(row_id, str(shell), "preview", "android", creds, url, "shell"))
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    logger.info("[autobuild] %s: the Android app is being built (%s)", project.short_id, str(row_id)[:8])
    return str(row_id)

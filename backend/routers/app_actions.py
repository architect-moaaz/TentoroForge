"""Post-generation app actions the chat offers: seed the DB (+ admin login) and
run the validate→repair loop. Both boot/exercise the generated app, so they run
the work in a thread and stream status → complete over SSE.
"""
import asyncio
import subprocess
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.project_service import get_project_with_auth
from sse_helpers import sse_event

router = APIRouter()


async def _app_dir(project_id: uuid.UUID, user, db) -> str:
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no output directory")
    return project.output_dir


@router.post("/api/projects/{project_id}/app/seed")
async def seed_app(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Boot the DB + run seed.ts (via start.sh --seed-only); return the admin login."""
    out = await _app_dir(project_id, user, db)

    async def stream():
        yield sse_event("status", {"message": "Seeding the database…"})
        try:
            proc = await asyncio.to_thread(
                lambda: subprocess.run(["bash", "start.sh", "--seed-only"],
                                       cwd=out, capture_output=True, text=True, timeout=600))
            from services.post_gen_actions import admin_credentials, post_seed_actions
            ok = "SEEDED_OK" in (proc.stdout or "")
            creds = admin_credentials(out)
            summary = (
                f"🌱 **Database seeded.** Log in with **{creds['email']}** / **{creds['password']}**."
                if ok else
                "⚠️ Seeding finished with warnings — check the app logs."
            )
            yield sse_event("message", {"text": summary})
            yield sse_event("complete", {
                "ok": ok,
                "credentials": creds,
                "actions": post_seed_actions(),
                "log": (proc.stdout or "")[-1200:],
            })
        except Exception as e:  # noqa: BLE001
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(stream())


@router.post("/api/projects/{project_id}/app/validate")
async def validate_app(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Boot the app, click-through-crawl it, repair the findings, re-validate."""
    out = await _app_dir(project_id, user, db)

    async def stream():
        yield sse_event("status", {"message": "Booting app + running click-through validation…"})
        try:
            from services.validate_repair_loop import run_validate_repair
            report = await asyncio.to_thread(lambda: run_validate_repair(out))
            from services.post_gen_actions import post_seed_actions
            rounds = len(report.get("rounds", []))
            remaining = (report.get("remaining") or {}).get("total", 0)
            if report.get("clean"):
                summary = "✅ **Validation passed** — every page loaded and every button worked."
            elif remaining:
                summary = (f"🔧 Ran {rounds} validate→repair round(s) and auto-fixed what I could. "
                           f"**{remaining} issue(s) still need a look** — see the report.")
            else:
                summary = f"✅ **Validated and repaired** across {rounds} round(s) — the app is clean now."
            yield sse_event("message", {"text": summary})
            yield sse_event("complete", {"report": report, "actions": post_seed_actions()})
        except Exception as e:  # noqa: BLE001
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(stream())

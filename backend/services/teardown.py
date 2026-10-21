"""Taking an application, or a whole organisation, off the platform for good.

One teardown, used by a member deleting their app, by the cockpit deleting
any app, and by the cockpit purging a removed organisation. A project used to
be deleted by a raw-SQL delete and an `rmtree`: its database on the apps
server and its Neon project stayed behind, nameless. Every step here is tried
on its own and reported — what was removed, and what could not be — so a
Neon call that fails does not keep the folder, and a second run finds
nothing to do rather than failing. A Vercel project is not touched: the
Vercel client has no delete, and it stays manual as it always was.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deployment import Deployment
from models.project import AgentJob, Conversation, Project, Version

logger = logging.getLogger(__name__)


def _report() -> dict[str, list]:
    return {"removed": [], "failed": []}


def _step(report: dict[str, list], step: str, target: str, fn) -> None:
    try:
        fn()
        report["removed"].append({"step": step, "target": target})
    except Exception as exc:  # noqa: BLE001 — said, and the rest goes on
        logger.warning("[teardown] %s %s failed: %s", step, target, exc)
        report["failed"].append({"step": step, "target": target, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})


async def _delete_neon_projects(db: AsyncSession, project_id: Any, report: dict[str, list]) -> None:
    rows = (await db.execute(
        select(Deployment.neon_project_id).where(Deployment.project_id == project_id,
                                                  Deployment.neon_project_id.is_not(None)))).all()
    ids = sorted({r[0] for r in rows if r[0]})
    if not ids:
        return
    if not os.environ.get("NEON_API_KEY"):
        for nid in ids:
            report["failed"].append({"step": "neon", "target": nid, "error": "NEON_API_KEY is not set"})
        return
    from services.deploy.neon_client import NeonClient
    client = NeonClient()
    try:
        for nid in ids:
            try:
                await client.delete_project(nid)
                report["removed"].append({"step": "neon", "target": nid})
            except Exception as exc:  # noqa: BLE001
                logger.warning("[teardown] neon %s failed: %s", nid, exc)
                report["failed"].append({"step": "neon", "target": nid, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def _detach_domains(output_dir: str, short_id: str, report: dict[str, list]) -> None:
    """The app's addresses let go of in Vercel, so the owner (or another app)
    can use them again (`services.deploy.domains.detach_all`)."""
    if not output_dir or not os.environ.get("VERCEL_TOKEN"):
        return
    from services.deploy.domains import detach_all, vercel_project_name
    from services.deploy.vercel_client import VercelClient
    client = VercelClient()
    try:
        for name in await detach_all(output_dir, client, vercel_project_name(short_id)):
            report["removed"].append({"step": "domain", "target": name})
    except Exception as exc:  # noqa: BLE001 — deleting the app never waits on Vercel
        logger.warning("[teardown] domains of %s failed: %s", short_id, exc)
        report["failed"].append({"step": "domain", "target": short_id, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def remove_project(db: AsyncSession, project: Project, *, report: dict[str, list] | None = None) -> dict[str, list]:
    """Everything the project has, gone: its preview, its addresses in Vercel,
    its database on the apps server, its Neon projects, its folder, its rows.
    Commits."""
    report = report if report is not None else _report()
    short_id = str(project.short_id)
    output_dir = str(project.output_dir or "")
    # ITS SPEND STAYS ITS ORGANISATION'S: whose it was is written down before
    # the row that says so goes (services/app_register).
    try:
        from services.credits import projects_known
        await projects_known(db)
    except Exception:  # noqa: BLE001 — accounting never stops a removal
        pass

    from preview import stop_preview
    _step(report, "preview", short_id, lambda: stop_preview(short_id))

    await _detach_domains(output_dir, short_id, report)

    from services import app_databases
    if app_databases.server() and output_dir:
        name = app_databases.name_for(Path(output_dir) / "app")
        _step(report, "app_database", name, lambda: app_databases.drop(name))

    await _delete_neon_projects(db, project.id, report)

    if output_dir and Path(output_dir).exists():
        _step(report, "folder", output_dir, lambda: shutil.rmtree(output_dir))

    pid = project.id
    try:
        db.expunge(project)
    except Exception:  # noqa: BLE001 — a project loaded elsewhere
        pass
    # Raw deletes, as the member's delete always did: the ORM's cascade walks
    # back-references over tables an older project may not have.
    await db.execute(delete(Version).where(Version.project_id == pid))
    await db.execute(delete(AgentJob).where(AgentJob.project_id == pid))
    await db.execute(delete(Conversation).where(Conversation.project_id == pid))
    await db.execute(delete(Deployment).where(Deployment.project_id == pid))
    await db.execute(delete(Project).where(Project.id == pid))
    await db.commit()
    report["removed"].append({"step": "rows", "target": short_id})
    return report


async def purge_organization(db: AsyncSession, org: Any) -> dict[str, list]:
    """Every project of the organisation torn down, then the organisation's
    own row — its members, people, roles and the rest go with it (FK cascade)."""
    from models.org import Organization

    report = _report()
    projects = (await db.execute(select(Project).where(Project.org_id == org.id))).scalars().all()
    for project in projects:
        await remove_project(db, project, report=report)
    org_id = org.id
    try:
        db.expunge(org)
    except Exception:  # noqa: BLE001
        pass
    await db.execute(delete(Organization).where(Organization.id == org_id))
    await db.commit()
    report["removed"].append({"step": "organization", "target": str(org_id)})
    return report


__all__ = ["remove_project", "purge_organization"]

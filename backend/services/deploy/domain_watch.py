"""The domain watch: every minute, each app's addresses whose time has come
are checked (`DomainService.watch_due`), and what changed is said in the app's
chat. Started with the backend; quiet when publishing is not set up."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

INTERVAL_S = 60


def _has_domains(root: Path) -> bool:
    import json
    p = root / ".forge" / "blueprint" / "current.json"
    try:
        doc = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return False
    return bool(((doc.get("deployment") or {}).get("domains")))


async def sweep() -> int:
    """One pass over every app; the number of addresses checked."""
    if not os.environ.get("VERCEL_TOKEN"):
        return 0
    from sqlalchemy import select

    from database import async_session
    from models.project import Project
    from routers.domains import _tell
    from services.deploy.domains import DomainService, project_root, vercel_project_name
    from services.deploy.vercel_client import VercelClient

    async with async_session() as db:
        rows = (await db.execute(select(Project.id, Project.short_id, Project.output_dir)
                                 .where(Project.output_dir.is_not(None)))).all()
    checked = 0
    client = VercelClient()
    try:
        for pid, short_id, output_dir in rows:
            root = project_root(output_dir)
            if not _has_domains(root):
                continue
            said: list[str] = []
            try:
                from services.deploy.domain_check import check_address
                svc = DomainService(output_dir=str(root), client=client, address_check=check_address,
                                    project_name=vercel_project_name(short_id), say=said.append)
                checked += await svc.watch_due()
            except Exception:  # noqa: BLE001 — one app never stops the sweep
                logger.warning("[domain-watch] %s failed", short_id, exc_info=True)
            await _tell(pid, said)
    finally:
        await client.close()
    return checked


async def watch_forever() -> None:
    while True:
        try:
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the watch never dies
            logger.warning("[domain-watch] sweep failed", exc_info=True)
        await asyncio.sleep(INTERVAL_S)


__all__ = ["INTERVAL_S", "sweep", "watch_forever"]

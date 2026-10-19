"""The switch that lets assistants connect to an application (`app_settings`).

GET says whether the app's MCP server is on and what it offers; PUT turns it
on or off. The tools themselves are the app's (`app_mcp.catalog`), written
from its definition; this route only reads them to say what is offered.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.project_service import get_project_with_auth

router = APIRouter()


class McpSwitch(BaseModel):
    enabled: bool


def _view(output_dir: str | None) -> dict:
    from services import app_settings
    from services.blueprint.app_mcp import CATALOG

    setting = (app_settings.read(output_dir).get("mcpServer") or {})
    tools = {"workflows": [], "records": []}
    if output_dir:
        try:
            data = json.loads((Path(output_dir) / "app" / CATALOG).read_text("utf-8"))
            tools = {"workflows": [{"tool": w["tool"], "name": w["name"], "roles": w.get("roles")}
                                   for w in data.get("workflows") or []],
                     "records": [{"find": r["find"], "get": r["get"], "name": r["name"], "roles": r.get("roles")}
                                 for r in data.get("records") or []]}
        except (OSError, ValueError, KeyError):
            pass
    return {"enabled": bool(setting.get("enabled")), "changedAt": setting.get("changedAt"),
            "path": "/api/mcp", "connectPage": "/connect-ai", "tools": tools}


@router.get("/api/projects/{project_id}/app-mcp")
async def app_mcp_status(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> dict:
    project = await get_project_with_auth(project_id, user, db)
    return _view(project.output_dir)


@router.put("/api/projects/{project_id}/app-mcp")
async def set_app_mcp(project_id: uuid.UUID, body: McpSwitch, user: PlatformUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict:
    """Turn the app's MCP server on or off. The preview hears it at once; the
    live app with its next publish."""
    from services import app_settings
    from services.audit_service import audit_log

    project = await get_project_with_auth(project_id, user, db)
    if project.output_dir:
        app_settings.set_mcp(project.output_dir, body.enabled, by=str(user.email or user.id))
    try:
        await audit_log(db, user_id=user.id, action="app_mcp.on" if body.enabled else "app_mcp.off",
                        resource_type="project", resource_id=str(project.id), org_id=project.org_id)
        await db.commit()
    except Exception:  # noqa: BLE001 — the switch stands without its trail line
        await db.rollback()
    return _view(project.output_dir)

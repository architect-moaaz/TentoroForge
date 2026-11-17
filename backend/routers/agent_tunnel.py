"""Connecting the builder's own computer to a platform that runs on a server (see services/agent_tunnel.py).

Signed-in members of a project (with the Agents feature on): see the tunnel's state, ask for a one-time pairing code, disconnect. A
computer belongs to the person who registered it: only they, or an admin of the organisation, may replace or remove it.
Anyone with a valid code (the connector program on the builder's computer): redeem it, and download the connector.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services import agent_tunnel
from services.agent_debug import hosting
from services.features import feature_gate
from services.project_service import get_project_with_auth

router = APIRouter()

CONNECTOR = Path(__file__).resolve().parent.parent / "templates" / "tunnel" / "ttf-watch-connect.mjs"


class PairRequest(BaseModel):
    code: str = Field(max_length=32)
    publicKey: str = Field(max_length=200)
    appPort: int
    secret: str = Field(max_length=100)
    label: str = Field(default="", max_length=80)


def _client_ip(request: Request) -> str:
    # The proxy in front of the platform sets X-Forwarded-For to the address it saw: the last entry is the one it wrote.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()[:64]
    return request.client.host if request.client else ""


async def _is_admin_for_tunnel(project, user: PlatformUser, db: AsyncSession) -> bool:
    """Whether this person is an admin of the project's organisation. Asked only when someone else's computer is registered, because
    that is the only time the answer changes what they may do."""
    current = await asyncio.to_thread(agent_tunnel.get, str(project.id))
    owner = (current or {}).get("registeredBy")
    if not owner or owner == str(user.id):
        return False
    from fastapi import HTTPException as _HTTPException
    from models.org import OrgMemberRole
    from services.org_access import require_org_member

    try:
        await require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)
    except _HTTPException:
        return False
    return True


def _fail(e: agent_tunnel.TunnelError):
    raise HTTPException(status_code=e.status_code, detail=str(e))


# The three builder routes are gated like the other agent routes; the public ones below (the connector's) cannot be, as they have no sign-in.
@router.get("/api/projects/{project_id}/agent-definitions/debug/tunnel", dependencies=[Depends(feature_gate("agents"))])
async def tunnel_state(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Whether a computer is connected for this project, where from, and where the platform knows the app is hosted."""
    project = await get_project_with_auth(project_id, user, db)
    state = await asyncio.to_thread(agent_tunnel.describe, str(project.id))
    return {**state, "hosted": await hosting(db, project.id)}


@router.post("/api/projects/{project_id}/agent-definitions/debug/tunnel/pair", dependencies=[Depends(feature_gate("agents"))])
async def tunnel_pair(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A one-time code (10 minutes) to give the connector on the computer where the app runs."""
    project = await get_project_with_auth(project_id, user, db)
    if not agent_tunnel.enabled():
        raise HTTPException(status_code=409, detail="This platform runs on your own computer, so there is nothing to connect: use the app's address.")
    try:
        return await asyncio.to_thread(agent_tunnel.new_pairing, str(project.id), user_id=str(user.id),
                                       is_admin=await _is_admin_for_tunnel(project, user, db))
    except agent_tunnel.TunnelError as e:
        _fail(e)


@router.delete("/api/projects/{project_id}/agent-definitions/debug/tunnel", dependencies=[Depends(feature_gate("agents"))])
async def tunnel_revoke(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Forget the connected computer. Its key stops being accepted for new connections at once."""
    project = await get_project_with_auth(project_id, user, db)
    try:
        return {"removed": await asyncio.to_thread(agent_tunnel.revoke, str(project.id), user_id=str(user.id),
                                                   is_admin=await _is_admin_for_tunnel(project, user, db))}
    except agent_tunnel.TunnelError as e:
        _fail(e)


@router.get("/api/tunnel/info")
async def tunnel_info():
    """Where a computer connects and the server identity to trust. Public: an address and a public key, nothing secret."""
    try:
        return await asyncio.to_thread(agent_tunnel.info)
    except agent_tunnel.TunnelError as e:
        _fail(e)


@router.post("/api/tunnel/pair")
async def redeem(req: PairRequest, request: Request):
    """The connector redeems its code. Public by design: the code is the credential (one use, 10 minutes, rate limited)."""
    try:
        return await asyncio.to_thread(
            agent_tunnel.pair, req.code, req.publicKey, req.appPort, req.secret, client_ip=_client_ip(request), label=req.label)
    except agent_tunnel.TunnelError as e:
        _fail(e)


@router.get("/api/tunnel/connector.mjs")
async def connector():
    """The connector program, to run on the computer where the app is. It holds no secret."""
    try:
        text = CONNECTOR.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status_code=404, detail="The connector is not part of this build.")
    return Response(text, media_type="text/javascript; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="ttf-watch-connect.mjs"', "Cache-Control": "no-cache"})

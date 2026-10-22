"""The live phone preview — start it, keep it current, and let the picture reach it through the backend.

    POST /api/projects/{project_id}/phone-preview/live/start    start the dev server (or say where it stands)
    POST /api/projects/{project_id}/phone-preview/live/sync     bring its copy up to date now (it also notices changes by itself)
    POST /api/projects/{project_id}/phone-preview/live/stop     stop it
    GET  /api/projects/{short_id}/phone/live/{path}             what the picture asks of it: the page, its bundle, fonts, pictures
    WS   /api/projects/{short_id}/phone/live/hot | message      its two live-update sockets

The first three are the editor's and need the person's session. The rest are loaded by an iframe, which cannot send the platform's
bearer token (the same reason `/phone/serve` is open), and they pass on only what a page needs (`services.phone_live_proxy`). Everything
rides on `/api/*`, which the proxy in front of the platform already forwards, WebSockets included.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from routers.phone_preview import _project
from services import phone_live, phone_live_proxy as proxy

router = APIRouter()


async def _built_project(project_id: str, user: PlatformUser, db: AsyncSession):
    project = await _project(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=404, detail="Nothing has been built into this project yet.")
    return project


@router.post("/api/projects/{project_id}/phone-preview/live/start")
async def live_start(project_id: str, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _built_project(project_id, user, db)
    try:
        return phone_live.start(project.output_dir, project.short_id, str(project.org_id))
    except phone_live.PhonePreviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/api/projects/{project_id}/phone-preview/live/sync")
async def live_sync(project_id: str, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _built_project(project_id, user, db)
    changed = await phone_live.sync(project.short_id)
    return {**phone_live.status(project.short_id), "changed": changed}


@router.post("/api/projects/{project_id}/phone-preview/live/stop")
async def live_stop(project_id: str, user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _built_project(project_id, user, db)
    phone_live.stop(project.short_id)
    return phone_live.status(project.short_id)


@router.api_route("/api/projects/{short_id}/phone/live/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/api/projects/{short_id}/phone/live", methods=["GET", "HEAD"], include_in_schema=False)
async def live(short_id: str, request: Request, path: str = ""):
    prefix = phone_live.live_path(short_id)
    rest = proxy.upstream_path(request.scope.get("raw_path") or request.url.path.encode("latin-1"), prefix)
    own = proxy.own_file(rest)
    if own:
        return FileResponse(own[0], media_type=own[1], headers={"Cache-Control": "no-store"})
    port = phone_live.port_of(short_id)
    if port is None:
        return JSONResponse({"detail": "The live preview is not running."}, status_code=503)
    accept = request.headers.get("accept", "")
    if not proxy.allowed(rest):
        if "text/html" not in accept:
            raise HTTPException(status_code=404, detail="Not found.")
        rest = "/"                                   # a screen's own address, reloaded: the page, whose router reads it
    try:
        upstream, client = await proxy.fetch(port, rest, request.url.query, request.method, accept or None)
    except httpx.TransportError:
        phone_live.mark_unreachable(short_id)
        return JSONResponse({"detail": "The live preview is not answering."}, status_code=503)
    if upstream.headers.get("content-type", "").startswith("text/html"):
        body = (await upstream.aread()).decode("utf-8", "replace")
        await upstream.aclose()
        await client.aclose()
        return HTMLResponse(proxy.rewrite_html(body, prefix), status_code=upstream.status_code, headers={"Cache-Control": "no-store"})
    if rest.split("?", 1)[0].endswith(".bundle") and upstream.status_code == 200:
        # The app's code names its fonts and pictures from the top of the host; they are moved under the prefix (a few MB, read whole).
        text = (await upstream.aread()).decode("utf-8", "replace")
        headers = proxy.response_headers(upstream)
        await upstream.aclose()
        await client.aclose()
        return Response(proxy.rewrite_bundle(text, prefix), media_type=upstream.headers.get("content-type", "application/javascript"),
                        headers={k: v for k, v in headers.items() if k.lower() != "content-type"})
    return StreamingResponse(proxy.stream(upstream, client), status_code=upstream.status_code, headers=proxy.response_headers(upstream))


@router.websocket("/api/projects/{short_id}/phone/live/hot")
@router.websocket("/api/projects/{short_id}/phone/live/message")
async def live_socket(websocket: WebSocket, short_id: str):
    which = "/hot" if websocket.url.path.endswith("/hot") else "/message"
    port = phone_live.port_of(short_id)
    if port is None:
        await websocket.close(code=1013)             # try again later
        return
    await websocket.accept()
    try:
        await proxy.pump(websocket, port, which, phone_live.live_path(short_id))
    except Exception:  # noqa: BLE001 - the page reconnects; nothing here is worth a trace
        pass
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass

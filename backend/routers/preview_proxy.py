"""Reverse-proxy for per-project Next.js dev previews.

The visual editor iframes the generated app so users can click on
elements to edit them. On the developer's own machine the iframe pointed
at `http://localhost:<port>` because the backend spawned `next dev` on
the same host. In UAT/prod the backend runs inside a container and the
tester's browser can't reach that internal port, so the iframe 404s
(bug B-013).

This router proxies HTTP requests from `/api/projects/{project_id}/preview/serve/*`
to the per-project internal `localhost:<port>` returned by
preview.get_preview_port. Combined with `NEXT_BASE_PATH` in preview.py
(which makes the generated app emit URLs already prefixed with the
proxy path), the browser never has to know about the internal port.

Auth is intentionally not required on this endpoint: iframe subresource
requests (JS chunks, CSS, images loaded by `_next/static/*`) do not
carry the platform's `Authorization: Bearer …` header, so requiring
auth would make the page load but leave every asset broken. Project
short_ids are opaque and preview servers only run when the platform UI
explicitly calls `POST /preview/start`, so the exposure surface is
limited to "anyone who knows a short_id can view (not edit) that
project's dev preview".

ONLY AT THE PREVIEW'S OWN ORIGIN (`services/preview_origin.py`). Through the
platform's address the app's code ran as the platform, and could read the
signed-in person's token. A page it serves carries the loader the editor's
bridge is sent to; the instant pages' host (`/preview/frame`) and the drawn
pictures (`/drawn/…`) are served here too, at the same origin.
"""

from __future__ import annotations

import http.cookiejar
import logging
from typing import AsyncIterator

import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from preview import get_preview_port, start_preview
from services import dev_servers, preview_origin

logger = logging.getLogger(__name__)

router = APIRouter()

# Headers that must NOT be forwarded verbatim between hops. `Host` /
# `Content-Length` are transport-layer; `Connection`/`Keep-Alive` /
# `Transfer-Encoding` control connection reuse; `Upgrade` is for WS.
_HOP_BY_HOP = frozenset(
    h.lower()
    for h in (
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    )
)

# One shared client. Next dev streams SSE for HMR-adjacent endpoints;
# a per-request client would leak connections. `follow_redirects=False`
# so we forward 3xx unchanged.
#
# IT KEEPS NO COOKIES. An httpx client stores every Set-Cookie it is
# answered with and sends it with every later request it builds: the first
# person to sign in to a preview had their session sent with everyone else's
# requests, so a signed-out visitor read the app as them ("/api/billing/status"
# answered `access: true` to a request with no cookie at all, 2026-11-11). The
# jar refuses every cookie, and each request is built on its own, carrying
# only the browser's own Cookie header.
_NO_COOKIES = http.cookiejar.CookieJar(policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), follow_redirects=False,
                            cookies=_NO_COOKIES)


def _filter_headers(headers) -> list[tuple[str, str]]:
    # `multi_items`, not `items`: httpx joins repeated headers with ", ", and
    # a Set-Cookie list joined that way is one broken cookie.
    items = headers.multi_items() if hasattr(headers, "multi_items") else headers.items()
    return [(k, v) for k, v in items if k.lower() not in _HOP_BY_HOP]


def _elsewhere() -> HTTPException:
    return HTTPException(status_code=404, detail=(
        f"A preview opens only at its own address ({preview_origin.origin()}), never at the platform's."))


def _a_page(request: Request) -> bool:
    """A document the browser is opening — the one kind of response the loader goes in."""
    dest = (request.headers.get("sec-fetch-dest") or "").lower()
    if dest:
        return dest in ("document", "iframe")
    return request.method == "GET" and "text/html" in (request.headers.get("accept") or "")


async def _proxy(request: Request, project_id: str, path: str, *, upstream_path: str | None = None) -> Response:
    if not preview_origin.may_serve(request):
        raise _elsewhere()
    port = get_preview_port(project_id)
    if port is None:
        # A PREVIEW THE REAPER ENDED COMES BACK WHEN IT IS OPENED. The tab
        # still shows it; the person clicks, and waits for a start rather
        # than reading a 503.
        root = dev_servers.reaped(project_id)
        if root:
            try:
                port = await start_preview(project_id, root)
            except RuntimeError as exc:
                logger.warning("preview %s did not come back: %s", project_id, exc)
    if port is None:
        raise HTTPException(
            status_code=503,
            detail="Preview server not running for this project. Call /preview/start first.",
        )

    # Reconstruct the upstream URL. The generated Next app expects
    # requests including the basePath, so we forward the full incoming
    # path verbatim — no stripping of the /api/projects/../preview/serve
    # prefix. That keeps `<Link href="/foo">` renders correctly since
    # Next writes them as `/api/projects/.../preview/serve/foo` and the
    # dev server sees the same shape it emitted.
    dev_servers.touch(port)
    upstream_url = f"http://localhost:{port}{upstream_path or request.url.path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    fwd_headers = _filter_headers(request.headers)
    page = _a_page(request)
    if page:
        # Plain bytes, so the loader can go in.
        fwd_headers = [(k, v) for k, v in fwd_headers if k.lower() != "accept-encoding"] + [("accept-encoding", "identity")]

    try:
        body_iter = request.stream()
        upstream_req = _client.build_request(
            request.method,
            upstream_url,
            headers=fwd_headers,
            content=body_iter,
        )
        upstream_resp = await _client.send(upstream_req, stream=True)
    except httpx.ConnectError:
        raise HTTPException(
            status_code=502,
            detail="Preview server crashed — call /preview/start again to restart it.",
        )
    except httpx.RequestError as e:
        logger.warning("preview proxy upstream error project=%s path=%s: %s", project_id, path, e)
        raise HTTPException(status_code=502, detail=f"Preview upstream error: {e}")

    async def stream_upstream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()

    resp_headers = _filter_headers(upstream_resp.headers)
    if page and "text/html" in (upstream_resp.headers.get("content-type") or "") \
            and not upstream_resp.headers.get("content-encoding"):
        try:
            body = await upstream_resp.aread()
        finally:
            await upstream_resp.aclose()
        response = Response(preview_origin.inject_loader(body), status_code=upstream_resp.status_code,
                            headers={k: v for k, v in resp_headers if k.lower() != "set-cookie"},
                            media_type=upstream_resp.headers.get("content-type"))
        for k, v in resp_headers:
            if k.lower() == "set-cookie":
                response.raw_headers.append((b"set-cookie", v.encode("latin-1")))
        return response
    response = StreamingResponse(
        stream_upstream(),
        status_code=upstream_resp.status_code,
        headers={k: v for k, v in resp_headers if k.lower() != "set-cookie"},
        media_type=upstream_resp.headers.get("content-type"),
    )
    # EVERY COOKIE, EACH ON ITS OWN LINE. A dict kept one Set-Cookie of
    # next-auth's three, so a preview sign-in succeeded and no session
    # arrived (Test4, 2026-09-28).
    for k, v in resp_headers:
        if k.lower() == "set-cookie":
            response.raw_headers.append((b"set-cookie", v.encode("latin-1")))
    return response


# One route per method — FastAPI has no single catch-all decorator, and
# `add_api_route(..., methods=[...])` bypasses OpenAPI in a way that has
# tripped up tools before. Enumerate what we actually need.
@router.api_route(
    "/api/projects/{project_id}/preview/serve/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def preview_serve(project_id: str, path: str, request: Request) -> Response:
    return await _proxy(request, project_id, path)


# The trailing slash / bare `/api/projects/{id}/preview/serve` — when
# the iframe first loads with the base URL, `path` is empty and the
# above route needs at least one path segment. Without this variant
# the initial load 404s and every asset URL never gets a chance.
@router.api_route(
    "/api/projects/{project_id}/preview/serve",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def preview_serve_root(project_id: str, request: Request) -> Response:
    return await _proxy(request, project_id, "")


@router.get("/api/preview/origin")
async def where_previews_are() -> JSONResponse:
    """The origin every preview frame loads from (`services/preview_origin.py`)."""
    return JSONResponse({"origin": preview_origin.origin()})


@router.get("/api/projects/{project_id}/preview/frame", include_in_schema=False)
async def instant_page_host(project_id: str, request: Request) -> HTMLResponse:
    """The page an instant page runs in, at the preview's origin."""
    if not preview_origin.may_serve(request):
        raise _elsewhere()
    return HTMLResponse(preview_origin.frame_host(), headers={"cache-control": "no-store"})


_FROM_A_PREVIEW = re.compile(r"/api/projects/([^/]+)/preview/serve")


@router.get("/drawn/{path:path}", include_in_schema=False)
async def drawn_picture(path: str, request: Request) -> Response:
    """A drawn app's pictures, asked for from inside its preview. A view
    converted from Figma names them `/drawn/…` from the app's root; the page
    that asks names its project in the Referer (as the frontend's rewrite did
    while previews were served there)."""
    found = _FROM_A_PREVIEW.search(request.headers.get("referer") or "")
    if not found:
        raise HTTPException(status_code=404)
    project_id = found.group(1)
    return await _proxy(request, project_id, f"drawn/{path}",
                        upstream_path=f"/api/projects/{project_id}/preview/serve/drawn/{path}")

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
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from preview import get_preview_port

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
_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), follow_redirects=False)


def _filter_headers(headers) -> list[tuple[str, str]]:
    return [(k, v) for k, v in headers.items() if k.lower() not in _HOP_BY_HOP]


async def _proxy(request: Request, project_id: str, path: str) -> Response:
    port = get_preview_port(project_id)
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
    upstream_url = f"http://localhost:{port}{request.url.path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    fwd_headers = _filter_headers(request.headers)

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
    return StreamingResponse(
        stream_upstream(),
        status_code=upstream_resp.status_code,
        headers=dict(resp_headers),
        media_type=upstream_resp.headers.get("content-type"),
    )


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

"""A preview runs the app's code, so it is served only at an origin of its own.

Through the platform's address (the frontend's rewrite of /api/projects/*),
in a frame allowed to act as that address, the app's code could read the
signed-in person's token from the platform's storage (audit, 2026-11-01).
"""
from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

PAGE = b"<!doctype html><html><head><title>App</title></head><body>hi</body></html>"


@pytest.fixture()
def upstream(monkeypatch):
    """A running dev server for project `abc123`, answering with an HTML page."""
    from routers import preview_proxy

    seen: list[httpx.Request] = []

    async def chunks(data: bytes):
        yield data  # streamed, as a dev server's answer is

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith(".js"):
            return httpx.Response(200, content=chunks(b"console.log(1)"), headers={"content-type": "application/javascript"})
        return httpx.Response(200, content=chunks(PAGE), headers={"content-type": "text/html; charset=utf-8"})

    monkeypatch.setattr(preview_proxy, "get_preview_port", lambda pid: 4999 if pid == "abc123" else None)
    monkeypatch.setattr(preview_proxy, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


async def _client(**headers) -> AsyncClient:
    from main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:6500", headers=headers)


@pytest.mark.asyncio
async def test_through_the_platforms_address_a_preview_is_refused(upstream):
    # What the frontend's rewrite sends: the platform's host, forwarded.
    async with await _client(**{"x-forwarded-host": "localhost:6501", "x-forwarded-for": "127.0.0.1"}) as c:
        r = await c.get("/api/projects/abc123/preview/serve/", headers={"sec-fetch-dest": "iframe"})
    assert r.status_code == 404 and "only at its own address" in r.text
    assert upstream == [], "the app was never asked"


@pytest.mark.asyncio
async def test_at_its_own_origin_a_page_carries_the_loader_and_its_assets_pass_untouched(upstream):
    async with await _client() as c:
        r = await c.get("/api/projects/abc123/preview/serve/", headers={"sec-fetch-dest": "iframe", "accept-encoding": "gzip"})
        js = await c.get("/api/projects/abc123/preview/serve/_next/app.js", headers={"sec-fetch-dest": "script"})
    assert r.status_code == 200
    assert b"forge-editor:loader-ready" in r.content and r.content.index(b"<script>") < r.content.index(b"</head>")
    assert upstream[0].headers["accept-encoding"] == "identity", "plain bytes, so the loader can go in"
    assert js.content == b"console.log(1)"
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self' " in csp and "http://localhost:6501" in csp.split("frame-ancestors")[1]
    assert "x-frame-options" not in {k.lower() for k in r.headers}


def test_the_loader_takes_the_bridge_only_from_the_editor():
    from services.preview_origin import LOADER, frame_host

    assert '"http://localhost:6501"' in LOADER and "O.indexOf(e.origin)<0" in LOADER
    assert "e.source!==window.parent" in LOADER and "__forgeEditorParent=e.origin" in LOADER
    host = frame_host()
    assert "forge-editor:mount" in host and "forge-editor:host-ready" in host and "O.indexOf(e.origin)<0" in host


@pytest.mark.asyncio
async def test_the_instant_page_host_and_the_drawn_pictures_are_at_the_preview_origin(upstream):
    async with await _client() as c:
        host = await c.get("/api/projects/abc123/preview/frame")
        origin = await c.get("/api/preview/origin")
        pic = await c.get("/drawn/logo.svg", headers={"referer": "http://localhost:6500/api/projects/abc123/preview/serve/home"})
        stray = await c.get("/drawn/logo.svg")
    assert host.status_code == 200 and "forge-editor:mount" in host.text
    assert origin.json() == {"origin": "http://localhost:6500"}
    assert pic.status_code == 200 and upstream[-1].url.path == "/api/projects/abc123/preview/serve/drawn/logo.svg"
    assert stray.status_code == 404
    async with await _client(**{"x-forwarded-host": "localhost:6501"}) as c:
        assert (await c.get("/api/projects/abc123/preview/frame")).status_code == 404


@pytest.mark.asyncio
async def test_a_named_preview_origin_serves_nothing_but_previews(monkeypatch, upstream):
    import config

    monkeypatch.setenv("FORGE_PREVIEW_ORIGIN", "https://preview.forge.test")
    monkeypatch.setattr(config, "PREVIEW_ORIGIN", "https://preview.forge.test")
    async with await _client(**{"x-forwarded-host": "preview.forge.test", "x-forwarded-for": "203.0.113.9"}) as c:
        assert (await c.get("/api/auth/me")).status_code == 404
        assert (await c.get("/api/projects/abc123/preview/serve/", headers={"sec-fetch-dest": "iframe"})).status_code == 200
    # The platform's own address still serves the platform's API, and no preview.
    async with await _client(**{"x-forwarded-host": "forge.test", "x-forwarded-for": "203.0.113.9"}) as c:
        assert (await c.get("/api/auth/me")).status_code in (401, 403)
        assert (await c.get("/api/projects/abc123/preview/serve/")).status_code == 404

import pytest
from httpx import ASGITransport, AsyncClient

from services.render_service.server import build_app, RenderRequest
from services.render_service.browser_pool import BrowserPool


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok():
    app = build_app(scaffold_url="http://localhost:6503")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_render_returns_422_when_scaffold_unreachable():
    """Pool is started manually because ASGITransport does not fire lifespan events."""
    # Build app; extract its pool by starting one manually and wiring it in.
    # Simpler: build the app, manually start the pool via the startup handler.
    app = build_app(scaffold_url="http://localhost:54321")

    # Fire the startup event manually so the BrowserPool is warmed up.
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/render", json={
                "projectId": "test", "pageRoute": "/x", "viewport": "desktop",
            })
            assert r.status_code == 422

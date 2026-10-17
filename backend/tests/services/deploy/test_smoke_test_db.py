"""Tests for the post-READY DB smoke check.

The smoke check is a shallow probe that answers "is the app answering
requests?" and, if the health endpoint is reachable unauthenticated,
"is the DB up + populated?". A 3xx redirect from the probe (typical:
NextAuth middleware bouncing to /login) must count as success — the
Next.js runtime is definitely up, and blocking a working deploy on an
auth redirect is a UX bug (was surfacing as "modal stuck on Activating").
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services.deploy.vercel_provider import _smoke_test_db


def _resp(status: int, body: dict | None = None) -> httpx.Response:
    if body is not None:
        return httpx.Response(status, json=body)
    return httpx.Response(status)


@pytest.mark.asyncio
async def test_smoke_ok_when_200_with_ok_true():
    mock = AsyncMock(return_value=_resp(200, {"ok": True, "tables": 12}))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is True
    assert err is None


@pytest.mark.asyncio
async def test_smoke_ok_when_307_middleware_redirect():
    """The exact failure that broke UAT — NextAuth middleware bounced
    /api/health/db to /login. Deploy was live, but the smoke check
    reported HTTP 307 and the modal got stuck on Activating."""
    mock = AsyncMock(return_value=_resp(307))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is True
    assert err is None


@pytest.mark.asyncio
async def test_smoke_ok_when_302_redirect():
    mock = AsyncMock(return_value=_resp(302))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is True


@pytest.mark.asyncio
async def test_smoke_fails_when_503_with_error_body():
    mock = AsyncMock(return_value=_resp(503, {"error": "no tables"}))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is False
    assert "no tables" in (err or "")


@pytest.mark.asyncio
async def test_smoke_fails_when_500():
    mock = AsyncMock(return_value=_resp(500))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is False
    assert "500" in (err or "")


@pytest.mark.asyncio
async def test_smoke_fails_when_200_but_ok_false():
    mock = AsyncMock(return_value=_resp(200, {"ok": False, "error": "connect refused"}))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is False
    assert "connect refused" in (err or "")


@pytest.mark.asyncio
async def test_smoke_fails_when_probe_raises():
    mock = AsyncMock(side_effect=httpx.ConnectError("dns failure"))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is False
    assert "probe failed" in (err or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_smoke_ok_when_the_middleware_answers_401_or_403(status):
    """An /api/* call without a session is answered 401 as JSON (a phone app cannot follow a redirect). The probe is such a
    call: Iron Log's first publish was live and healthy, and the check said "database unhealthy: HTTP 401"."""
    mock = AsyncMock(return_value=_resp(status, {"error": {"code": "UNAUTHORIZED", "message": "Sign in to use this."}}))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is True and err is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 500, 502])
async def test_smoke_still_fails_on_a_real_server_fault(status):
    mock = AsyncMock(return_value=_resp(status))
    with patch("httpx.AsyncClient.get", mock):
        ok, err = await _smoke_test_db("https://app.example.com")
    assert ok is False and f"HTTP {status}" in (err or "")

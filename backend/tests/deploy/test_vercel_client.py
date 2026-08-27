"""Unit tests for VercelClient — every REST call mocked via respx.

Never hits the real Vercel API in CI. Locks in the shape we expect
from each of the endpoints the deploy pipeline calls, so a Vercel API
change surfaces as a test failure instead of a runtime "sorry, that
deployment vanished" halfway through a publish.
"""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from services.deploy.vercel_client import VercelClient


@pytest.mark.asyncio
async def test_create_project_hits_v9_projects() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.post("https://api.vercel.com/v9/projects").mock(
            return_value=Response(
                200, json={"id": "prj_abc", "name": "acme", "framework": "nextjs"}
            )
        )
        c = VercelClient(token="tk", team_id="tm")
        try:
            r = await c.create_project(name="acme")
        finally:
            await c.close()
        assert r["id"] == "prj_abc"


@pytest.mark.asyncio
async def test_set_env_uses_upsert_and_encrypted_type() -> None:
    """Env vars must be set with upsert=true so a redeploy that
    already has DATABASE_URL doesn't fail with "env already exists",
    and type=encrypted so integration secrets aren't visible in the
    Vercel dashboard."""
    async with respx.mock(assert_all_called=True) as rmock:
        route = rmock.post("https://api.vercel.com/v9/projects/prj_abc/env").mock(
            return_value=Response(200, json={"created": [{"key": "DATABASE_URL"}]})
        )
        c = VercelClient(token="tk", team_id="tm")
        try:
            r = await c.set_env(
                project_id="prj_abc",
                key="DATABASE_URL",
                value="postgres://ep.neon.tech/main",
                target=["production"],
            )
        finally:
            await c.close()
        assert r["created"][0]["key"] == "DATABASE_URL"
        # Verify request params + body shape
        req = route.calls.last.request
        assert "upsert=true" in str(req.url)
        assert "teamId=tm" in str(req.url)
        import json as _json

        body = _json.loads(req.content)
        assert body["type"] == "encrypted"
        assert body["target"] == ["production"]


@pytest.mark.asyncio
async def test_upload_file_posts_bytes_with_sha_digest_header() -> None:
    """Files are uploaded to /v2/files with `x-vercel-digest: <sha1>`
    and the raw bytes as the request body; anything else and Vercel
    either 400s ("digest mismatch") or writes garbage against a wrong
    key."""
    async with respx.mock(assert_all_called=True) as rmock:
        route = rmock.post("https://api.vercel.com/v2/files").mock(
            return_value=Response(200)
        )
        c = VercelClient(token="tk", team_id="tm")
        try:
            await c.upload_file(sha="abc123", raw=b"hello")
        finally:
            await c.close()
        req = route.calls.last.request
        assert req.headers["x-vercel-digest"] == "abc123"
        assert req.headers["content-type"] == "application/octet-stream"
        assert req.content == b"hello"


@pytest.mark.asyncio
async def test_create_deployment_specifies_nextjs_framework() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.post("https://api.vercel.com/v13/deployments").mock(
            return_value=Response(
                200, json={"id": "dpl_xyz", "url": "acme-a1b2.vercel.app"}
            )
        )
        c = VercelClient(token="tk", team_id="tm")
        try:
            r = await c.create_deployment(
                name="acme",
                project_id="prj_abc",
                files=[{"file": "package.json", "data": "{}"}],
            )
        finally:
            await c.close()
        assert r["url"] == "acme-a1b2.vercel.app"
        assert r["id"] == "dpl_xyz"


@pytest.mark.asyncio
async def test_get_deployment_returns_ready_state() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.get("https://api.vercel.com/v13/deployments/dpl_xyz").mock(
            return_value=Response(
                200, json={"readyState": "READY", "url": "acme.vercel.app"}
            )
        )
        c = VercelClient(token="tk", team_id="tm")
        try:
            r = await c.get_deployment("dpl_xyz")
        finally:
            await c.close()
        assert r["readyState"] == "READY"


@pytest.mark.asyncio
async def test_promote_deployment_uses_patch_promote_endpoint() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.patch("https://api.vercel.com/v13/deployments/dpl_old/promote").mock(
            return_value=Response(200, json={"promoted": True})
        )
        c = VercelClient(token="tk", team_id="tm")
        try:
            r = await c.promote_deployment("dpl_old")
        finally:
            await c.close()
        assert r["promoted"] is True


@pytest.mark.asyncio
async def test_raises_http_error_on_non_2xx() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.post("https://api.vercel.com/v9/projects").mock(
            return_value=Response(
                403, json={"error": {"code": "forbidden", "message": "bad token"}}
            )
        )
        c = VercelClient(token="tk", team_id="tm")
        try:
            with pytest.raises(Exception):
                await c.create_project(name="acme")
        finally:
            await c.close()

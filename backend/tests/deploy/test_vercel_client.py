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
async def test_a_passing_vercel_fault_is_tried_again(monkeypatch) -> None:
    """Med Tracker's publish died on one 500 for one 789-byte file."""
    from services.deploy import vercel_client
    monkeypatch.setattr(vercel_client, "UPLOAD_BACKOFF_S", (0.0, 0.0, 0.0))
    async with respx.mock(assert_all_called=True) as rmock:
        route = rmock.post("https://api.vercel.com/v2/files").mock(
            side_effect=[Response(500, text="Internal Server Error"), Response(429), Response(200)])
        c = VercelClient(token="tk", team_id="tm")
        try:
            await c.upload_file(sha="abc123", raw=b"hello")
        finally:
            await c.close()
        assert route.call_count == 3


@pytest.mark.asyncio
async def test_a_refusal_is_not_retried_and_a_lasting_fault_still_fails(monkeypatch) -> None:
    from services.deploy import vercel_client
    monkeypatch.setattr(vercel_client, "UPLOAD_BACKOFF_S", (0.0, 0.0, 0.0))
    async with respx.mock() as rmock:
        route = rmock.post("https://api.vercel.com/v2/files").mock(return_value=Response(400, json={"error": "digest mismatch"}))
        c = VercelClient(token="tk", team_id="tm")
        with pytest.raises(RuntimeError, match="status=400"):
            await c.upload_file(sha="abc123", raw=b"hello")
        assert route.call_count == 1
        route.mock(return_value=Response(500, text="Internal Server Error"))
        with pytest.raises(RuntimeError, match="status=500"):
            await c.upload_file(sha="abc123", raw=b"hello")
        assert route.call_count == 1 + 4
        await c.close()


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



@pytest.mark.asyncio
async def test_a_deployment_naming_files_vercel_lacks_says_which() -> None:
    """Vercel answers 400 `missing_files` with the SHAs it does not hold; the
    client hands them back so only those are uploaded."""
    from services.deploy.vercel_client import VercelMissingFiles
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.post("https://api.vercel.com/v13/deployments").mock(return_value=Response(
            400, json={"error": {"code": "missing_files", "message": "Missing files", "missing": ["aaa", "bbb"]}}))
        c = VercelClient(token="tk", team_id="tm")
        try:
            with pytest.raises(VercelMissingFiles) as got:
                await c.create_deployment(name="acme", project_id="prj", files=[{"file": "a", "sha": "aaa", "size": 1}])
        finally:
            await c.close()
    assert got.value.missing == ["aaa", "bbb"]


@pytest.mark.asyncio
async def test_any_other_refused_deployment_still_says_why() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.post("https://api.vercel.com/v13/deployments").mock(return_value=Response(
            400, json={"error": {"code": "bad_request", "message": "nope"}}))
        c = VercelClient(token="tk", team_id="tm")
        try:
            with pytest.raises(RuntimeError, match="nope"):
                await c.create_deployment(name="acme", project_id="prj", files=[])
        finally:
            await c.close()


@pytest.mark.asyncio
async def test_a_429_that_says_when_it_resets_is_waited_out(monkeypatch) -> None:
    """DITANS's publish died on `api-upload-paid` (forge-v3, 2026-11-03):
    three short backoffs are nothing to a limit that resets in half a minute."""
    from services.deploy import vercel_client
    clock = [1_800_000_000.0]
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)
        clock[0] += s
    monkeypatch.setattr(vercel_client, "_now", lambda: clock[0])
    monkeypatch.setattr(vercel_client, "_sleep", fake_sleep)
    told: list[str] = []
    async with respx.mock(assert_all_called=True) as rmock:
        route = rmock.post("https://api.vercel.com/v2/files").mock(side_effect=[
            Response(429, headers={"x-ratelimit-reset": str(int(clock[0]) + 30)},
                     json={"error": {"code": "rate_limited", "message": "api-upload-paid"}}),
            Response(200),
        ])
        c = VercelClient(token="tk", team_id="tm")
        try:
            await c.upload_file(sha="abc123", raw=b"hello", on_wait=told.append)
        finally:
            await c.close()
    assert route.call_count == 2
    assert slept == [30.0]
    assert len(told) == 1 and "waiting 30s" in told[0]


@pytest.mark.asyncio
async def test_retry_after_and_the_body_reset_are_read_too(monkeypatch) -> None:
    from services.deploy import vercel_client
    monkeypatch.setattr(vercel_client, "_now", lambda: 1_800_000_000.0)
    assert vercel_client._rate_limit_wait(Response(429, headers={"retry-after": "12"})) == 12.0
    body = {"error": {"code": "rate_limited", "limit": {"reset": 1_800_000_045_000}}}
    assert vercel_client._rate_limit_wait(Response(429, json=body)) == 45.0
    assert vercel_client._rate_limit_wait(Response(429)) is None


@pytest.mark.asyncio
async def test_concurrent_uploads_share_one_pause_and_one_notice(monkeypatch) -> None:
    import asyncio
    from services.deploy import vercel_client
    clock = [1_800_000_000.0]

    async def fake_sleep(s: float) -> None:
        clock[0] += s
        await asyncio.sleep(0)
    monkeypatch.setattr(vercel_client, "_now", lambda: clock[0])
    monkeypatch.setattr(vercel_client, "_sleep", fake_sleep)
    told: list[str] = []
    reset = str(int(clock[0]) + 20)
    async with respx.mock() as rmock:
        rmock.post("https://api.vercel.com/v2/files").mock(side_effect=[
            Response(429, headers={"x-ratelimit-reset": reset}),
            Response(429, headers={"x-ratelimit-reset": reset}),
            Response(429, headers={"x-ratelimit-reset": reset}),
            Response(200), Response(200), Response(200),
        ])
        c = VercelClient(token="tk", team_id="tm")
        try:
            await asyncio.gather(*(c.upload_file(sha=f"s{i}", raw=b"x", on_wait=told.append)
                                   for i in range(3)))
        finally:
            await c.close()
    assert len(told) == 1


@pytest.mark.asyncio
async def test_a_limit_that_resets_too_late_fails_saying_when(monkeypatch) -> None:
    from services.deploy import vercel_client
    clock = 1_800_000_000.0
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)
    monkeypatch.setattr(vercel_client, "_now", lambda: clock)
    monkeypatch.setattr(vercel_client, "_sleep", fake_sleep)
    async with respx.mock() as rmock:
        route = rmock.post("https://api.vercel.com/v2/files").mock(
            return_value=Response(429, headers={"retry-after": "3600"}))
        c = VercelClient(token="tk", team_id="tm")
        try:
            with pytest.raises(RuntimeError, match="status=429.*resets in 3600s.*only the rest"):
                await c.upload_file(sha="abc123", raw=b"hello")
        finally:
            await c.close()
    assert route.call_count == 1 and slept == []

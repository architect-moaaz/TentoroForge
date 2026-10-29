"""Connect Figma: a person signs in to Figma and their own token is kept.

The shared `FIGMA_TOKEN` opens only its owner's files, so a client's project
shared with a tester read as "not found" (2026-10-29). Signing in to Figma
stores the person's token, sealed, against them; the API says which Figma
account is connected and never hands the token back.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

ACCESS = "figu_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
REFRESH = "figur_" + "Z9y8X7w6V5u4T3s2R1q0"


@pytest.fixture()
def figma_app(monkeypatch):
    monkeypatch.setenv("FIGMA_OAUTH_CLIENT_ID", "forge-client")
    monkeypatch.setenv("FIGMA_OAUTH_CLIENT_SECRET", "forge-" + "secret-value")
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "a" * 64)
    asked: list[tuple[str, dict, dict]] = []

    def post(url, data=None, headers=None, **_):
        asked.append((url, dict(data or {}), dict(headers or {})))
        assert url.endswith("/v1/oauth/token")
        if data.get("code") != "the-code":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"user_id_string": "123", "access_token": ACCESS,
                                         "token_type": "bearer", "expires_in": 7776000,
                                         "refresh_token": REFRESH})

    def get(url, headers=None, **_):
        assert url.endswith("/v1/me") and headers == {"Authorization": f"Bearer {ACCESS}"}
        return httpx.Response(200, json={"id": "123", "handle": "Ada Designer", "email": "ada@studio.test"})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    return asked


async def _connect(auth_client, *, popup: bool = True) -> dict[str, list[str]]:
    r = await auth_client.post("/api/me/figma/connect",
                               json={"return_to": "http://localhost:6501/org/o/projects/p", "popup": popup},
                               headers={"origin": "http://localhost:6501"})
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://www.figma.com/oauth"
    return parse_qs(url.query)


@pytest.mark.asyncio
async def test_the_callback_keeps_the_persons_token_sealed_and_says_whose_it_is(auth_client, figma_app):
    assert (await auth_client.get("/api/me/figma")).json() == {"configured": True, "connected": False}

    q = await _connect(auth_client)
    assert q["client_id"] == ["forge-client"] and q["response_type"] == ["code"]
    assert q["scope"] == ["current_user:read,file_content:read"], "read-only scopes, nothing that writes"
    assert q["redirect_uri"] == ["http://test/api/figma/oauth/callback"]

    r = await auth_client.get("/api/figma/oauth/callback", params={"code": "the-code", "state": q["state"][0]})
    assert r.status_code == 200 and "Figma is connected" in r.text
    assert ACCESS not in r.text and REFRESH not in r.text

    # The exchange: Basic client auth, the same redirect address, the code.
    url, form, headers = figma_app[0]
    assert form == {"redirect_uri": "http://test/api/figma/oauth/callback", "code": "the-code",
                    "grant_type": "authorization_code"}
    assert headers["Authorization"].startswith("Basic ")

    status = (await auth_client.get("/api/me/figma")).json()
    assert status["connected"] is True and status["account"] == {"handle": "Ada Designer", "email": "ada@studio.test"}
    assert ACCESS not in str(status)

    from sqlalchemy import select

    from database import async_session
    from models.person_connection import PersonConnection
    from services.platform_integrations_crypto import decrypt

    async with async_session() as db:
        row = (await db.execute(select(PersonConnection))).scalars().one()
    assert ACCESS not in row.access_ct and REFRESH not in (row.refresh_ct or "")
    assert decrypt("figma-oauth", row.access_ct, row.access_iv) == ACCESS
    assert decrypt("figma-oauth", row.refresh_ct, row.refresh_iv) == REFRESH
    assert row.expires_at is not None

    # Disconnect forgets it.
    assert (await auth_client.delete("/api/me/figma")).json() == {"connected": False, "removed": True}
    assert (await auth_client.get("/api/me/figma")).json()["connected"] is False


@pytest.mark.asyncio
async def test_a_state_forge_did_not_issue_is_refused(auth_client, figma_app):
    r = await auth_client.get("/api/figma/oauth/callback", params={"code": "the-code", "state": "forged"})
    assert r.status_code == 400 and "did not issue" in r.text
    assert figma_app == [], "no code was exchanged"


@pytest.mark.asyncio
async def test_a_refused_code_connects_nothing_and_goes_back_to_the_page(auth_client, figma_app):
    q = await _connect(auth_client, popup=False)
    r = await auth_client.get("/api/figma/oauth/callback", params={"code": "stale", "state": q["state"][0]})
    assert r.status_code == 400 and "Figma refused the sign-in (400)" in r.text
    assert "http://localhost:6501/org/o/projects/p?figma=error" in r.text
    assert (await auth_client.get("/api/me/figma")).json()["connected"] is False


@pytest.mark.asyncio
async def test_the_return_address_is_never_another_site(auth_client, figma_app):
    r = await auth_client.post("/api/me/figma/connect", json={"return_to": "https://evil.example/steal"})
    from services.figma.oauth import read_state

    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    assert read_state(state)["return_to"] == ""


@pytest.mark.asyncio
async def test_without_an_oauth_app_the_person_is_told_to_paste_a_token(auth_client, monkeypatch):
    monkeypatch.delenv("FIGMA_OAUTH_CLIENT_ID", raising=False)
    r = await auth_client.post("/api/me/figma/connect", json={})
    assert r.status_code == 503 and "Paste a Figma access token instead" in r.json()["detail"]
    assert (await auth_client.get("/api/me/figma")).json() == {"configured": False, "connected": False}

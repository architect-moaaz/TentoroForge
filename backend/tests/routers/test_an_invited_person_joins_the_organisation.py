"""Inviting somebody from the organisation's settings made a pending row and
nothing else: no email, no accept button anywhere, and the members list asked
a route that did not exist. Now: a person with an account joins at once; a
person without one is sent (or handed) the sign-up address and joins at the
sign-in after their sign-up; the list shows members and invitations."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


async def _fresh():
    from main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_an_account_holder_joins_at_once_and_a_newcomer_joins_when_they_sign_up(auth_client, org_id):
    async with await _fresh() as other:
        r = await other.post("/api/auth/signup", json={"email": "ann@example.com", "name": "Ann Lee", "password": "Testpass123"})
        assert r.status_code == 201
        ann_token = r.json()["access_token"]

    # Somebody with an account: a member the moment they are invited.
    r = await auth_client.post(f"/api/orgs/{org_id}/invite", json={"email": "Ann@example.com", "role": "admin"},
                               headers={"origin": "https://forge-v3.tentoro.ai"})
    assert r.status_code == 201, r.text
    assert r.json()["joined"] is True and r.json()["invite_status"] == "accepted" and r.json()["invite_url"] == ""
    async with await _fresh() as ann:
        ann.headers["Authorization"] = f"Bearer {ann_token}"
        assert [o["id"] for o in (await ann.get("/api/orgs")).json()] == [org_id]
    assert (await auth_client.post(f"/api/orgs/{org_id}/invite", json={"email": "ann@example.com"})).status_code == 409

    # Somebody without one: the sign-up address, pending until they sign up.
    r = await auth_client.post(f"/api/orgs/{org_id}/invite", json={"email": "Zed@example.com", "role": "member"},
                               headers={"origin": "https://forge-v3.tentoro.ai"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["joined"] is False and body["invite_status"] == "pending"
    assert body["invite_url"] == "https://forge-v3.tentoro.ai/signup?email=zed%40example.com"
    assert body["emailed"] is True  # the development mailer takes it; with no provider it is False and the address is the answer

    rows = (await auth_client.get(f"/api/orgs/{org_id}/members")).json()
    assert {(m["email"], m["invite_status"]) for m in rows} == {
        ("test@example.com", "accepted"), ("ann@example.com", "accepted"), ("zed@example.com", "pending")}
    assert next(m for m in rows if m["email"] == "ann@example.com")["name"] == "Ann Lee"

    # Resending hands the address back again; then Zed signs up with that email and is in.
    r = await auth_client.post(f"/api/orgs/{org_id}/invite/{body['id']}/resend", headers={"origin": "https://forge-v3.tentoro.ai"})
    assert r.status_code == 200 and r.json()["invite_url"].endswith("/signup?email=zed%40example.com")
    async with await _fresh() as zed:
        r = await zed.post("/api/auth/signup", json={"email": "zed@example.com", "name": "Zed", "password": "Testpass123"})
        assert r.status_code == 201
        zed.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        assert [o["id"] for o in (await zed.get("/api/orgs")).json()] == [org_id]
    rows = (await auth_client.get(f"/api/orgs/{org_id}/members")).json()
    zed_row = next(m for m in rows if m["email"] == "zed@example.com")
    assert zed_row["invite_status"] == "accepted" and zed_row["user_id"] and zed_row["role"] == "member"


@pytest.mark.asyncio
async def test_an_invitation_can_be_withdrawn_and_only_by_an_admin(auth_client, org_id):
    r = await auth_client.post(f"/api/orgs/{org_id}/invite", json={"email": "late@example.com"})
    invite_id = r.json()["id"]
    assert r.json()["invite_url"] == ""  # no Origin and no FORGE_PUBLIC_URL: nothing to hand on
    async with await _fresh() as outsider:
        r = await outsider.post("/api/auth/signup", json={"email": "out@example.com", "name": "Out", "password": "Testpass123"})
        outsider.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        assert (await outsider.delete(f"/api/orgs/{org_id}/invite/{invite_id}")).status_code == 403
    assert (await auth_client.delete(f"/api/orgs/{org_id}/invite/{invite_id}")).status_code == 204
    assert (await auth_client.delete(f"/api/orgs/{org_id}/invite/{invite_id}")).status_code == 404
    assert "late@example.com" not in {m["email"] for m in (await auth_client.get(f"/api/orgs/{org_id}/members")).json()}

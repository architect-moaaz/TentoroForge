"""Somebody who signed up because they were invited picks "I'm joining a
team" and must see the team; somebody nobody invited must be told so rather
than shown an empty page. One route answers both, from the sign-in email."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


async def _fresh():
    from main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_my_invitations_name_the_teams_i_joined_and_the_ones_still_waiting(auth_client, org_id):
    # The owner's own organisation: a membership, not an invitation.
    mine = (await auth_client.get("/api/me/invitations")).json()
    assert mine["email"] == "test@example.com" and mine["pending"] == []
    assert [(m["slug"], m["role"], m["invited"]) for m in mine["memberships"]] == [("test-org", "owner", False)]

    # Zed is invited before having an account; signing up takes the invitation up.
    await auth_client.post(f"/api/orgs/{org_id}/invite", json={"email": "zed@example.com", "role": "admin"})
    async with await _fresh() as zed:
        r = await zed.post("/api/auth/signup", json={"email": "zed@example.com", "name": "Zed", "password": "Testpass123"})
        zed.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        waiting = (await zed.get("/api/me/invitations")).json()
        assert waiting["pending"] == []
        assert [(m["slug"], m["role"], m["invited"]) for m in waiting["memberships"]] == [("test-org", "admin", True)]

    # Nobody invited Out: nothing to show, and the route says so plainly.
    async with await _fresh() as out:
        r = await out.post("/api/auth/signup", json={"email": "out@example.com", "name": "Out", "password": "Testpass123"})
        out.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        nothing = (await out.get("/api/me/invitations")).json()
        assert nothing == {"email": "out@example.com", "memberships": [], "pending": []}

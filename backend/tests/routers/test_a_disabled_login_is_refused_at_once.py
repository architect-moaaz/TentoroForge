"""A login the cockpit disables is refused on its very next request — its
access token is still valid by the clock, so the refusal lives where every
token is checked — at sign-in, and at refresh; enabling it restores
everything. A super admin cannot disable their own login."""
from __future__ import annotations

import pytest


async def _person_id(auth_client) -> str:
    return (await auth_client.get("/api/auth/me")).json()["id"]


@pytest.mark.asyncio
async def test_a_disabled_login_fails_its_next_request_and_sign_in_and_refresh(auth_client, super_admin_client, client):
    pid = await _person_id(auth_client)
    login = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "Testpass123"})
    refresh_token = login.json()["refresh_token"]

    r = await super_admin_client.post(f"/api/admin/people/{pid}/disable", json={"reason": "left the company"})
    assert r.status_code == 200, r.text
    assert r.json()["disabled_at"] and r.json()["disabled_reason"] == "left the company"

    # The token in hand is refused at once.
    r = await auth_client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["detail"] == "This login has been disabled"
    # A fresh sign-in with the right password is refused, in those words.
    r = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "Testpass123"})
    assert r.status_code == 401 and r.json()["detail"] == "This login has been disabled"
    # And a refresh of the old pair.
    r = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 401

    r = await super_admin_client.post(f"/api/admin/people/{pid}/enable")
    assert r.status_code == 200 and r.json()["disabled_at"] is None
    assert (await auth_client.get("/api/auth/me")).status_code == 200
    assert (await client.post("/api/auth/login", json={"email": "test@example.com", "password": "Testpass123"})).status_code == 200


@pytest.mark.asyncio
async def test_disabling_twice_or_enabling_an_enabled_login_is_said(auth_client, super_admin_client):
    pid = await _person_id(auth_client)
    assert (await super_admin_client.post(f"/api/admin/people/{pid}/enable")).status_code == 409
    assert (await super_admin_client.post(f"/api/admin/people/{pid}/disable", json={"reason": "a reason"})).status_code == 200
    assert (await super_admin_client.post(f"/api/admin/people/{pid}/disable", json={"reason": "again"})).status_code == 409


@pytest.mark.asyncio
async def test_a_reason_is_required_and_the_super_admin_cannot_disable_themselves(super_admin_client, auth_client):
    pid = await _person_id(auth_client)
    assert (await super_admin_client.post(f"/api/admin/people/{pid}/disable", json={"reason": ""})).status_code == 422
    me = (await super_admin_client.get("/api/auth/me")).json()["id"]
    r = await super_admin_client.post(f"/api/admin/people/{me}/disable", json={"reason": "oops"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_the_people_list_shows_who_is_disabled_and_when_they_signed_in(super_admin_client, auth_client):
    pid = await _person_id(auth_client)
    await super_admin_client.post(f"/api/admin/people/{pid}/disable", json={"reason": "gone"})
    r = await super_admin_client.get("/api/admin/people", params={"q": "test@example"})
    assert r.status_code == 200
    rows = r.json()["items"]
    assert len(rows) == 1 and rows[0]["disabled_reason"] == "gone" and rows[0]["last_sign_in_at"]
    assert r.json()["total"] == 1

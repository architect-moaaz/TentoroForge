"""The super admin is made the ordinary way: the email the platform's
configuration names (`FORGE_SUPER_ADMIN_EMAILS`, `admin@tentoro.ai` by
default) takes the role the moment that account signs up or signs in. Nobody
types a password into a seed, and any other email stays what it was."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_signing_up_with_the_listed_email_takes_the_role(client, monkeypatch):
    monkeypatch.setenv("FORGE_SUPER_ADMIN_EMAILS", "boss@example.com, admin@tentoro.ai")
    r = await client.post("/api/auth/signup", json={"email": "boss@example.com", "name": "Boss", "password": "Bosspass123"})
    assert r.status_code == 201, r.text
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["platform_role"] == "super_admin"
    assert me.json()["disabled"] is False
    assert me.json()["impersonated_by"] is None


@pytest.mark.asyncio
async def test_an_unlisted_email_stays_an_ordinary_login(auth_client):
    me = await auth_client.get("/api/auth/me")
    assert me.json()["platform_role"] is None
    r = await auth_client.get("/api/admin/overview")
    assert r.status_code == 403
    assert "Super admin" in r.json()["detail"]


@pytest.mark.asyncio
async def test_an_existing_login_takes_the_role_at_its_next_sign_in(client, monkeypatch):
    monkeypatch.setenv("FORGE_SUPER_ADMIN_EMAILS", "nobody@example.com")
    r = await client.post("/api/auth/signup", json={"email": "later@example.com", "name": "Later", "password": "Laterpass123"})
    assert r.status_code == 201
    token = r.json()["access_token"]
    assert (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).json()["platform_role"] is None

    # The configuration names them afterwards; the next sign-in bootstraps.
    monkeypatch.setenv("FORGE_SUPER_ADMIN_EMAILS", "later@example.com")
    r = await client.post("/api/auth/login", json={"email": "later@example.com", "password": "Laterpass123"})
    assert r.status_code == 200
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.json()["platform_role"] == "super_admin"
    # And the cockpit opens, with the bootstrap on the record.
    r = await client.get("/api/admin/audit", headers=headers)
    assert r.status_code == 200
    assert any(row["action"] == "super_admin.bootstrap" for row in r.json())


@pytest.mark.asyncio
async def test_the_default_listed_email_is_admin_at_tentoro(client, monkeypatch):
    monkeypatch.delenv("FORGE_SUPER_ADMIN_EMAILS", raising=False)
    r = await client.post("/api/auth/signup", json={"email": "admin@tentoro.ai", "name": "Admin", "password": "Adminpass123"})
    assert r.status_code == 201
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["platform_role"] == "super_admin"

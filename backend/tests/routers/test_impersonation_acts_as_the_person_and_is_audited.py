"""A super admin acts as a person on a token that names them both. Every
route sees the person; every write made under it is on the record with the
admin's own name beside the person's; the person's organisation can read
that record; the cockpit is closed under it; it has no refresh and it
expires. Never another super admin, never a disabled login."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt


async def _person(auth_client) -> dict:
    return (await auth_client.get("/api/auth/me")).json()


async def _impersonate(super_admin_client, person_id: str) -> dict:
    r = await super_admin_client.post(f"/api/admin/people/{person_id}/impersonate")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_the_token_serves_the_person_and_names_the_admin(auth_client, super_admin_client, client, org_id):
    person = await _person(auth_client)
    grant = await _impersonate(super_admin_client, person["id"])
    assert grant["default_org_id"] == org_id and "refresh_token" not in grant
    claims = jwt.get_unverified_claims(grant["access_token"])
    assert claims["sub"] == person["id"] and claims["act"] == (await super_admin_client.get("/api/auth/me")).json()["id"]

    headers = {"Authorization": f"Bearer {grant['access_token']}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["id"] == person["id"]
    assert me.json()["impersonated_by"]["email"] == "admin@tentoro.ai"
    # The person's organisation opens for the token as it does for them.
    assert (await client.get(f"/api/orgs/{org_id}", headers=headers)).status_code == 200
    # The cockpit does not.
    r = await client.get("/api/admin/overview", headers=headers)
    assert r.status_code == 403 and "impersonating" in r.json()["detail"]


@pytest.mark.asyncio
async def test_every_write_under_the_token_is_on_the_record_for_the_org_too(auth_client, super_admin_client, client, org_id):
    person = await _person(auth_client)
    grant = await _impersonate(super_admin_client, person["id"])
    headers = {"Authorization": f"Bearer {grant['access_token']}"}

    r = await client.post(f"/api/orgs/{org_id}/departments", json={"name": "Made while impersonated"}, headers=headers)
    assert r.status_code == 201, r.text

    admin_id = (await super_admin_client.get("/api/auth/me")).json()["id"]
    rows = (await super_admin_client.get("/api/admin/audit", params={"actor_user_id": admin_id})).json()
    actions = [row["action"] for row in rows]
    assert "impersonation.start" in actions and "impersonated_request" in actions
    start = next(row for row in rows if row["action"] == "impersonation.start")
    assert start["resource_id"] == person["id"] and start["org_id"] == org_id
    made = next(row for row in rows if row["action"] == "impersonated_request")
    assert made["resource_id"] == f"POST /api/orgs/{org_id}/departments"
    assert made["user_id"] == person["id"] and made["actor_user_id"] == admin_id
    assert made["org_id"] == org_id and made["changes"]["status"] == 201

    # The organisation's owner reads the same rows through the ordinary trail.
    own = (await auth_client.get("/api/audit", params={"org_id": org_id})).json()
    assert any(row["action"] == "impersonated_request" for row in own)
    # A read leaves no row.
    before = len((await super_admin_client.get("/api/admin/audit")).json())
    await client.get(f"/api/orgs/{org_id}", headers=headers)
    assert len((await super_admin_client.get("/api/admin/audit")).json()) == before


@pytest.mark.asyncio
async def test_an_expired_or_orphaned_token_is_refused(auth_client, super_admin_client, client, org_id, monkeypatch):
    person = await _person(auth_client)
    admin = (await super_admin_client.get("/api/auth/me")).json()
    from auth import JWT_ALGORITHM, SECRET_KEY
    expired = jwt.encode({"sub": person["id"], "act": admin["id"], "type": "access", "jti": "x",
                          "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, SECRET_KEY, algorithm=JWT_ALGORITHM)
    assert (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})).status_code == 401

    grant = await _impersonate(super_admin_client, person["id"])
    headers = {"Authorization": f"Bearer {grant['access_token']}"}
    # The admin behind the token loses the role (a second admin revokes it).
    r = await client.post("/api/auth/signup", json={"email": "second@tentoro.ai", "name": "Second", "password": "Secondpass1"})
    monkeypatch.setenv("FORGE_SUPER_ADMIN_EMAILS", "admin@tentoro.ai,second@tentoro.ai")
    r = await client.post("/api/auth/login", json={"email": "second@tentoro.ai", "password": "Secondpass1"})
    second = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.delete(f"/api/admin/people/{admin['id']}/super-admin", headers=second)).status_code == 200
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "Impersonation no longer valid"


@pytest.mark.asyncio
async def test_not_another_super_admin_not_a_disabled_login_not_oneself(auth_client, super_admin_client):
    person = await _person(auth_client)
    admin = (await super_admin_client.get("/api/auth/me")).json()
    assert (await super_admin_client.post(f"/api/admin/people/{admin['id']}/impersonate")).status_code == 400
    await super_admin_client.post(f"/api/admin/people/{person['id']}/disable", json={"reason": "gone"})
    assert (await super_admin_client.post(f"/api/admin/people/{person['id']}/impersonate")).status_code == 409
    await super_admin_client.post(f"/api/admin/people/{person['id']}/enable")
    await super_admin_client.post(f"/api/admin/people/{person['id']}/super-admin")
    assert (await super_admin_client.post(f"/api/admin/people/{person['id']}/impersonate")).status_code == 403

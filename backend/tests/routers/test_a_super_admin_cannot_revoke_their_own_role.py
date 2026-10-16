"""The role is granted and revoked from the cockpit, never to oneself: the
last super admin cannot lock everyone out. Nobody else reaches the cockpit."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_grant_and_revoke_another_person_never_oneself(super_admin_client, auth_client):
    me = (await super_admin_client.get("/api/auth/me")).json()["id"]
    other = (await auth_client.get("/api/auth/me")).json()["id"]

    r = await super_admin_client.delete(f"/api/admin/people/{me}/super-admin")
    assert r.status_code == 400 and "own platform role" in r.json()["detail"]
    assert (await super_admin_client.post(f"/api/admin/people/{me}/super-admin")).status_code == 400

    r = await super_admin_client.post(f"/api/admin/people/{other}/super-admin")
    assert r.status_code == 200 and r.json()["platform_role"] == "super_admin"
    assert (await auth_client.get("/api/admin/overview")).status_code == 200
    assert (await super_admin_client.post(f"/api/admin/people/{other}/super-admin")).status_code == 409

    r = await super_admin_client.delete(f"/api/admin/people/{other}/super-admin")
    assert r.status_code == 200 and r.json()["platform_role"] is None
    assert (await auth_client.get("/api/admin/overview")).status_code == 403
    assert (await super_admin_client.delete(f"/api/admin/people/{other}/super-admin")).status_code == 409


@pytest.mark.asyncio
async def test_every_cockpit_route_is_closed_to_an_ordinary_login(auth_client, org_id):
    me = (await auth_client.get("/api/auth/me")).json()["id"]
    closed = [
        ("get", "/api/admin/overview", None),
        ("get", "/api/admin/people", None),
        ("get", "/api/admin/orgs", None),
        ("get", "/api/admin/apps", None),
        ("get", "/api/admin/audit", None),
        ("post", f"/api/admin/people/{me}/disable", {"reason": "x"}),
        ("post", f"/api/admin/orgs/{org_id}/block", {"reason": "x"}),
        ("get", f"/api/admin/orgs/{org_id}/members", None),
    ]
    for method, path, body in closed:
        r = await getattr(auth_client, method)(path, json=body) if body is not None else await getattr(auth_client, method)(path)
        assert r.status_code == 403, (path, r.status_code, r.text)


@pytest.mark.asyncio
async def test_the_overview_counts_the_platform(super_admin_client, auth_client, org_id):
    r = await super_admin_client.get("/api/admin/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["people"] == 2 and body["super_admins"] == 1 and body["orgs"]["active"] == 1
    assert body["orgs"]["blocked"] == 0 and body["disabled_logins"] == 0

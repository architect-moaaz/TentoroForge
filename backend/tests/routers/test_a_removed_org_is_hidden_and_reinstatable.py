"""Block, remove, reinstate. A blocked organisation refuses its members with
its own words and stays listed with its status; a removed one is gone from
every list and answers 404, its data kept; reinstating undoes either. The
cockpit says which moves are allowed from where."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_a_blocked_org_refuses_its_members_and_says_why(auth_client, super_admin_client, org_id):
    assert (await auth_client.get(f"/api/orgs/{org_id}")).status_code == 200

    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/block", json={"reason": "unpaid"})
    assert r.status_code == 200 and r.json()["status"] == "blocked" and r.json()["status_reason"] == "unpaid"

    r = await auth_client.get(f"/api/orgs/{org_id}")
    assert r.status_code == 403 and r.json()["detail"] == "Organisation is blocked"
    assert (await auth_client.get(f"/api/orgs/{org_id}/people")).status_code == 403
    assert (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Nope"})).status_code == 403

    # Signed in still, and told which of their organisations is blocked.
    me = await auth_client.get("/api/auth/me")
    assert me.status_code == 200
    assert [o["status"] for o in me.json()["orgs"] if o["org_id"] == org_id] == ["blocked"]
    listed = await auth_client.get("/api/orgs")
    assert [o["status"] for o in listed.json()] == ["blocked"]

    assert (await super_admin_client.post(f"/api/admin/orgs/{org_id}/block", json={"reason": "again"})).status_code == 409
    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/reinstate")
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["status_reason"] is None
    assert (await auth_client.get(f"/api/orgs/{org_id}")).status_code == 200


@pytest.mark.asyncio
async def test_a_removed_org_is_hidden_and_comes_back_whole(auth_client, super_admin_client, org_id):
    made = await auth_client.post(f"/api/orgs/{org_id}/departments", json={"name": "Finance"})
    assert made.status_code == 201, made.text

    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/remove", json={"reason": "churned"})
    assert r.status_code == 200 and r.json()["status"] == "removed"

    assert (await auth_client.get(f"/api/orgs/{org_id}")).status_code == 404
    assert (await auth_client.get("/api/orgs")).json() == []
    assert (await auth_client.get("/api/auth/me")).json()["orgs"] == []
    # The cockpit still sees it, by status.
    r = await super_admin_client.get("/api/admin/orgs", params={"status": "removed"})
    assert [o["id"] for o in r.json()["items"]] == [org_id]
    assert (await super_admin_client.post(f"/api/admin/orgs/{org_id}/remove", json={"reason": "a reason"})).status_code == 409

    assert (await super_admin_client.post(f"/api/admin/orgs/{org_id}/reinstate")).status_code == 200
    depts = await auth_client.get(f"/api/orgs/{org_id}/departments")
    assert depts.status_code == 200 and [d["name"] for d in depts.json()] == ["Finance"]


@pytest.mark.asyncio
async def test_an_outsider_learns_nothing_from_a_block(super_admin_client, auth_client, client, org_id):
    r = await client.post("/api/auth/signup", json={"email": "outsider@example.com", "name": "Out", "password": "Outsider123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/block", json={"reason": "unpaid"})
    r = await client.get(f"/api/orgs/{org_id}", headers=headers)
    assert r.status_code == 403 and r.json()["detail"] == "Not a member of this organization"


@pytest.mark.asyncio
async def test_every_status_change_is_on_the_record(super_admin_client, auth_client, org_id):
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/block", json={"reason": "unpaid"})
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/reinstate")
    rows = (await super_admin_client.get("/api/admin/audit", params={"org_id": org_id})).json()
    assert {r["action"] for r in rows} == {"org.active", "org.blocked"}
    assert next(r for r in rows if r["action"] == "org.blocked")["changes"]["reason"] == "unpaid"
    # The organisation's own owner sees the same trail.
    mine = (await auth_client.get("/api/audit")).json()
    assert {r["action"] for r in mine} >= {"org.blocked", "org.active"}

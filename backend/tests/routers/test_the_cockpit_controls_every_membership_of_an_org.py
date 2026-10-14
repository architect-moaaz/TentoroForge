"""Who may do what in an organisation is the cockpit's to change: add a
person (an account joins at once, an unknown email gets a pending invite with
no placeholder user), change a role, remove, hand ownership over, see,
cancel and resend invites — and an organisation keeps at least one owner."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_a_person_with_an_account_joins_at_once_and_an_unknown_email_is_invited(super_admin_client, auth_client, client, org_id):
    await client.post("/api/auth/signup", json={"email": "known@example.com", "name": "Known", "password": "Knownpass1"})

    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/members", json={"email": "known@example.com", "role": "admin"})
    assert r.status_code == 201, r.text
    assert r.json()["invite_status"] == "accepted" and r.json()["role"] == "admin" and r.json()["user_id"]
    assert (await super_admin_client.post(f"/api/admin/orgs/{org_id}/members", json={"email": "known@example.com"})).status_code == 409

    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/members", json={"email": "new@example.com"})
    assert r.status_code == 201
    assert r.json()["invite_status"] == "pending" and r.json()["user_id"] is None and r.json()["email"] == "new@example.com"
    # A second invite from the same organisation does not trip the old placeholder.
    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/members", json={"email": "another@example.com"})
    assert r.status_code == 201

    members = (await super_admin_client.get(f"/api/admin/orgs/{org_id}/members")).json()
    assert sorted(m["email"] for m in members) == ["another@example.com", "known@example.com", "new@example.com", "test@example.com"]
    invites = (await super_admin_client.get(f"/api/admin/orgs/{org_id}/invites")).json()
    assert sorted(i["email"] for i in invites) == ["another@example.com", "new@example.com"]

    # The person signs up and accepts: the row becomes theirs.
    r = await client.post("/api/auth/signup", json={"email": "new@example.com", "name": "New", "password": "Newpass123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    invite_id = next(i["id"] for i in invites if i["email"] == "new@example.com")
    assert (await client.post(f"/api/orgs/{org_id}/invite/{invite_id}/accept", headers=headers)).status_code == 200
    assert (await client.get(f"/api/orgs/{org_id}", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_invites_are_cancelled_and_resent(super_admin_client, org_id):
    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/members", json={"email": "late@example.com"})
    invite_id = r.json()["id"]
    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/invites/{invite_id}/resend")
    assert r.status_code == 200 and r.json()["accept_path"] == f"/api/orgs/{org_id}/invite/{invite_id}/accept"
    assert (await super_admin_client.delete(f"/api/admin/orgs/{org_id}/invites/{invite_id}")).status_code == 200
    assert (await super_admin_client.get(f"/api/admin/orgs/{org_id}/invites")).json() == []
    assert (await super_admin_client.delete(f"/api/admin/orgs/{org_id}/invites/{invite_id}")).status_code == 404


@pytest.mark.asyncio
async def test_roles_change_ownership_moves_and_the_last_owner_stays(super_admin_client, auth_client, client, org_id):
    owner = (await auth_client.get("/api/auth/me")).json()["id"]
    r = await client.post("/api/auth/signup", json={"email": "member@example.com", "name": "Member", "password": "Memberpass1"})
    member_id = (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})).json()["id"]
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/members", json={"email": "member@example.com"})

    # The only owner cannot step down or be removed.
    assert (await super_admin_client.patch(f"/api/admin/orgs/{org_id}/members/{owner}", json={"role": "member"})).status_code == 409
    assert (await super_admin_client.delete(f"/api/admin/orgs/{org_id}/members/{owner}")).status_code == 409

    r = await super_admin_client.patch(f"/api/admin/orgs/{org_id}/members/{member_id}", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"

    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/transfer-ownership", json={"user_id": member_id})
    assert r.status_code == 200
    roles = {m["email"]: m["role"] for m in r.json()}
    assert roles == {"test@example.com": "admin", "member@example.com": "owner"}

    # Now the old owner can go.
    assert (await super_admin_client.delete(f"/api/admin/orgs/{org_id}/members/{owner}")).status_code == 200
    assert (await auth_client.get(f"/api/orgs/{org_id}")).status_code == 403
    rows = (await super_admin_client.get("/api/admin/audit", params={"org_id": org_id})).json()
    assert {r["action"] for r in rows} >= {"org.member_add", "org.member_role", "org.transfer_ownership", "org.member_remove"}

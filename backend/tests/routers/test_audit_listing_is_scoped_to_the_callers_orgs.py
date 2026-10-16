"""The audit trail used to answer every row to any signed-in person. A super
admin reads everything; everyone else reads what is about them and what
concerns the organisations they own or administer — nothing of a stranger's."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_a_person_reads_their_own_rows_and_their_orgs_rows_only(auth_client, super_admin_client, client, org_id):
    # Rows about the person's org, and rows about a stranger's.
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/block", json={"reason": "theirs"})
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/reinstate")
    r = await client.post("/api/auth/signup", json={"email": "stranger@example.com", "name": "S", "password": "Stranger123"})
    stranger = {"Authorization": f"Bearer {r.json()['access_token']}"}
    other = (await client.post("/api/orgs", json={"name": "Other Org", "slug": "other-org"}, headers=stranger)).json()["id"]
    await super_admin_client.post(f"/api/admin/orgs/{other}/block", json={"reason": "not theirs"})

    mine = (await auth_client.get("/api/audit")).json()
    assert mine and all(row["org_id"] in (org_id, None) for row in mine)
    assert not any(row["changes"] and row["changes"].get("reason") == "not theirs" for row in mine)

    theirs = (await client.get("/api/audit", headers=stranger)).json()
    assert any(row["changes"] and row["changes"].get("reason") == "not theirs" for row in theirs)
    assert not any(row["changes"] and row["changes"].get("reason") == "theirs" for row in theirs)

    everything = (await super_admin_client.get("/api/audit")).json()
    reasons = {row["changes"].get("reason") for row in everything if row["changes"]}
    assert {"theirs", "not theirs"} <= reasons


@pytest.mark.asyncio
async def test_the_cockpit_trail_filters_by_actor_org_and_action(auth_client, super_admin_client, org_id):
    admin = (await super_admin_client.get("/api/auth/me")).json()["id"]
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/block", json={"reason": "a reason"})
    rows = (await super_admin_client.get("/api/admin/audit", params={"actor_user_id": admin, "action": "org."})).json()
    assert rows and all(row["actor_user_id"] == admin and row["action"].startswith("org.") for row in rows)
    rows = (await super_admin_client.get("/api/admin/audit", params={"org_id": org_id})).json()
    assert all(row["org_id"] == org_id for row in rows)

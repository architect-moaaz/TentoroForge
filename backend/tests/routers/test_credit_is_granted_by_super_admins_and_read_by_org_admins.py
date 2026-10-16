"""Credit is the cockpit's to grant: signed entries with a reason, an
opening balance once, limits per scope and period, every move on the
record. An organisation's admins read their own organisation's balance and
spend and nobody else's; platform-wide figures are the super admin's."""
from __future__ import annotations

import json
import time

import pytest


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("FORGE_USAGE_LOG", str(path))
    return path


@pytest.mark.asyncio
async def test_entries_move_the_balance_and_need_a_reason(super_admin_client, auth_client, org_id, ledger):
    base = f"/api/admin/credits/orgs/{org_id}/entries"
    assert (await super_admin_client.post(base, json={"amount_usd": -5, "kind": "adjustment", "note": "no"})).status_code == 422
    assert (await super_admin_client.post(base, json={"amount_usd": 0, "kind": "top_up", "note": "nothing"})).status_code == 422
    assert (await super_admin_client.post(base, json={"amount_usd": -5, "kind": "top_up", "note": "wrong sign"})).status_code == 400

    r = await super_admin_client.post(base, json={"amount_usd": 100, "kind": "opening", "note": "October credit"})
    assert r.status_code == 201 and r.json()["balance"]["balance_usd"] == 100.0 and r.json()["by_email"] == "admin@tentoro.ai"
    assert (await super_admin_client.post(base, json={"amount_usd": 1, "kind": "opening", "note": "again"})).status_code == 400
    r = await super_admin_client.post(base, json={"amount_usd": -30, "kind": "adjustment", "note": "mis-posted"})
    assert r.status_code == 201 and r.json()["balance"]["balance_usd"] == 70.0

    history = (await super_admin_client.get(base)).json()
    assert [e["amount"] for e in history["entries"]] == [-30.0, 100.0] and history["balance"]["known"]
    rows = (await super_admin_client.get("/api/admin/audit", params={"org_id": org_id, "action": "credit."})).json()
    assert len(rows) == 2 and {r["changes"]["note"] for r in rows} == {"October credit", "mis-posted"}

    listed = (await super_admin_client.get("/api/admin/credits/orgs")).json()
    mine = next(o for o in listed["orgs"] if o["org_id"] == org_id)
    assert mine["balance_usd"] == 70.0 and mine["entries"] == 2 and mine["last_entry"]["kind"] == "adjustment"


@pytest.mark.asyncio
async def test_limits_are_one_row_per_scope_and_period_and_clear_when_emptied(super_admin_client, org_id):
    r = await super_admin_client.put("/api/admin/credits/limits",
                                     json={"scope_kind": "org", "scope_id": org_id, "day": 2, "month": 50})
    assert r.status_code == 200 and r.json()["limits"] == {"day": 2.0, "month": 50.0} and r.json()["name"] == "Test Org"
    r = await super_admin_client.put("/api/admin/credits/limits",
                                     json={"scope_kind": "org", "scope_id": org_id, "day": 3, "month": None})
    assert r.json()["limits"] == {"day": 3.0}
    assert [l["period"] for l in (await super_admin_client.get("/api/admin/credits/limits")).json()] == ["day"]
    assert (await super_admin_client.put("/api/admin/credits/limits", json={"scope_kind": "org", "scope_id": "nope"})).status_code == 404
    assert (await super_admin_client.put("/api/admin/credits/limits", json={"scope_kind": "platform", "week": -1})).status_code == 400
    r = await super_admin_client.put("/api/admin/credits/limits", json={"scope_kind": "platform", "week": 500})
    assert r.status_code == 200
    standing = (await super_admin_client.get("/api/admin/credits/standing")).json()
    assert standing["platform_limits"] == {"week": 500.0} and standing["orgs"] == 1 and standing["orgs_known"] == 0


@pytest.mark.asyncio
async def test_org_admins_read_their_own_organisation_only(super_admin_client, auth_client, client, org_id, ledger):
    await super_admin_client.post(f"/api/admin/credits/orgs/{org_id}/entries",
                                  json={"amount_usd": 20, "kind": "opening", "note": "opening balance"})
    r = await auth_client.get(f"/api/orgs/{org_id}/spend")
    assert r.status_code == 200 and r.json()["balance"]["balance_usd"] == 20.0 and "report" in r.json()

    r = await client.post("/api/auth/signup", json={"email": "other@example.com", "name": "O", "password": "Otherpass1"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"/api/orgs/{org_id}/spend", headers=other)).status_code == 403
    for path in ("/api/admin/credits/orgs", "/api/usage/summary", "/api/usage/platform-patches", "/api/spend/report"):
        assert (await auth_client.get(path)).status_code == 403, path
    assert (await auth_client.get("/api/spend/report", params={"org": org_id})).status_code == 200
    assert (await auth_client.get("/api/spend/report", params={"person": "me"})).status_code == 200
    assert (await super_admin_client.get("/api/usage/summary")).status_code == 200

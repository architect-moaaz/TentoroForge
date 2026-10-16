"""The super admin switches a feature for one organisation, or its default
for every organisation without a setting of its own; an organisation's own
setting beats the platform's; clearing a setting restores what is beneath
it; every change carries a reason and lands on the record."""
from __future__ import annotations

import pytest

TEMPLATE = "/api/orgs/{org}/projects/from-template"


async def _templates_answer(auth_client, org_id) -> int:
    """422 when the door is open (the body is empty on purpose), 403 when shut."""
    return (await auth_client.post(TEMPLATE.format(org=org_id), json={})).status_code


@pytest.mark.asyncio
async def test_an_organisations_setting_shuts_a_door_and_is_audited(super_admin_client, auth_client, org_id):
    # The Drafts Room is off by default; the super admin opens it platform-wide first.
    assert (await auth_client.get(f"/api/orgs/{org_id}/drafts-room")).status_code == 403
    r = await super_admin_client.put("/api/admin/features/drafts_room", json={"enabled": True, "reason": "opened for everyone"})
    assert r.status_code == 200
    assert (await auth_client.get(f"/api/orgs/{org_id}/drafts-room")).status_code == 200
    r = await super_admin_client.put(f"/api/admin/orgs/{org_id}/features/drafts_room",
                                     json={"enabled": False, "reason": "contract excludes the Drafts Room"})
    assert r.status_code == 200
    row = next(f for f in r.json()["features"] if f["key"] == "drafts_room")
    assert row["enabled"] is False and row["source"] == "org" and row["override"]["by_email"] == "admin@tentoro.ai"

    r = await auth_client.get(f"/api/orgs/{org_id}/drafts-room")
    assert r.status_code == 403 and r.json()["detail"] == "Drafts Room is not enabled for your organisation. Ask the platform administrator."
    mine = (await auth_client.get(f"/api/orgs/{org_id}/features")).json()["features"]["drafts_room"]
    assert mine["enabled"] is False and mine["source"] == "org" and "reason" not in mine

    rows = (await super_admin_client.get("/api/admin/audit", params={"org_id": org_id, "action": "feature."})).json()
    assert len(rows) == 1 and rows[0]["action"] == "feature.org" and rows[0]["changes"]["reason"] == "contract excludes the Drafts Room"

    # Clearing the setting opens the door again: the platform's setting applies.
    r = await super_admin_client.put(f"/api/admin/orgs/{org_id}/features/drafts_room",
                                     json={"enabled": None, "reason": "contract renewed"})
    assert next(f for f in r.json()["features"] if f["key"] == "drafts_room")["source"] == "platform"
    assert (await auth_client.get(f"/api/orgs/{org_id}/drafts-room")).status_code == 200


@pytest.mark.asyncio
async def test_the_platform_default_applies_where_an_organisation_has_no_setting(super_admin_client, auth_client, org_id):
    assert await _templates_answer(auth_client, org_id) == 422
    r = await super_admin_client.put("/api/admin/features/templates", json={"enabled": False, "reason": "templates paused platform-wide"})
    assert r.status_code == 200 and r.json()["enabled_by_default"] is False
    assert await _templates_answer(auth_client, org_id) == 403

    # The organisation's own setting beats the platform's.
    await super_admin_client.put(f"/api/admin/orgs/{org_id}/features/templates", json={"enabled": True, "reason": "pilot customer"})
    assert await _templates_answer(auth_client, org_id) == 422
    listed = (await super_admin_client.get("/api/admin/features")).json()
    t = next(f for f in listed["features"] if f["key"] == "templates")
    assert t["platform"]["enabled"] is False and t["org_overrides"] == 1 and t["enabled_by_default"] is False
    assert listed["groups"] == ["build", "workspace", "ship", "integrations"]

    # Clear the organisation's: back to the platform's. Clear the platform's: back to the catalogue.
    await super_admin_client.put(f"/api/admin/orgs/{org_id}/features/templates", json={"enabled": None, "reason": "pilot over"})
    assert await _templates_answer(auth_client, org_id) == 403
    await super_admin_client.put("/api/admin/features/templates", json={"enabled": None, "reason": "templates resumed"})
    assert await _templates_answer(auth_client, org_id) == 422
    rows = (await super_admin_client.get("/api/admin/audit", params={"action": "feature.platform"})).json()
    assert {r["changes"]["reason"] for r in rows} == {"templates paused platform-wide", "templates resumed"}


@pytest.mark.asyncio
async def test_only_the_super_admin_switches_and_every_change_has_a_reason(super_admin_client, auth_client, org_id):
    assert (await auth_client.put(f"/api/admin/orgs/{org_id}/features/publish", json={"enabled": True, "reason": "please"})).status_code == 403
    assert (await super_admin_client.put(f"/api/admin/orgs/{org_id}/features/publish", json={"enabled": True, "reason": "no"})).status_code == 422
    assert (await super_admin_client.put(f"/api/admin/orgs/{org_id}/features/teleport", json={"enabled": True, "reason": "a reason"})).status_code == 404
    r = await super_admin_client.put(f"/api/admin/orgs/{org_id}/features/publish", json={"enabled": True, "reason": "paying customer"})
    assert r.status_code == 200
    project = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Shop"})).json()
    # Open now: the publish route gets past the door (and fails later on an app that was never built).
    assert (await auth_client.post(f"/api/projects/{project['id']}/publish", json={})).status_code != 403

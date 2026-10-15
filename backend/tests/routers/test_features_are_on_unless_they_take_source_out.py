"""Every feature is on for an organisation unless it takes an app's source
code out of the platform — the Code tab, code export, publishing, mobile
builds — which are off until the super admin opens them. Members read
their organisation's features; the routes of a feature that is off refuse
with 403 and say who can change that."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_defaults_and_the_doors_they_close(auth_client, org_id):
    r = await auth_client.get(f"/api/orgs/{org_id}/features")
    assert r.status_code == 200
    features = r.json()["features"]
    assert features["drafts_room"]["enabled"] and features["templates"]["enabled"] and features["integrations"]["enabled"]
    for key in ("code_view", "code_export", "publish", "mobile_builds"):
        assert features[key]["enabled"] is False and features[key]["source_out"] and features[key]["source"] == "default", key

    project = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Shop"})).json()
    pid = project["id"]
    r = await auth_client.post(f"/api/projects/{pid}/export/dockerfile", json={})
    assert r.status_code == 403 and r.json()["detail"].startswith("Code export is not enabled for your organisation")
    assert r.headers.get("x-forge-feature") == "code_export"
    assert (await auth_client.get(f"/api/projects/{pid}/download")).status_code == 403
    r = await auth_client.get(f"/api/projects/{pid}/files")
    assert r.status_code == 403 and r.json()["detail"].startswith("Code tab is not enabled")
    assert (await auth_client.post(f"/api/projects/{pid}/publish", json={})).status_code == 403
    # What is on answers as before.
    assert (await auth_client.get(f"/api/orgs/{org_id}/drafts-room")).status_code == 200


@pytest.mark.asyncio
async def test_an_outsider_reads_no_organisations_features(client, auth_client, org_id):
    from main import app
    other = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    token = (await other.post("/api/auth/signup", json={"email": "someone@example.com", "name": "S", "password": "Pass12345"})).json()["access_token"]
    other.headers["Authorization"] = f"Bearer {token}"
    assert (await other.get(f"/api/orgs/{org_id}/features")).status_code == 403
    await other.aclose()
    nobody = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    assert (await nobody.get(f"/api/orgs/{org_id}/features")).status_code in (401, 403)
    await nobody.aclose()

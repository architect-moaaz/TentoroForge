"""Purge is permanent and deliberate: only a removed organisation, only
with its slug typed back; every project torn down (preview, apps database,
Neon, folder, rows), then the organisation itself; what could not be removed
is reported, and a second purge finds nothing."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def fakes(monkeypatch):
    calls: dict[str, list] = {"preview": [], "drop": [], "neon": []}
    import preview
    from services import app_databases
    monkeypatch.setattr(preview, "stop_preview", lambda sid: calls["preview"].append(sid) or False)
    monkeypatch.setattr(app_databases, "server", lambda: "postgresql://apps")
    monkeypatch.setattr(app_databases, "drop", lambda name: calls["drop"].append(name))
    monkeypatch.setenv("NEON_API_KEY", "test-key")

    class FakeNeon:
        def __init__(self, *a, **k):
            pass

        async def delete_project(self, nid):
            if nid == "neon-broken":
                raise RuntimeError("neon is down")
            calls["neon"].append(nid)

        async def close(self):
            pass

    from services.deploy import neon_client
    monkeypatch.setattr(neon_client, "NeonClient", FakeNeon)
    return calls


@pytest.mark.asyncio
async def test_purge_takes_everything_and_reports_what_it_could_not(auth_client, super_admin_client, org_id, fakes):
    a = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "App A"})).json()
    b = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "App B"})).json()
    from database import async_session
    from models.deployment import Deployment
    async with async_session() as db:
        db.add(Deployment(project_id=uuid.UUID(a["id"]), target="vercel", status="succeeded", neon_project_id="neon-a"))
        db.add(Deployment(project_id=uuid.UUID(b["id"]), target="vercel", status="failed", neon_project_id="neon-broken"))
        await db.commit()

    # Not before it is removed, and not with the wrong slug.
    assert (await super_admin_client.post(f"/api/admin/orgs/{org_id}/purge", json={"confirm_slug": "test-org"})).status_code == 409
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/remove", json={"reason": "churned"})
    assert (await super_admin_client.post(f"/api/admin/orgs/{org_id}/purge", json={"confirm_slug": "wrong"})).status_code == 400

    r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/purge", json={"confirm_slug": "test-org"})
    assert r.status_code == 200, r.text
    report = r.json()
    assert sorted(fakes["drop"]) == sorted([f"app_{a['short_id']}", f"app_{b['short_id']}"])
    assert fakes["neon"] == ["neon-a"]
    assert report["failed"] == [{"step": "neon", "target": "neon-broken", "error": "RuntimeError: neon is down"}]
    assert ("organization", org_id) in {(s["step"], s["target"]) for s in report["removed"]}
    base = Path(os.environ["FORGE_OUTPUT_BASE"])
    assert not (base / a["short_id"]).exists() and not (base / b["short_id"]).exists()

    assert (await super_admin_client.get(f"/api/admin/orgs/{org_id}")).status_code == 404
    assert (await super_admin_client.post(f"/api/admin/orgs/{org_id}/purge", json={"confirm_slug": "test-org"})).status_code == 404
    assert (await auth_client.get("/api/orgs")).json() == []
    # The purge itself is on the record, with no organisation left to point at.
    rows = (await super_admin_client.get("/api/admin/audit", params={"action": "org.purge"})).json()
    assert rows and rows[0]["changes"]["slug"] == "test-org"

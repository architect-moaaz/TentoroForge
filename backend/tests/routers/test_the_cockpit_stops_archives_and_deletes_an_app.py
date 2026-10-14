"""Every app on the platform, from the cockpit: listed with its organisation
and owner, its build stopped, its preview stopped, archived and brought back,
and deleted — with its id typed back — through the one teardown that also
drops its database on the apps server and its Neon projects. A member's own
delete goes through the same teardown now."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def project(auth_client, org_id):
    r = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Doomed App"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def fakes(monkeypatch):
    """What a teardown reaches for, recorded instead of done."""
    calls: dict[str, list] = {"preview": [], "drop": [], "neon": [], "stop": []}
    import preview
    from services import app_databases, run_registry
    monkeypatch.setattr(preview, "stop_preview", lambda sid: calls["preview"].append(sid) or True)
    monkeypatch.setattr(app_databases, "server", lambda: "postgresql://apps")
    monkeypatch.setattr(app_databases, "drop", lambda name: calls["drop"].append(name))
    monkeypatch.setattr(run_registry, "request_stop", lambda pid, out: calls["stop"].append(pid))
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


async def _deployment(project_id: str, neon_project_id: str) -> None:
    from database import async_session
    from models.deployment import Deployment
    async with async_session() as db:
        db.add(Deployment(project_id=uuid.UUID(project_id), target="vercel", status="succeeded",
                          url="https://app.example.vercel.app", neon_project_id=neon_project_id))
        await db.commit()


@pytest.mark.asyncio
async def test_the_apps_list_names_org_owner_and_deployment(super_admin_client, project, org_id):
    await _deployment(project["id"], "neon-1")
    r = await super_admin_client.get("/api/admin/apps", params={"q": "Doomed"})
    assert r.status_code == 200 and r.json()["total"] == 1
    app = r.json()["items"][0]
    assert app["short_id"] == project["short_id"] and app["org"]["id"] == org_id
    assert app["owner_email"] == "test@example.com" and app["deployed_url"] == "https://app.example.vercel.app"
    assert app["build_in_flight"] is False and app["preview_running"] is False
    assert (await super_admin_client.get("/api/admin/apps", params={"org_id": str(uuid.uuid4())})).json()["total"] == 0


@pytest.mark.asyncio
async def test_stop_build_stop_preview_archive_and_unarchive(super_admin_client, auth_client, project, org_id, fakes):
    pid = project["id"]
    r = await super_admin_client.post(f"/api/admin/apps/{pid}/stop-build")
    assert r.status_code == 200 and r.json()["stopping"] is True and fakes["stop"] == [pid]
    r = await super_admin_client.post(f"/api/admin/apps/{pid}/stop-preview")
    assert r.status_code == 200 and fakes["preview"] == [project["short_id"]]

    assert (await super_admin_client.post(f"/api/admin/apps/{pid}/unarchive")).status_code == 409
    r = await super_admin_client.post(f"/api/admin/apps/{pid}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert [p["id"] for p in (await auth_client.get(f"/api/orgs/{org_id}/projects")).json()] == []
    r = await super_admin_client.post(f"/api/admin/apps/{pid}/unarchive")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert [p["id"] for p in (await auth_client.get(f"/api/orgs/{org_id}/projects")).json()] == [pid]


@pytest.mark.asyncio
async def test_delete_needs_the_id_typed_and_runs_the_one_teardown(super_admin_client, auth_client, project, fakes):
    pid, sid = project["id"], project["short_id"]
    await _deployment(pid, "neon-1")
    await _deployment(pid, "neon-broken")
    folder = Path(os.environ["FORGE_OUTPUT_BASE"]) / sid
    assert folder.exists()

    assert (await super_admin_client.post(f"/api/admin/apps/{pid}/delete", json={"confirm_short_id": "wrong"})).status_code == 400
    r = await super_admin_client.post(f"/api/admin/apps/{pid}/delete", json={"confirm_short_id": sid})
    assert r.status_code == 200, r.text
    steps = {(s["step"], s["target"]) for s in r.json()["removed"]}
    assert ("preview", sid) in steps and ("app_database", f"app_{sid}") in steps and ("neon", "neon-1") in steps
    assert ("folder", str(folder)) in steps and ("rows", sid) in steps
    assert r.json()["failed"] == [{"step": "neon", "target": "neon-broken", "error": "RuntimeError: neon is down"}]
    assert not folder.exists()
    assert (await auth_client.get(f"/api/projects/{pid}")).status_code == 404
    assert fakes["drop"] == [f"app_{sid}"]


@pytest.mark.asyncio
async def test_a_members_own_delete_drops_the_app_database_too(auth_client, project, fakes):
    r = await auth_client.delete(f"/api/projects/{project['id']}")
    assert r.status_code in (200, 204), r.text
    assert fakes["drop"] == [f"app_{project['short_id']}"]
    assert not (Path(os.environ["FORGE_OUTPUT_BASE"]) / project["short_id"]).exists()

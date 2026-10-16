"""A blocked organisation starts no work. A build, a Smith turn through the
panel and a Smith turn through the editor route are all refused at the
door — before any agent runs — with the organisation's status as the
reason; its people still sign in and are told."""
from __future__ import annotations

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def project(auth_client, org_id):
    r = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Blocked App"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_no_build_or_turn_starts_for_a_blocked_org(auth_client, super_admin_client, org_id, project, monkeypatch):
    import routers.blueprint_generate as bg
    started = []
    monkeypatch.setattr(bg, "_run_dag", lambda *a, **k: started.append("dag") or {"status": "ran"})

    await super_admin_client.post(f"/api/admin/orgs/{org_id}/block", json={"reason": "unpaid"})

    r = await auth_client.post(f"/api/projects/{project['id']}/generate/blueprint", json={"description": "A shop"})
    assert r.status_code == 403 and r.json()["detail"] == "Organisation is blocked"
    r = await auth_client.post(f"/api/projects/{project['id']}/smith/chat",
                               json={"message": "add a page", "history": [], "approved": False})
    assert r.status_code == 403 and r.json()["detail"] == "Organisation is blocked"
    r = await auth_client.post(f"/api/projects/{project['short_id']}/smith/turn", json={"text": "add a page"})
    assert r.status_code == 403
    assert started == []

    # Reinstated, the same calls reach the work (a stub, here).
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/reinstate")
    r = await auth_client.post(f"/api/projects/{project['id']}/generate/blueprint", json={"description": "A shop"})
    assert r.status_code != 403, r.text


@pytest.mark.asyncio
async def test_a_removed_orgs_app_is_not_found(auth_client, super_admin_client, org_id, project):
    await super_admin_client.post(f"/api/admin/orgs/{org_id}/remove", json={"reason": "churned"})
    r = await auth_client.get(f"/api/projects/{project['id']}")
    assert r.status_code == 404
    r = await auth_client.post(f"/api/projects/{project['id']}/smith/chat",
                               json={"message": "hello", "history": [], "approved": False})
    assert r.status_code == 404

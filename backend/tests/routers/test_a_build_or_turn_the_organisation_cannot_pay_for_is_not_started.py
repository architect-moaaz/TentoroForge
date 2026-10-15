"""Nothing starts that the organisation cannot pay for. A build, a Smith
turn through the panel and a turn through the editor route are refused at
the door with 402 and the reasons in the administrator's words; the ledger
is untouched; a limit works the same way; a check that itself fails lets
the work through."""
from __future__ import annotations

import json
import time

import pytest
import pytest_asyncio


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("FORGE_USAGE_LOG", str(path))
    return path


@pytest_asyncio.fixture
async def project(auth_client, org_id):
    r = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Costly App"})
    assert r.status_code == 201, r.text
    return r.json()


def _spend(path, short_id: str, cost: float, user: str = "test@example.com", org: str = "") -> None:
    with path.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "project": short_id, "agent": "page_code", "phase": "change",
                            "model": "m", "est_cost_usd": cost, "sdk_cost_usd": 0.0, "input_tokens": 1,
                            "output_tokens": 1, "user": user, "org": org}) + "\n")


@pytest.mark.asyncio
async def test_a_build_the_balance_cannot_cover_is_refused_and_a_turn_is_not(auth_client, super_admin_client, org_id, project, ledger, monkeypatch):
    import routers.blueprint_generate as bg
    started = []
    monkeypatch.setattr(bg, "_run_dag", lambda *a, **k: started.append("dag") or {"status": "ran"})
    r = await super_admin_client.post(f"/api/admin/credits/orgs/{org_id}/entries",
                                      json={"amount_usd": 5, "kind": "opening", "note": "opening balance"})
    assert r.status_code == 201, r.text

    r = await auth_client.post(f"/api/projects/{project['id']}/generate/blueprint",
                               json={"description": "A shop", "approved": True})
    assert r.status_code == 402, r.text
    assert r.json()["detail"].startswith("Not started: the organisation Test Org holds $5.00 and this is expected to cost about $12.00")
    assert started == [] and not ledger.exists()

    # A turn costs less than the balance: through to the work (a stub here).
    r = await auth_client.post(f"/api/projects/{project['id']}/smith/chat",
                               json={"message": "rename the page", "history": [], "approved": False})
    assert r.status_code != 402, r.text


@pytest.mark.asyncio
async def test_a_limit_refuses_in_the_same_words_and_a_failing_check_lets_work_through(auth_client, super_admin_client, org_id, project, ledger, monkeypatch):
    _spend(ledger, project["short_id"], 0.4)
    r = await super_admin_client.put("/api/admin/credits/limits",
                                     json={"scope_kind": "user", "scope_id": "test@example.com", "day": 0.5})
    assert r.status_code == 200, r.text

    r = await auth_client.post(f"/api/projects/{project['short_id']}/smith/turn", json={"text": "add a page"})
    assert r.status_code == 402
    assert "test@example.com has spent $0.40 today of a $0.50 limit, and this is expected to cost about $0.60" in r.json()["detail"]

    from services import spending
    monkeypatch.setattr(spending, "check", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger unreadable")))
    r = await auth_client.post(f"/api/projects/{project['short_id']}/smith/turn", json={"text": "add a page"})
    assert r.status_code != 402


@pytest.mark.asyncio
async def test_an_org_with_no_entry_is_not_refused_for_a_balance(auth_client, project, ledger, monkeypatch):
    import routers.blueprint_generate as bg
    monkeypatch.setattr(bg, "_run_dag", lambda *a, **k: {"status": "ran"})
    r = await auth_client.post(f"/api/projects/{project['id']}/generate/blueprint",
                               json={"description": "A shop", "approved": True})
    assert r.status_code != 402, r.text

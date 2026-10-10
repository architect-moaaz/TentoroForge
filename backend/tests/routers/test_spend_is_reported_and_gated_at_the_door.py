"""The spend report per person, organisation and application; the credit
and limits an administrator keeps; and a build or a turn refused at the
door when the account cannot cover it (2026-10-10: $100 became $19 and a
build sank $14 before the API refused it)."""
from __future__ import annotations

import json
import time

import pytest


async def _project(client, org_id, name="Shop") -> dict:
    res = await client.post(f"/api/orgs/{org_id}/projects", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()


def _ledger(path, project: str, rows: list[tuple[float, str, float]]) -> None:
    with open(path, "w") as f:
        for ts, agent, cost in rows:
            f.write(json.dumps({"ts": ts, "project": project, "agent": agent, "kind": "blueprint", "phase": "build",
                                "model": "claude-sonnet-5", "input_tokens": 100, "output_tokens": 50,
                                "est_cost_usd": cost}) + "\n")


@pytest.mark.asyncio
async def test_the_report_names_the_person_and_the_organisation_behind_each_application(auth_client, org_id, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_USAGE_LOG", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("FORGE_SPEND_POLICY", str(tmp_path / "policy.json"))
    project = await _project(auth_client, org_id)
    now = time.time()
    _ledger(tmp_path / "usage.jsonl", project["short_id"],
            [(now - 60, "page_code:ui_engineer", 3.0), (now - 30, "workflow_steps:workflow", 1.0),
             (now - 40 * 86400, "smith", 2.0)])
    res = await auth_client.get("/api/spend/report", params={"period": "day"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"]["cost_usd"] == 4.0 and body["period"] == "day"
    assert body["by_project"][0]["project"] == project["short_id"] and body["by_project"][0]["name"] == "Shop"
    assert body["by_user"] == [{"user": "test@example.com", "cost_usd": 4.0, "calls": 2, "input_tokens": 200,
                                "output_tokens": 100, "cache_read_tokens": 0, "cache_write_tokens": 0}]
    assert [r["agent"] for r in body["by_agent"]] == ["page_code:ui_engineer", "workflow_steps:workflow"]
    res = await auth_client.get("/api/spend/report", params={"period": "year", "org": org_id})
    assert res.json()["total"]["cost_usd"] == 6.0, "the organisation's year holds the old row too"
    res = await auth_client.get("/api/spend/report", params={"period": "year", "person": "me"})
    assert res.json()["total"]["cost_usd"] == 6.0
    res = await auth_client.get("/api/spend/report", params={"period": "fortnight"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_an_administrator_records_credit_and_limits_and_sees_where_things_stand(auth_client, org_id, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_USAGE_LOG", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("FORGE_SPEND_POLICY", str(tmp_path / "policy.json"))
    project = await _project(auth_client, org_id)
    _ledger(tmp_path / "usage.jsonl", project["short_id"], [(time.time() - 60, "smith", 2.5)])
    res = await auth_client.post("/api/spend/credits", json={"amount": 100, "note": "top-up"})
    assert res.status_code == 201 and res.json()["by"] == "test@example.com"
    res = await auth_client.post("/api/spend/credits", json={"amount": 0})
    assert res.status_code == 422
    res = await auth_client.put("/api/spend/limits", json={"scope": f"org:{org_id}", "week": 40, "day": None})
    assert res.status_code == 200 and res.json()["limits"] == {"week": 40.0}
    res = await auth_client.put("/api/spend/limits", json={"scope": "team:x", "week": 40})
    assert res.status_code == 400
    res = await auth_client.get("/api/spend/standing", params={"org": org_id, "person": "me"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["balance"]["credit_usd"] == 100 and body["balance"]["balance_usd"] == 100.0, \
        "credit counts from when it was recorded; the earlier row is not against it"
    week = next(r for r in body["limits"] if r["scope"] == f"org:{org_id}" and r["period"] == "week")
    assert week["limit_usd"] == 40.0 and week["spent_usd"] == 2.5 and week["left_usd"] == 37.5
    assert body["policy"]["limits"] == {f"org:{org_id}": {"week": 40.0}} and body["build_estimate_usd"] > 0


@pytest.mark.asyncio
async def test_a_build_the_account_cannot_pay_for_is_not_started(auth_client, org_id, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_USAGE_LOG", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("FORGE_SPEND_POLICY", str(tmp_path / "policy.json"))
    from services import spending
    project = await _project(auth_client, org_id)
    spending.add_credit(5)                                                   # $5 on the account
    res = await auth_client.post(f"/api/projects/{project['id']}/generate/blueprint",
                                 json={"description": "a shop", "approved": True})
    assert res.status_code == 402, res.text
    assert res.json()["detail"].startswith("Not started: the account holds $5.00 and this is expected to cost about $12.00")
    assert not (tmp_path / "usage.jsonl").exists(), "nothing was spent"
    res = await auth_client.post(f"/api/projects/{project['id']}/smith/chat", json={"message": "hello"})
    assert res.status_code != 402, "a turn costs well under $5"
    spending.set_limits(f"user:test@example.com", {"day": 0.5})
    _ledger(tmp_path / "usage.jsonl", project["short_id"], [(time.time() - 60, "smith", 0.4)])
    res = await auth_client.post(f"/api/projects/{project['id']}/smith/chat", json={"message": "hello"})
    assert res.status_code == 402 and "test@example.com has spent $0.40 today of a $0.50 limit" in res.json()["detail"]

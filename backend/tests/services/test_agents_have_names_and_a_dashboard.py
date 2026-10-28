"""Every agent is a person — a name, a title, a few words of introduction —
and the super admin sees how each one is doing.

The office, the build strip and the spend charts each called agents their own
thing ("Data Modeler", a stage verb, `page_code:ui_engineer`). One persona
file names them all; `agent_stats` reads the usage ledger and every app's run
ledgers into each agent's work, cost, success and failures.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from services import agent_personas
from services.agent_personas import agent_of, aliases, persona_for, personas
from services.agent_stats import agent_stats

ROOT = Path(__file__).resolve().parents[2]


def test_every_agent_and_every_step_of_the_build_has_a_person():
    from services.blueprint.agent_contract import AGENT_REGISTRY
    from services.blueprint.orchestrator import DAG
    assert set(AGENT_REGISTRY) <= set(personas())
    assert [k for k in DAG if agent_of(k) is None] == []
    assert set(aliases().values()) <= set(personas())
    for agent, p in personas().items():
        assert p["name"] and p["title"] and p["room"], agent
        assert p["intro"].startswith(f"I'm {p['name']}."), agent
    assert personas()["smith"]["name"] == "Smith"
    names = [p["name"] for p in personas().values()]
    assert len(set(names)) == len(names), "two agents share a name"


def test_the_frontend_reads_the_same_people():
    front = json.loads((ROOT.parent / "frontend" / "src" / "lib" / "agent-personas.json").read_text())
    back = json.loads(agent_personas.PERSONAS_FILE.read_text())
    assert front == back, "copy backend/services/agent_personas.json to frontend/src/lib/agent-personas.json"


def test_the_foundrys_desks_are_all_people():
    """Every agent at a desk in the Foundry (`virtual-office/types.ts`) has a persona."""
    import re
    src = (ROOT.parent / "frontend" / "src" / "components" / "virtual-office" / "types.ts").read_text()
    ids = re.findall(r'\{ id: "([a-z_]+)", name: "', src)
    assert ids and [i for i in ids if i not in personas()] == []


@pytest.mark.parametrize("key,agent", [
    ("page_code:ui_engineer", "ui_engineer"), ("workflow_steps:workflow:edit", "workflow"),
    ("app_check", "testing"), ("checks", "testing"), ("page_review", "page_reviewer"),
    ("page_repair", "smith"), ("Indexer", "memory"), ("decisions:engineer", "solution_architecture"),
    ("page_code", "ui_engineer"), ("smith", "smith"), ("", None), ("nobody", None),
])
def test_work_recorded_under_any_name_is_its_agents(key, agent):
    assert agent_of(key) == agent
    if agent:
        assert persona_for(key)["agent"] == agent


def _ledger(app: Path, run_id: str, events: list[dict]) -> Path:
    runs = app / ".forge" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{run_id}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


def _now(offset: float = 0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


def test_each_agents_work_cost_success_and_failures(tmp_path):
    now = time.time()
    rows = [
        {"ts": now - 60, "agent": "entity_fields:data_model", "project": "app1", "input_tokens": 1000,
         "output_tokens": 500, "duration_ms": 120000, "est_cost_usd": 0.5},
        {"ts": now - 50, "agent": "entity_fields:data_model:edit", "project": "app1", "duration_ms": 60000,
         "est_cost_usd": 0.25},
        {"ts": now - 40, "agent": "app_check", "project": "app2", "duration_ms": 30000, "est_cost_usd": 0.1},
        {"ts": now - 400 * 86400, "agent": "smith", "est_cost_usd": 99},          # last year: not this period
    ]
    _ledger(tmp_path / "app1", "20261028-100000-abc123", [
        {"event": "run:start", "phase": "build", "at": _now(-300), "elapsedMs": 0},
        {"event": "node:start", "node": "entity_fields", "elapsedMs": 1000},
        {"event": "node:retry", "node": "entity_fields", "reason": "ran out of output", "elapsedMs": 2000},
        {"event": "observer:repair", "node": "entity_fields", "elapsedMs": 2500},
        {"event": "node:done", "node": "entity_fields", "elapsedMs": 31000},
        {"event": "observer:verdict", "node": "entity_fields", "ok": False, "findings": 2, "elapsedMs": 31500},
        {"event": "node:start", "node": "workflow_steps", "elapsedMs": 32000},
        {"event": "node:subject", "node": "workflow_steps", "subject": "FLOW-001", "ok": False,
         "summary": "the formula `x[0]` could not be parsed", "elapsedMs": 33000},
        {"event": "node:failed", "node": "workflow_steps", "reason": "all 3 subjects failed", "elapsedMs": 40000},
        {"event": "run:end", "failedBecause": {"workflow_steps": "all 3 subjects failed"}, "elapsedMs": 41000},
    ])
    _ledger(tmp_path / "app2", "20261028-110000-smith-turn", [
        {"event": "run:start", "phase": "change", "at": _now(-200), "elapsedMs": 0},
        {"event": "run:crashed", "error": "the platform restarted while it ran", "elapsedMs": 9000},
    ])
    out = agent_stats(period="month", root=tmp_path, rows=rows)
    by = {a["agent"]: a for a in out["agents"]}
    bob, todd, smith, otto, tess = by["data_model"], by["workflow"], by["smith"], by["observer"], by["testing"]
    assert bob["name"] == "Bob" and bob["calls"] == 2 and bob["repair_calls"] == 1
    assert bob["cost_usd"] == pytest.approx(0.75) and bob["busy_hours"] == pytest.approx(0.05)
    assert (bob["steps"], bob["done"], bob["failed"], bob["retries"], bob["repairs"]) == (1, 1, 0, 1, 1)
    assert bob["median_s"] == 30.0 and bob["success_rate"] == 1.0
    assert todd["failed"] == 1 and todd["success_rate"] == 0.0
    # "all 3 subjects failed" says nothing; the subject that failed does.
    assert todd["top_failures"][0]["reason"].startswith("the formula `x[#]` could not be parsed")
    assert (smith["steps"], smith["failed"], smith["runs_lost"]) == (1, 1, 1)
    assert smith["top_failures"][0]["reason"] == "cut off by a platform restart"
    assert smith["cost_usd"] == 0, "last year's spend is not this month's"
    assert otto["reviews"] == 1 and otto["found"] == 1
    assert tess["calls"] == 1 and tess["apps"] == 1
    assert out["totals"]["failed"] == 2 and out["totals"]["runs_lost"] == 1
    assert any(a["calls"] == 0 and a["steps"] == 0 for a in out["agents"]), "idle agents are listed too"
    assert out["daily"] and out["daily"][-1]["calls"] == 3


@pytest.mark.asyncio
async def test_only_the_super_admin_sees_the_agents(client, super_admin_client, monkeypatch, tmp_path):
    from routers import admin_agents
    monkeypatch.setattr("services.project_paths.OUTPUT_ROOT", tmp_path)
    admin_agents._cache.clear()
    r = await super_admin_client.get("/api/admin/agents?period=week")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {a["name"] for a in body["agents"]} >= {"Bob", "Todd", "Smith"}
    assert (await super_admin_client.get("/api/admin/agents?period=decade")).status_code == 422
    assert (await super_admin_client.get("/api/admin/agents/personas")).json()["personas"]["data_model"]["name"] == "Bob"


@pytest.mark.asyncio
async def test_anyone_else_is_turned_away(auth_client):
    assert (await auth_client.get("/api/admin/agents")).status_code == 403

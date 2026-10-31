"""Find problems, through the platform's four endpoints.

Driven the way the other router tests drive endpoints: the function itself, with the project lookup stubbed and the
engine faked at its edge. What is pinned: the bombs and limits are listed, a failure to invent is a plain 400 with the
reason, a blast streams its events as they happen, and fixes come back for the failures only.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import models  # noqa: F401  (register every model before test_db.create_all)
from tests.services.test_agent_runtime_install import graph, node


@pytest.fixture()
def project(monkeypatch):
    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=None)

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    return proj


def drawn():
    from schemas.agent_builder import AgentDefinitionSave

    return AgentDefinitionSave(**graph(node("sp", "system_prompt", "P", {"prompt": "You help."})))


U = SimpleNamespace(id="u")


async def drain(response) -> list[dict]:
    raw = b"".join([c async for c in response.body_iterator]).decode()
    return [json.loads(line[6:]) for line in raw.split("\n") if line.startswith("data: ")]


@pytest.mark.asyncio
async def test_the_bombs_and_their_limits_are_listed(project):
    from routers.agent_builder import blast_bombs

    out = await blast_bombs(project.id, U, None)
    assert len(out["bombs"]) == 8 and {"made_up_id", "no_permission"} <= {b["key"] for b in out["bombs"]}
    assert out["maxTests"] == 20 and out["maxRepeats"] == 3 and out["perBomb"] == 2
    assert [a["key"] for a in out["toolAngles"]][:2] == ["valid_use", "bad_input"] and len(out["toolAngles"]) == 8 and out["perAngle"] == 2
    assert all(set(a) == {"key", "title"} for a in out["toolAngles"]), "what the AI is told about an angle is not sent to the page"


@pytest.mark.asyncio
async def test_inventing_returns_the_tests_and_passes_on_what_was_asked_for(project, monkeypatch):
    from routers.agent_builder import blast_invent
    from schemas.agent_builder import AgentBlastInvent

    seen = {}

    async def fake(graph_, bombs, per_bomb, **kw):
        seen.update(bombs=bombs, per=per_bomb, prompt=graph_["nodes"][0]["data"]["config"]["prompt"])
        return [{"id": "blast_vague_1", "bomb": "vague", "name": "n", "message": "fix it", "expect": {}, "judge": "asks"}]

    monkeypatch.setattr("services.agent_blast.invent_bombs", fake)
    out = await blast_invent(project.id, "support", AgentBlastInvent(graph=drawn(), bombs=["vague"], per_bomb=3), U, None)
    assert out["tests"][0]["id"] == "blast_vague_1"
    assert seen == {"bombs": ["vague"], "per": 3, "prompt": "You help."}


@pytest.mark.asyncio
async def test_a_failure_to_invent_is_a_plain_400_with_the_reason(project, monkeypatch):
    from routers.agent_builder import blast_invent
    from schemas.agent_builder import AgentBlastInvent

    async def nokey(*a, **kw):
        raise RuntimeError("Finding problems needs a model key.")

    monkeypatch.setattr("services.agent_blast.invent_bombs", nokey)
    with pytest.raises(HTTPException) as e:
        await blast_invent(project.id, "support", AgentBlastInvent(graph=drawn()), U, None)
    assert e.value.status_code == 400 and "needs a model key" in e.value.detail


@pytest.mark.asyncio
async def test_a_blast_streams_its_events_as_they_happen(project, monkeypatch):
    from routers.agent_builder import blast_run
    from schemas.agent_builder import AgentBlastRun

    seen = {}

    async def fake(graph_, tests, *, repeats=1, **kw):
        seen.update(tests=tests, repeats=repeats)
        yield {"type": "start", "total": 1, "repeats": repeats}
        yield {"type": "result", "result": {"id": "a", "status": "failed"}}
        yield {"type": "done", "summary": {"passed": 0, "failed": 1, "flaky": 0, "error": 0, "total": 1}}

    monkeypatch.setattr("services.agent_blast.blast", fake)
    resp = await blast_run(project.id, "support", AgentBlastRun(graph=drawn(), tests=[{"name": "x", "message": "m"}], repeats=2), U, None)
    assert resp.media_type == "text/event-stream"
    events = await drain(resp)
    assert [e["type"] for e in events] == ["start", "result", "done"] and events[-1]["summary"]["failed"] == 1
    assert seen == {"tests": [{"name": "x", "message": "m"}], "repeats": 2}


@pytest.mark.asyncio
async def test_fixes_come_back_for_the_failures_and_a_failure_to_propose_is_a_400(project, monkeypatch):
    from routers.agent_builder import blast_fixes
    from schemas.agent_builder import AgentBlastFixes

    async def fake(graph_, results, **kw):
        return [{"id": "fix_1", "kind": "advice", "text": f"{len(results)} failed"}]

    monkeypatch.setattr("services.agent_blast.propose_fixes", fake)
    out = await blast_fixes(project.id, "support", AgentBlastFixes(graph=drawn(), results=[{"id": "a", "status": "failed"}]), U, None)
    assert out["fixes"][0]["text"] == "1 failed"

    async def broken(*a, **kw):
        raise RuntimeError("The model did not answer in the expected form.")

    monkeypatch.setattr("services.agent_blast.propose_fixes", broken)
    with pytest.raises(HTTPException) as e:
        await blast_fixes(project.id, "support", AgentBlastFixes(graph=drawn()), U, None)
    assert e.value.status_code == 400


def test_the_old_run_scenarios_endpoint_is_gone_because_find_problems_runs_saved_tests_too():
    import routers.agent_builder as r

    paths = {getattr(route, "path", "") for route in r.router.routes}
    assert not any(p.endswith("/tests/run") for p in paths)
    assert {"/api/projects/{project_id}/agent-definitions/blast/bombs"} <= paths
    assert any(p.endswith("/blast/invent") for p in paths) and any(p.endswith("/blast/run") for p in paths) and any(p.endswith("/blast/fixes") for p in paths)
    assert any(p.endswith("/{agent_id}/tests") for p in paths), "saved tests are still kept and listed"


@pytest.mark.asyncio
async def test_a_tool_is_studied_and_its_tests_come_back_with_the_analysis_and_a_failure_is_a_plain_400(project, monkeypatch):
    from routers.agent_builder import blast_tool_tests
    from schemas.agent_builder import AgentBlastTool

    seen = {}

    async def fake(graph_, tool, angles, per_angle, **kw):
        seen.update(tool=tool, angles=angles, per=per_angle)
        return {"analysis": {"whatItDoes": "Lists tickets.", "needs": [], "risks": []}, "tests": [{"id": "tool_x_valid_use_1", "name": "n", "message": "m", "expect": {}}]}

    monkeypatch.setattr("services.agent_blast.invent_tool_tests", fake)
    out = await blast_tool_tests(project.id, "support", AgentBlastTool(graph=drawn(), tool="list_tickets", angles=["fidelity"], per_angle=3), U, None)
    assert out["analysis"]["whatItDoes"] == "Lists tickets." and out["tests"][0]["id"] == "tool_x_valid_use_1"
    assert seen == {"tool": "list_tickets", "angles": ["fidelity"], "per": 3}

    async def broken(*a, **kw):
        raise RuntimeError("There is no tool called 'ghost' on this agent.")

    monkeypatch.setattr("services.agent_blast.invent_tool_tests", broken)
    with pytest.raises(HTTPException) as e:
        await blast_tool_tests(project.id, "support", AgentBlastTool(graph=drawn(), tool="ghost"), U, None)
    assert e.value.status_code == 400 and "no tool called 'ghost'" in e.value.detail

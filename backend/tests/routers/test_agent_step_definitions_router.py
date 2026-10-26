"""The two routes an assistant step needs from the platform (routers/agent_step_definitions.py).

`POST .../agent-definitions/from-brief` makes the workflow-only assistant for a step the way the build stage does, and
`GET .../agent-definitions/{agent_id}/used-by` says which workflows run an assistant. Driven like the other router
tests: the functions themselves with the project lookup stubbed, plus one real request through both routers in the
app's order to prove the paths are not read as an assistant's id.
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import models  # noqa: F401  (register every model before test_db.create_all)
from schemas.agent_builder import AgentBrief, AgentFromBrief
from services.blueprint import agent_steps
from tests.services.test_an_assistant_step import HOST, host_steps, triage, vet_doc

PID = uuid.UUID("11111111-2222-3333-4444-555555555555")
USER = SimpleNamespace(id="u-1")
AID = "wf_handle-appointment-request_triage"


def brief(**kw) -> AgentBrief:
    cfg = triage()["config"]["agentBrief"]
    cfg.update(kw)
    return AgentBrief(**cfg)


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A project with a Blueprint on disk (the VET clinic, its host workflow written out) and a stubbed project lookup."""
    doc = vet_doc()
    next(w for w in doc["workflows"] if w["name"] == HOST)["steps"] = host_steps()
    path = tmp_path / ".forge" / "blueprint"
    path.mkdir(parents=True)
    (path / "current.json").write_text(json.dumps(doc), encoding="utf-8")
    proj = SimpleNamespace(id=PID, output_dir=str(tmp_path), doc=doc)

    async def fake_get(project_id, user, db):
        if str(project_id) != str(PID):
            raise HTTPException(status_code=404, detail="Project not found")
        return proj

    monkeypatch.setattr("routers.agent_step_definitions.get_project_with_auth", fake_get)
    return proj


def defs(project):
    d = Path(project.output_dir) / "agent-definitions"
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


# --- from-brief ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_from_brief_makes_and_saves_the_assistant_for_the_step(project):
    from routers.agent_step_definitions import agent_from_brief

    out = await agent_from_brief(PID, AgentFromBrief(brief=brief(), workflowId="FLOW-006", stepId="triage"), USER, None)
    assert out["agentId"] == AID and out["name"] == "Triage assistant" and out["warnings"] == []
    assert {"list_pets", "get_pet", "list_medical_records", "book_appointment"} <= set(out["tools"])
    assert out["writeTools"] == ["book_appointment"] and "book_appointment" not in out["readTools"]

    saved = json.loads((Path(project.output_dir) / "agent-definitions" / f"{AID}.json").read_text("utf-8"))
    assert saved["config"]["workflow_only"] is True
    assert saved["config"]["made_for"]["workflowId"] == "FLOW-006" and saved["config"]["made_for"]["stepKey"] == "triage"
    assert defs(project) == [f"{AID}.json"]


@pytest.mark.asyncio
async def test_from_brief_is_the_same_assistant_the_build_stage_makes(project):
    """One function draws both, so the editor's button and the build give the same tools and prompt."""
    from routers.agent_step_definitions import agent_from_brief
    from services.agent_suggest import agent_for_brief

    await agent_from_brief(PID, AgentFromBrief(brief=brief(), workflowId="FLOW-006", stepId="triage"), USER, None)
    saved = json.loads((Path(project.output_dir) / "agent-definitions" / f"{AID}.json").read_text("utf-8"))
    host = next(w for w in project.doc["workflows"] if w["name"] == HOST)
    made = agent_for_brief(project.doc, brief().model_dump(exclude_none=True), host, triage())["agent"]
    saved["config"].pop("made_for")
    assert saved == made


@pytest.mark.asyncio
async def test_from_brief_works_without_naming_the_step_and_takes_a_name(project):
    from routers.agent_step_definitions import agent_from_brief

    out = await agent_from_brief(PID, AgentFromBrief(brief=brief(), name="Front desk triage"), USER, None)
    assert out["name"] == "Front desk triage" and out["agentId"].startswith("wf_")
    assert defs(project) == [f"{out['agentId']}.json"]


@pytest.mark.asyncio
async def test_asking_again_for_the_same_step_makes_it_again_but_never_overwrites_an_edit(project):
    from routers.agent_step_definitions import agent_from_brief

    req = AgentFromBrief(brief=brief(), workflowId="FLOW-006", stepId="triage")
    first = await agent_from_brief(PID, req, USER, None)
    again = await agent_from_brief(PID, req, USER, None)            # nobody has touched it: made again, same id
    assert again["agentId"] == first["agentId"] == AID and defs(project) == [f"{AID}.json"]

    path = Path(project.output_dir) / "agent-definitions" / f"{AID}.json"
    graph = json.loads(path.read_text("utf-8"))
    graph["description"] = "The builder's own words."
    path.write_text(json.dumps(graph), "utf-8")
    kept = path.read_bytes()
    third = await agent_from_brief(PID, req, USER, None)
    assert third["agentId"] == f"{AID}-2" and path.read_bytes() == kept
    assert "left as it is" in third["warnings"][0]
    assert defs(project) == [f"{AID}-2.json", f"{AID}.json"]


@pytest.mark.asyncio
async def test_a_brief_the_app_cannot_honour_is_a_plain_400(project):
    from routers.agent_step_definitions import agent_from_brief

    with pytest.raises(HTTPException) as e:
        await agent_from_brief(PID, AgentFromBrief(brief=brief(reads=["Pet", "Ghosts"])), USER, None)
    assert e.value.status_code == 400 and "'Ghosts', which is not one of this app's records" in e.value.detail
    with pytest.raises(HTTPException) as e:
        await agent_from_brief(PID, AgentFromBrief(brief=AgentBrief(purpose="", reads=[])), USER, None)
    assert e.value.status_code == 400 and "the brief is not usable" in e.value.detail
    assert defs(project) == [], "nothing was saved"


@pytest.mark.asyncio
async def test_a_brief_that_lets_the_assistant_start_its_own_workflow_is_refused(project):
    from routers.agent_step_definitions import agent_from_brief

    own = brief(mayChange=[{"tool": "Handle Appointment Request", "why": "to book"}])
    with pytest.raises(HTTPException) as e:
        await agent_from_brief(PID, AgentFromBrief(brief=own, workflowId="FLOW-006", stepId="triage"), USER, None)
    assert e.value.status_code == 400 and "the workflow this very step belongs to" in e.value.detail


@pytest.mark.asyncio
async def test_a_loop_through_another_workflows_assistant_is_refused(project):
    from routers.agent_step_definitions import agent_from_brief

    doc = project.doc
    doc["workflows"].append({"id": "FLOW-007", "name": "Review Cancellation", "purpose": "Decide.", "trigger": {"kind": "manual"},
                             "status": "PROPOSED", "launchedFrom": [], "inputs": [], "steps": [
                                 {"key": "ask", "type": "agent_step", "name": "Ask", "next": [], "config": triage(
                                     agentBrief={"purpose": "Decide.", "reads": ["Appointment"],
                                                 "mayChange": [{"tool": HOST, "why": "to rebook"}]})["config"]}]})
    (Path(project.output_dir) / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc), "utf-8")
    via = brief(mayChange=[{"tool": "Review Cancellation", "why": "to send it on"}])
    with pytest.raises(HTTPException) as e:
        await agent_from_brief(PID, AgentFromBrief(brief=via, workflowId="FLOW-006", stepId="triage"), USER, None)
    assert e.value.status_code == 400 and f"{HOST} -> Review Cancellation -> {HOST}" in e.value.detail


@pytest.mark.asyncio
async def test_from_brief_needs_a_blueprint_a_directory_and_a_workflow_that_exists(project, tmp_path):
    from routers.agent_step_definitions import agent_from_brief

    with pytest.raises(HTTPException) as e:
        await agent_from_brief(PID, AgentFromBrief(brief=brief(), workflowId="FLOW-999", stepId="x"), USER, None)
    assert e.value.status_code == 400 and "no workflow called 'FLOW-999'" in e.value.detail

    (tmp_path / ".forge" / "blueprint" / "current.json").unlink()
    with pytest.raises(HTTPException) as e:
        await agent_from_brief(PID, AgentFromBrief(brief=brief()), USER, None)
    assert e.value.status_code == 409 and "no Blueprint yet" in e.value.detail

    project.output_dir = None
    with pytest.raises(HTTPException) as e:
        await agent_from_brief(PID, AgentFromBrief(brief=brief()), USER, None)
    assert e.value.status_code == 400 and e.value.detail == "No output directory"


# --- used-by -------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_used_by_is_empty_when_no_workflow_uses_the_assistant(project):
    from routers.agent_step_definitions import agent_used_by

    assert await agent_used_by(PID, "app_assistant", USER, None) == {"workflows": []}
    project.output_dir = None
    assert await agent_used_by(PID, "app_assistant", USER, None) == {"workflows": []}


@pytest.mark.asyncio
async def test_used_by_names_the_workflow_and_step_from_the_blueprint(project):
    from routers.agent_step_definitions import agent_used_by

    doc = project.doc
    step = next(s for w in doc["workflows"] if w["name"] == HOST for s in w["steps"] if s["key"] == "triage")
    step["config"]["agentId"] = "wf_x"
    (Path(project.output_dir) / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc), "utf-8")
    assert await agent_used_by(PID, "wf_x", USER, None) == {
        "workflows": [{"workflowId": "FLOW-006", "workflowName": HOST, "stepId": "triage"}]}
    assert await agent_used_by(PID, "wf_y", USER, None) == {"workflows": []}


@pytest.mark.asyncio
async def test_used_by_prefers_the_apps_own_definitions_which_the_editor_changes(project, tmp_path):
    from routers.agent_step_definitions import agent_used_by

    d = tmp_path / "app" / "src" / "lib" / "workflows" / "definitions"
    d.mkdir(parents=True)
    node = lambda nid, agent: {"id": nid, "type": "agent_step", "data": {"nodeType": "agent_step", "config": {"agentId": agent}}}
    (d / "handle-appointment-request.json").write_text(json.dumps({"name": HOST, "definition": {"nodes": [
        node("triage", "wf_x"), node("second", "wf_x"), node("other", "wf_y")]}}), "utf-8")
    (d / "broken.json").write_text("{not json wf_x", "utf-8")
    (d / "cancel-appointment.json").write_text(json.dumps({"name": "Cancel", "definition": {"nodes": []}}), "utf-8")
    out = await agent_used_by(PID, "wf_x", USER, None)
    assert out == {"workflows": [
        {"workflowId": "handle-appointment-request", "workflowName": HOST, "stepId": "triage"},
        {"workflowId": "handle-appointment-request", "workflowName": HOST, "stepId": "second"}]}


# --- who may ask, and where the paths land ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_project_that_is_not_found_or_not_yours_answers_the_same_as_the_other_agent_routes(project, monkeypatch):
    from routers.agent_step_definitions import agent_from_brief, agent_used_by

    other = uuid.uuid4()
    for call in (agent_from_brief(other, AgentFromBrief(brief=brief()), USER, None), agent_used_by(other, "x", USER, None)):
        with pytest.raises(HTTPException) as e:
            await call
        assert e.value.status_code == 404

    async def not_a_member(project_id, user, db):
        raise HTTPException(status_code=403, detail="Not a member of this organisation")

    monkeypatch.setattr("routers.agent_step_definitions.get_project_with_auth", not_a_member)
    for call in (agent_from_brief(PID, AgentFromBrief(brief=brief()), USER, None), agent_used_by(PID, "x", USER, None)):
        with pytest.raises(HTTPException) as e:
            await call
        assert e.value.status_code == 403
    assert defs(project) == []


def test_the_routes_use_the_same_access_function_as_the_agent_builder():
    import inspect

    import routers.agent_builder as builder
    import routers.agent_step_definitions as mine

    assert mine.get_project_with_auth is builder.get_project_with_auth
    assert "get_project_with_auth(project_id, user, db)" in inspect.getsource(mine.agent_from_brief)
    assert "get_project_with_auth(project_id, user, db)" in inspect.getsource(mine.agent_used_by)


def test_the_paths_are_not_read_as_an_assistants_id(project, monkeypatch):
    """Through the routers in the app's order: `from-brief` and `.../used-by` reach their own handlers, not `GET /{agent_id}`."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth import get_current_user
    from database import get_db
    import routers.agent_builder as builder
    import routers.agent_step_definitions as mine

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", mine.get_project_with_auth)
    app = FastAPI()
    app.include_router(mine.router)
    app.include_router(builder.router)
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_db] = lambda: None
    for r in (mine.router, builder.router):
        app.dependency_overrides[r.dependencies[0].dependency] = lambda: None
    client = TestClient(app)

    made = client.post(f"/api/projects/{PID}/agent-definitions/from-brief",
                       json={"brief": brief().model_dump(exclude_none=True), "workflowId": "FLOW-006", "stepId": "triage"})
    assert made.status_code == 200 and made.json()["agentId"] == AID
    used = client.get(f"/api/projects/{PID}/agent-definitions/{AID}/used-by")
    assert used.status_code == 200 and used.json() == {"workflows": []}
    # and the existing single-assistant route still answers for the assistant itself
    got = client.get(f"/api/projects/{PID}/agent-definitions/{AID}")
    assert got.status_code == 200 and got.json()["id"] == AID
    # a plain 400 sentence reaches the caller as `detail`
    bad = client.post(f"/api/projects/{PID}/agent-definitions/from-brief",
                      json={"brief": {"purpose": "x", "reads": ["Ghosts"]}})
    assert bad.status_code == 400 and "Ghosts" in bad.json()["detail"]

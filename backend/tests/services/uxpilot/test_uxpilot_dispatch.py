"""The page-layouts node has one producer and dispatches per page: a drawn
frame, then the designer the user chose, then A2UI — and a UX Pilot page that
could not be delivered is composed by A2UI and says so."""
from __future__ import annotations

import pytest

from services.blueprint.executors import make_executor
from services.blueprint.orchestrator import TaskSpec
from services.blueprint.service import BlueprintService
from services.uxpilot import generate as g


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Taskboard", domain="Operations")
    s.doc["application"]["uiDesigner"] = "uxpilot"
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Task", "table": "tasks",
                                   "status": "VERIFIED",
                                   "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                                              {"name": "title", "type": "string"}]}]}
    s.doc["pages"] = [{"id": "PAGE-001", "name": "Tasks", "route": "/tasks", "purpose": "x",
                       "pattern": "entity_list", "data": {"primaryEntity": "ENTITY-001"},
                       "status": "VERIFIED"}]
    s.doc["designSystem"] = {"visualPersonality": "calm"}
    s.validate()
    return s


def _spec():
    return TaskSpec(task_id="t1", node="page_layouts", agent="a2ui_pages", subject="PAGE-001")


def _model(*, system, user, schema):
    raise AssertionError("no model call expected on this path")


TREE = {"type": "Stack", "props": {}, "children": [
    {"type": "Heading", "props": {"content": "Tasks", "level": 1}, "children": []}]}


def test_a_uxpilot_page_lands_with_its_provenance(svc, monkeypatch):
    monkeypatch.setattr(g, "compose", lambda *a, **k: g.Outcome(
        root=TREE, data_sources=[{"name": "tasks", "op": "list", "entity": "Task"}],
        design_id="dsg_1", warnings=["button \"export\" was not found"]))
    result = make_executor(svc, _model)(_spec())
    body = result.proposals[0].body
    assert result.proposals[0].section == "pageLayouts" and body["page"] == "PAGE-001"
    assert body["composedBy"] == "uxpilot"
    assert "design dsg_1" in body["rationale"] and "unbound" in body["rationale"]
    assert body["dataSources"] == [{"name": "tasks", "op": "list", "entity": "Task"}]
    assert result.issues == ["button \"export\" was not found"]


def test_a_forge_application_never_calls_uxpilot(svc, monkeypatch):
    svc.doc["application"]["uiDesigner"] = "forge"
    called = []
    monkeypatch.setattr(g, "compose", lambda *a, **k: called.append(1))
    import services.a2ui_authority as a2ui
    monkeypatch.setattr(a2ui, "compose_page_via_a2ui", lambda *a, **k: {
        "applied": True, "root": TREE, "schema": {"dataSources": []}})
    result = make_executor(svc, _model)(_spec())
    assert called == []
    assert result.proposals[0].body["composedBy"] == "a2ui"
    assert result.proposals[0].body["rationale"] == "composed by A2UI (§34)"


def test_the_page_override_wins_over_the_application(svc, monkeypatch):
    svc.doc["application"]["uiDesigner"] = "forge"
    svc.doc["pages"][0]["designedBy"] = "uxpilot"
    monkeypatch.setattr(g, "compose", lambda *a, **k: g.Outcome(root=TREE, design_id="dsg_2"))
    result = make_executor(svc, _model)(_spec())
    assert result.proposals[0].body["composedBy"] == "uxpilot"


def test_a_uxpilot_failure_falls_through_to_a2ui_and_says_so(svc, monkeypatch):
    monkeypatch.setattr(g, "compose", lambda *a, **k: g.Outcome(reason="UX Pilot timeout: session exceeded 60s"))
    import services.a2ui_authority as a2ui
    monkeypatch.setattr(a2ui, "compose_page_via_a2ui", lambda *a, **k: {
        "applied": True, "root": TREE, "schema": {"dataSources": []}})
    result = make_executor(svc, _model)(_spec())
    body = result.proposals[0].body
    assert body["composedBy"] == "a2ui"
    assert "UX Pilot could not design this page (UX Pilot timeout" in body["rationale"]
    assert "Forge UI Designer instead" in body["rationale"]


def test_when_a2ui_also_declines_the_author_is_told_about_the_fallback(svc, monkeypatch):
    monkeypatch.setattr(g, "compose", lambda *a, **k: g.Outcome(reason="UX Pilot returned no HTML"))
    import services.a2ui_authority as a2ui
    monkeypatch.setattr(a2ui, "compose_page_via_a2ui", lambda *a, **k: {
        "applied": False, "reason": "below the substance floor"})
    spec = _spec()
    seen = {}

    def model(*, system, user, schema):
        seen["user"] = user
        return '{"proposals": [], "confidence": 0.95, "assumptions": [], "issues": [], "change_requests": []}'

    make_executor(svc, model)(spec)
    assert "UX Pilot could not design this page" in (spec.feedback or "")
    assert "below the substance floor" in (spec.feedback or "")

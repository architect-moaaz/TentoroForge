"""The `native_code` node, through the executor: one page in, one `nativeCode`
proposal out — the web page's twin, written for the phone. A screen that needs
a change no workflow makes gets the workflow added first, as the web page does,
and a page the application does not have is refused."""
from __future__ import annotations

import pytest

from services.blueprint import executors as ex
from services.blueprint import native_engineer, ui_engineer
from services.blueprint.service import BlueprintService


def _svc(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="F&B", domain="Food")
    svc.doc["mobile"] = {"native": {"enabled": True}, "store": {"bundleId": "com.acme.fb"}}
    svc.doc["pages"] = [{"id": "PAGE-003", "name": "Edit Category", "route": "/admin/categories/[id]",
                         "pattern": "entity_form"}]
    svc.doc["workflows"] = [{"id": "FLOW-001", "name": "Create Category", "steps": []}]
    return svc


def _spec(subject="PAGE-003"):
    return ex.TaskSpec(task_id=f"T-native_code-{subject}", node="native_code", agent="native_engineer", subject=subject)


def test_a_page_comes_back_as_a_native_code_proposal(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    seen = {}

    def compose_screen(doc, page, root, client, **kw):
        seen.update(page=page["id"], root=root, node=kw.get("node"))
        return {"page": page["id"], "screen": "export default function S() { return null; }", "parts": {}}, []

    monkeypatch.setattr(native_engineer, "compose_screen", compose_screen)
    result = ex.make_executor(svc, object())(_spec())
    proposal = result.proposals[0]
    assert (proposal.section, proposal.natural_key) == ("nativeCode", "PAGE-003")
    assert result.agent == "native_engineer" and proposal.body["screen"].startswith("export default")
    assert seen["page"] == "PAGE-003" and seen["node"] == "native_code"
    assert seen["root"] == tmp_path / "native", "the screen is compiled in the native project, beside the web app"


def test_the_missing_workflow_is_added_then_the_screen_is_written(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    calls = []

    def compose_screen(doc, page, root, client, **kw):
        calls.append(("compose", [w["name"] for w in doc["workflows"]]))
        if not any(w["name"] == "Update Category" for w in doc["workflows"]):
            raise ui_engineer.NeedsWorkflow(["update a Category's name"])
        return {"page": page["id"], "screen": "x", "parts": {}}, []

    def add_workflow(svc_, need, *, route, app_root, executor, reasoning, compose):
        calls.append(("add", need, compose))
        svc_.doc["workflows"].append({"id": "FLOW-002", "name": "Update Category", "steps": [], "launchedFrom": ["PAGE-003"]})
        return {"applied": True, "workflow": "FLOW-002", "name": "Update Category"}

    monkeypatch.setattr(native_engineer, "compose_screen", compose_screen)
    monkeypatch.setattr("services.smith.workflow_change.add_workflow", add_workflow)
    result = ex.make_executor(svc, object())(_spec())
    assert result.proposals[0].section == "nativeCode"
    assert [c[0] for c in calls] == ["compose", "add", "compose"] and calls[1][2] is False


def test_a_page_the_application_does_not_have_is_refused(tmp_path):
    with pytest.raises(ValueError, match="is not a page"):
        ex.make_executor(_svc(tmp_path), object())(_spec("PAGE-999"))

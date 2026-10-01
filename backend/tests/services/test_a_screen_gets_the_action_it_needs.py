"""F&B (forge-v3 fxa532bj, 2026-10-01): Edit Category, Edit Menu Item and
Incoming Orders failed the build with "needs a workflow that does not exist
yet" — the plan had edit screens and only Create workflows. SnapIt
(am6t8azx, 2026-09-30) lost Profile and Product Detail the same way. The page
writer was right to refuse a Save that saves nothing; the build now adds the
workflow the page named, then writes the page.
"""
from __future__ import annotations

import pytest

from services.blueprint import executors as ex
from services.blueprint import ui_engineer
from services.blueprint.service import BlueprintService


def _svc(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="F&B", domain="Food")
    svc.doc["pages"] = [{"id": "PAGE-003", "name": "Edit Category", "route": "/admin/categories/[id]",
                         "pattern": "entity_form"}]
    svc.doc["workflows"] = [{"id": "FLOW-001", "name": "Create Category", "steps": []}]
    return svc


def _spec():
    return ex.TaskSpec(task_id="T-page_code-PAGE-003", node="page_code", agent="ui_engineer", subject="PAGE-003")


def test_the_missing_workflow_is_added_then_the_page_is_written(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    calls: list = []

    def compose_page(doc, page, root, client, **kw):
        calls.append(("compose", [w["name"] for w in doc["workflows"]]))
        if not any(w["name"] == "Update Category" for w in doc["workflows"]):
            raise ui_engineer.NeedsWorkflow(["update a Category's name and image"])
        return {"page": page["id"], "view": "\"use client\";", "load": ""}, []

    def add_workflow(svc_, need, *, route, app_root, executor, reasoning, compose):
        calls.append(("add", need, route, compose, callable(executor)))
        svc_.doc["workflows"].append({"id": "FLOW-002", "name": "Update Category", "steps": [],
                                      "launchedFrom": ["PAGE-003"]})
        return {"applied": True, "workflow": "FLOW-002", "name": "Update Category"}

    monkeypatch.setattr(ui_engineer, "compose_page", compose_page)
    monkeypatch.setattr("services.smith.workflow_change.add_workflow", add_workflow)
    result = ex.make_executor(svc, object())(_spec())

    assert result.proposals[0].section == "pageCode" and result.proposals[0].natural_key == "PAGE-003"
    assert calls[0] == ("compose", ["Create Category"])
    # The workflow is added for this page, and the screen is left to the build to write.
    assert calls[1] == ("add", "update a Category's name and image", "/admin/categories/[id]", False, True)
    assert calls[2] == ("compose", ["Create Category", "Update Category"])


def test_a_workflow_that_cannot_be_added_fails_the_page_as_before(tmp_path, monkeypatch):
    from services.smith.workflow_change import WorkflowChangeError
    svc = _svc(tmp_path)

    def compose_page(doc, page, root, client, **kw):
        raise ui_engineer.NeedsWorkflow(["mark an order as fulfilled"])

    def add_workflow(*a, **k):
        raise WorkflowChangeError("the steps were refused twice")

    monkeypatch.setattr(ui_engineer, "compose_page", compose_page)
    monkeypatch.setattr("services.smith.workflow_change.add_workflow", add_workflow)
    with pytest.raises(ui_engineer.NeedsWorkflow, match="mark an order as fulfilled"):
        ex.make_executor(svc, object())(_spec())


def test_smiths_add_workflow_can_leave_the_screen_to_its_caller():
    import inspect
    from services.smith.workflow_change import add_workflow
    assert inspect.signature(add_workflow).parameters["compose"].default is True
    assert "if compose and str((wf.get(\"trigger\")" in inspect.getsource(add_workflow)


def test_the_planner_is_told_a_screen_that_changes_a_record_needs_its_workflow():
    from services.blueprint.executors import NODE_TASKS
    task = NODE_TASKS["workflows"]
    assert "EVERY SCREEN THAT CHANGES A RECORD HAS ITS WORKFLOW" in task
    assert "A create workflow does not edit" in task

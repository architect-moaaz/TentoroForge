"""Self-heal regenerates a missing CRUD workflow that the UI references, so a
Delete/Edit button isn't left pointing at a workflow that was never written."""
import json

from services.self_heal import heal_missing_workflows


def _app(tmp_path, with_delete_workflow=False):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"Member": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}}},
    }))
    wf = tmp_path / "workflows"
    wf.mkdir()
    (wf / "CreateMember.json").write_text('{"name": "CreateMember"}')
    if with_delete_workflow:
        (wf / "DeleteMember.json").write_text('{"name": "DeleteMember"}')
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    # A list page with a Delete row action referencing a workflow that's missing.
    (sdir / "members.json").write_text(json.dumps({
        "route": "/members",
        "root": {"type": "Stack", "children": [
            {"type": "Table", "props": {"rowActions": [
                {"label": "Delete", "action": {"type": "workflow", "workflow": "DeleteMember"}}]}},
        ]},
    }))
    return tmp_path


def test_regenerates_missing_crud_workflow(tmp_path):
    _app(tmp_path, with_delete_workflow=False)
    res = heal_missing_workflows(str(tmp_path))
    assert "Member" in res["entities"]
    assert (tmp_path / "workflows" / "DeleteMember.json").exists()   # regenerated


def test_noop_when_workflow_present(tmp_path):
    _app(tmp_path, with_delete_workflow=True)
    res = heal_missing_workflows(str(tmp_path))
    assert res["entities"] == []


def test_ignores_non_crud_missing_refs(tmp_path):
    # A domain workflow reference that isn't Create/Update/Delete<Entity> is NOT
    # deterministically regenerable — left for flag/neutralize, not fabricated.
    (tmp_path / "registry.json").write_text(json.dumps(
        {"entities": {"Member": {"fields": {"id": {"type": "uuid"}}}}}))
    (tmp_path / "workflows").mkdir()
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    (sdir / "x.json").write_text(json.dumps(
        {"root": {"type": "Button", "props": {"label": "Go", "workflow": "SomeMagicWorkflow"}}}))
    res = heal_missing_workflows(str(tmp_path))
    assert res["entities"] == [] and res["healed"] == []


def test_missing_registry_safe(tmp_path):
    assert heal_missing_workflows(str(tmp_path)) == {"healed": [], "entities": []}

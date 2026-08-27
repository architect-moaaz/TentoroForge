import json

from services.workflow_completeness import (
    ensure_workflow_validity, is_valid_workflow, minimal_workflow,
)


def test_is_valid_workflow_contract():
    assert is_valid_workflow(minimal_workflow("w1", "W1"))
    assert not is_valid_workflow({"id": "x"})                                  # no definition
    assert not is_valid_workflow({"definition": {"trigger": {}, "nodes": [], "edges": []}})  # empty nodes
    # nodes present but no trigger node -> engine's triggerNode.find fails
    assert not is_valid_workflow(
        {"definition": {"trigger": {}, "nodes": [{"id": "a", "type": "action"}], "edges": []}})


def test_repairs_malformed_and_creates_missing(tmp_path):
    wf = tmp_path / "workflows"
    wf.mkdir()
    (wf / "good.json").write_text(json.dumps(minimal_workflow("good", "Good")))
    (wf / "bad.json").write_text(json.dumps(
        {"id": "bad", "name": "Bad", "definition": {"nodes": [], "edges": [], "trigger": {}}}))
    (wf / "broken.json").write_text("{ not valid json")

    plan = {"workflows": [{"name": "Good"}, {"name": "NewFlow", "description": "d"}]}
    res = ensure_workflow_validity(tmp_path, plan)

    # valid file untouched
    assert json.loads((wf / "good.json").read_text()) == minimal_workflow("good", "Good")
    # malformed + unparseable repaired to valid
    assert "bad.json" in res["repaired"] and "broken.json" in res["repaired"]
    assert is_valid_workflow(json.loads((wf / "bad.json").read_text()))
    assert is_valid_workflow(json.loads((wf / "broken.json").read_text()))
    # missing plan workflow created (Good already present, so not duplicated)
    assert res["created"] == ["NewFlow.json"]
    assert is_valid_workflow(json.loads((wf / "NewFlow.json").read_text()))

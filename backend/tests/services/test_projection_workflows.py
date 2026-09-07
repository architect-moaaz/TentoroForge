"""The workflow projection assembles engine definitions from catalog nodes.

The editor picks its node component and properties panel from
``data.nodeType`` and draws edges between top (in) and bottom (out) handles;
the executor dispatches on ``type``. A projected node therefore carries both,
laid out top-to-bottom, with the edges the Blueprint step declared.
"""
import json
from pathlib import Path

from services.blueprint.projection import project_workflows


def _doc(steps, trigger=None):
    return {
        "data": {"entities": [{
            "id": "ENTITY-001", "name": "Ticket", "table": "tickets",
            "fields": [{"name": "id", "type": "uuid", "primaryKey": True}],
        }]},
        "workflows": [{
            "id": "FLOW-001", "name": "Work the ticket queue",
            "trigger": trigger or {"kind": "manual"},
            "steps": steps,
        }],
    }


def _load(tmp_path: Path) -> dict:
    files = list((tmp_path / "src/lib/workflows/definitions").glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_every_node_carries_the_editor_type_and_sits_in_a_column(tmp_path):
    project_workflows(_doc([
        {"key": "read", "name": "Read tickets", "type": "action", "entity": "ENTITY-001",
         "config": {"actionType": "db_query"}},
        {"key": "any", "name": "Any match?", "type": "condition", "config": {"expression": "rows > 0"}},
    ]), tmp_path)
    nodes = _load(tmp_path)["definition"]["nodes"]

    for n in nodes:
        assert n["data"]["nodeType"] == n["type"], n
        assert n["data"]["config"]["nodeType"] == n["type"], n
        assert n["data"]["status"] == "idle"
    assert {n["position"]["x"] for n in nodes} == {250}
    assert [n["position"]["y"] for n in nodes] == [0, 120, 240, 360]
    # node ids are the Blueprint step keys, so `next` and codeMap line up
    assert [n["id"] for n in nodes] == ["trigger", "read", "any", "end"]


def test_a_step_is_its_catalog_node_with_defaults_under_the_declared_config(tmp_path):
    project_workflows(_doc([
        {"key": "review", "name": "Review the frame", "type": "user_task", "entity": "ENTITY-001",
         "config": {"assignType": "role", "assignTarget": "Reviewer"}},
        {"key": "notify", "name": "Notify the owner", "type": "action",
         "config": {"actionType": "send_notification", "toRole": "owner", "message": "Changed"}},
        {"key": "sign", "name": "Sign off", "type": "approval", "config": {"assignTarget": "Manager", "slaHours": 8}},
    ]), tmp_path)
    by_id = {n["id"]: n for n in _load(tmp_path)["definition"]["nodes"]}

    assert by_id["review"]["type"] == "user_task"
    assert by_id["review"]["data"]["config"]["table"] == "tickets"
    assert by_id["notify"]["data"]["config"]["actionType"] == "send_notification"
    assert by_id["notify"]["data"]["config"]["message"] == "Changed"
    cfg = by_id["sign"]["data"]["config"]
    assert cfg["assignType"] == "role" and cfg["approvalType"] == "single"  # catalog defaults
    assert cfg["slaHours"] == 8  # declared wins


def test_condition_rule_lands_on_the_key_the_engine_evaluates(tmp_path):
    project_workflows(_doc([
        {"key": "urgent", "name": "Is it urgent?", "type": "condition",
         "config": {"condition": "priority == 'high'"}},
    ]), tmp_path)
    cond = _load(tmp_path)["definition"]["nodes"][1]
    assert cond["data"]["config"]["expression"] == "priority == 'high'"
    assert "condition" not in cond["data"]["config"]


def test_declared_next_becomes_then_and_else_edges(tmp_path):
    project_workflows(_doc([
        {"key": "check", "name": "Valid?", "type": "condition", "config": {"expression": "ok"},
         "next": ["save", "reject"]},
        {"key": "save", "name": "Save", "type": "action", "entity": "ENTITY-001",
         "config": {"actionType": "db_insert", "values": {"a": "{{a}}"}}, "next": ["done"]},
        {"key": "reject", "name": "Reject", "type": "action",
         "config": {"actionType": "send_notification", "toRole": "user", "message": "no"}, "next": ["check"]},
        {"key": "done", "name": "Done", "type": "end"},
    ]), tmp_path)
    wf = _load(tmp_path)["definition"]
    edges = {(e["source"], e["target"]): e for e in wf["edges"]}

    assert ("trigger", "check") in edges
    assert edges[("check", "save")]["data"] == {"edgeType": "then"}
    assert edges[("check", "reject")]["data"] == {"edgeType": "else"}
    assert edges[("check", "reject")]["sourceHandle"] == "else"
    assert ("save", "done") in edges and ("reject", "check") in edges
    # the declared end step is the terminal; no synthetic end is added
    assert [n["type"] for n in wf["nodes"]].count("end") == 1
    assert not any(e["source"] == "done" for e in wf["edges"])


def test_without_declared_next_steps_chain_in_order(tmp_path):
    project_workflows(_doc([
        {"key": "a", "name": "A", "type": "action", "config": {"actionType": "custom", "code": "x"}},
        {"key": "b", "name": "B", "type": "wait"},
    ]), tmp_path)
    wf = _load(tmp_path)["definition"]
    assert [(e["source"], e["target"]) for e in wf["edges"]] == [
        ("trigger", "a"), ("a", "b"), ("b", "end")]
    assert wf["nodes"][2]["data"]["config"]["duration"] == "1 hour"  # catalog default


def test_trigger_kind_is_a_catalog_trigger_type(tmp_path):
    project_workflows(_doc([], trigger={"kind": "api_event", "detail": "ticket.created"}), tmp_path)
    wf = _load(tmp_path)["definition"]
    assert wf["trigger"] == {"type": "api_event", "event": "ticket.created"}
    assert wf["nodes"][0]["data"]["config"]["type"] == "api_event"

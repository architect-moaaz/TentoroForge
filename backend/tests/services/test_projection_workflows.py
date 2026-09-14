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
    return json.loads(files[0].read_text())


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


# --- who a human step waits on --------------------------------------------------


def test_a_role_assigned_task_names_its_roles_for_the_runtime():
    """The Blueprint states `assignType: role, assignTarget: [...]`; the runtime
    reads `assigneeRole`. Untranslated, a guest's refund request created a task
    filed under "admin" that no inbox showed."""
    from services.blueprint.projection import _name_the_assignee

    config = {"assignType": "role", "assignTarget": ["Reception", "Front Office Manager"]}
    _name_the_assignee(config, "FLOW-002", {"key": "triage_case"})
    assert config["assigneeRole"] == "Reception,Front Office Manager"
    assert "assignee" not in config

    single = {"assignType": "role", "assignTarget": "Finance"}
    _name_the_assignee(single, "FLOW-003", {"key": "post"})
    assert single["assigneeRole"] == "Finance"

    person = {"assignType": "user", "assignTarget": ["ceo@criterion.test"]}
    _name_the_assignee(person, "FLOW-004", {"key": "sign"})
    assert person["assignee"] == "ceo@criterion.test"

    authored = {"assigneeRole": "CEO", "assignType": "role", "assignTarget": ["Finance"]}
    _name_the_assignee(authored, "FLOW-005", {"key": "x"})
    assert authored["assigneeRole"] == "CEO"




# --- what a human step asks, what a set-variable computes, what a gateway counts


def test_a_task_asks_for_what_later_steps_read_off_it():
    """Later steps read `{{triage.overrideReason}}`; the generic task page
    collected a decision and a comment, the placeholder stayed text, and the
    insert failed on a uuid column. What the workflow reads off a task that
    the runtime does not provide is the task's form."""
    from services.blueprint.projection import task_form_fields

    steps = [
        {"key": "triage", "type": "user_task", "config": {"assignType": "role", "assignTarget": ["Reception"]}},
        {"key": "record", "type": "action", "config": {"actionType": "set_variable",
                                                        "value": "{{triage.overrideReason}}"}},
        {"key": "raiser", "type": "action", "config": {"actionType": "set_variable",
                                                        "value": "{{triage.userId}}"}},
        {"key": "insert", "type": "action", "config": {"actionType": "db_insert",
                                                        "values": {"note": "{{triage.overrideReason}}",
                                                                   "who": "{{ triage.completedBy }}"}}},
    ]
    fields = task_form_fields("triage", steps)
    assert fields == [{"name": "overrideReason", "label": "Override reason", "kind": "textarea", "required": True}]


def test_a_set_variable_that_computes_is_an_expression():
    from services.blueprint.projection import _reads_as_expression

    assert _reads_as_expression('refundType in ["Gesture (SR)", "Early Departure"]')
    assert _reads_as_expression("amountRequested > 100 and isServiceRecovery")
    assert not _reads_as_expression("Pending approval")
    assert not _reads_as_expression("{{triage.overrideReason}}")
    assert not _reads_as_expression(12)


def test_a_gateway_counts_a_query_s_rows_not_its_keys():
    """A db_query answers `{rows, count}`; `count(check_duplicates)` counted
    the object's two keys, so "Duplicate case found?" was always yes."""
    from services.blueprint.projection import _step_config
    from services.catalog import workflow_nodes

    catalog = workflow_nodes()
    steps = [
        {"key": "check_duplicates", "type": "action",
         "config": {"actionType": "db_query", "table": "refund_cases", "where": {"confirmationNumber": "{{confirmationNumber}}"}}},
        {"key": "duplicate_gateway", "type": "condition", "config": {"expression": "count(check_duplicates) > 0"}},
        {"key": "flag", "type": "action",
         "config": {"actionType": "set_variable", "variableName": "isServiceRecovery",
                    "value": 'refundType in ["Gesture (SR)"]'}},
        {"key": "triage", "type": "user_task", "config": {"assignType": "role", "assignTarget": ["Reception"]}},
        {"key": "record", "type": "action", "config": {"actionType": "set_variable", "variableName": "reason",
                                                        "value": "{{triage.overrideReason}}"}},
    ]
    gate = _step_config(steps[1], {}, catalog, wf_id="FLOW-002", steps=steps)
    assert gate["expression"] == "check_duplicates.count > 0"
    flag = _step_config(steps[2], {}, catalog, wf_id="FLOW-002", steps=steps)
    assert flag["expression"] == 'refundType in ["Gesture (SR)"]' and "value" not in flag
    record = _step_config(steps[4], {}, catalog, wf_id="FLOW-002", steps=steps)
    assert record["value"] == "{{triage.overrideReason}}" and "expression" not in record
    triage = _step_config(steps[3], {}, catalog, wf_id="FLOW-002", steps=steps)
    assert triage["assigneeRole"] == "Reception"
    assert triage["formBinding"] == {"fields": [
        {"name": "overrideReason", "label": "Override reason", "kind": "textarea", "required": True}]}

# backend/tests/services/test_llm_plan_binding_adapter.py
from services.llm_plan_binding_adapter import build_page_intent

_PLAN = {
    "data_models": [{"name": "LeaveRequest", "fields": [{"name": "id"}]}],
    "workflows": [{"name": "LeaveApprovalWorkflow"}],
}


def test_passthrough_validated_page_actions():
    page = {"route": "/leave-requests", "file": "src/schemas/leave-requests.json",
            "entity": "LeaveRequest", "actions": [
                {"label": "Approve", "workflow": "LeaveApprovalWorkflow", "kind": "row_action"},
                {"label": "Bad", "workflow": "GhostWorkflow", "kind": "row_action"},
                {"label": "WrongKind", "workflow": "LeaveApprovalWorkflow", "kind": "nope"},
            ]}
    intent = build_page_intent(page, _PLAN)
    assert intent["entity"] == "LeaveRequest"
    assert intent["file"] == "src/schemas/leave-requests.json"
    # bad workflow + bad kind dropped
    assert intent["actions"] == [
        {"label": "Approve", "workflow": "LeaveApprovalWorkflow", "kind": "row_action"}]


def test_derive_from_api_strategy_when_no_page_actions():
    page = {"route": "/leave-requests", "entity": "LeaveRequest"}
    plan = {**_PLAN, "api_strategy": {"LeaveRequest": {"workflow_actions": [
        {"trigger": "button:Approve", "workflow": "LeaveApprovalWorkflow", "ui_location": "list_page"},
        {"trigger": "button:Audit", "workflow": "LeaveApprovalWorkflow", "ui_location": "detail_page"},
    ]}}}
    intent = build_page_intent(page, plan)
    assert intent["actions"] == [
        {"label": "Approve", "workflow": "LeaveApprovalWorkflow", "kind": "row_action"},
        {"label": "Audit", "workflow": "LeaveApprovalWorkflow", "kind": "page_action"},
    ]


def test_empty_when_no_source():
    page = {"route": "/x", "entity": "LeaveRequest"}
    intent = build_page_intent(page, _PLAN)
    assert intent["actions"] == []
    assert intent["file"] == "src/schemas/x.json"


def test_adapter_plus_apply_bindings_wires_llm_button():
    from services.schema_binding import apply_bindings, iter_nodes
    plan = {
        "data_models": [{"name": "Driver", "fields": [{"name": "id"}, {"name": "name"}]}],
        "workflows": [{"name": "ApproveDriver"}],
        "pages": [{"route": "/drivers", "entity": "Driver",
                   "file": "src/schemas/drivers.json",
                   "actions": [{"label": "Approve", "workflow": "ApproveDriver", "kind": "row_action"}]}],
    }
    page = plan["pages"][0]
    # LLM-shaped schema: data already bound, button not yet wired.
    schema = {"schemaVersion": "2", "id": "drivers",
              "dataSources": [{"name": "driver", "entity": "Driver", "op": "list"}],
              "root": {"id": "r", "type": "Stack", "children": [
                  {"id": "rep", "type": "Repeat", "bind": "driver", "children": [
                      {"id": "row", "type": "Card", "children": [
                          {"id": "btn", "type": "Button", "props": {"label": "Approve"}}]}]}]}}
    intent = build_page_intent(page, plan)
    out, report = apply_bindings(schema, intent, plan)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert btn["props"]["workflow"] == "ApproveDriver"
    assert btn["props"]["args"]["id"] == "{{item.id}}"
    assert report["buttons_bound"] == 1 and report["list_skipped"] is True


def test_build_page_intent_keeps_navigate_actions():
    from services.llm_plan_binding_adapter import build_page_intent
    page = {"route": "/tasks", "entity": "Task", "file": "src/schemas/tasks.json",
            "actions": [{"label": "New", "kind": "navigate", "to": "/tasks/new"}]}
    intent = build_page_intent(page, {"workflows": []})
    assert {"label": "New", "kind": "navigate", "to": "/tasks/new"} in intent["actions"]

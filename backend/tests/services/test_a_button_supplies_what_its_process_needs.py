"""A control must be able to send every required input of the process it
starts. "Mark all read" on a workflow that requires the acting user answered
HTTP 422 on every click (UAT F&B, fxa532bj)."""
import json
import logging

from services.control_inputs_guard import ensure_controls_supply_inputs

NOTHING = {"findings": [], "repaired": [], "workflows_touched": []}


def _app(tmp_path, required, root, where=None):
    wf = {"id": "flow-006", "name": "Mark Notifications Read", "requiredInputs": required,
          "definition": {"nodes": [{"id": "n", "data": {"config": {
              "actionType": "db_update", "table": "notifications",
              "where": where or {"userId": "{{userId}}"}, "values": {"read": True}}}}]}}
    d = tmp_path / "src/lib/workflows/definitions"
    d.mkdir(parents=True)
    (d / "mark-notifications-read.json").write_text(json.dumps(wf))
    s = tmp_path / "src/schemas/admin"
    s.mkdir(parents=True)
    (s / "notifications.json").write_text(json.dumps({"route": "/admin/notifications", "root": root}))
    return d / "mark-notifications-read.json"


def _btn(**props):
    return {"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "Mark all read (7)", "workflow": "FLOW-006", **props}}]}


def test_mark_all_button_cannot_supply_the_acting_user_so_it_is_repaired(tmp_path):
    wf = _app(tmp_path, ["userId"], _btn())
    r = ensure_controls_supply_inputs(str(tmp_path))
    assert [x["input"] for x in r["repaired"]] == ["userId"]
    assert r["findings"] == []
    doc = json.loads(wf.read_text())
    assert doc["requiredInputs"] == []
    assert "{{user.id}}" in json.dumps(doc["definition"])


def test_an_input_nothing_can_supply_is_a_named_blocking_finding(tmp_path, caplog):
    _app(tmp_path, ["notification"], _btn(), where={"id": "{{notification}}"})
    with caplog.at_level(logging.WARNING, logger="services.control_inputs_guard"):
        r = ensure_controls_supply_inputs(str(tmp_path))
    (f,) = r["findings"]
    assert (f["page"], f["control"], f["workflow"], f["input"]) == (
        "admin/notifications.json", "Button", "Mark Notifications Read", "notification")
    assert "422" in f["detail"]
    assert any("control_inputs_guard" in m and "notification" in m for m in caplog.messages)


def test_a_button_that_supplies_everything_has_no_finding(tmp_path):
    wf = _app(tmp_path, ["userId"], _btn(args={"userId": "{{session.id}}"}))
    before = wf.read_text()
    assert ensure_controls_supply_inputs(str(tmp_path)) == NOTHING
    assert wf.read_text() == before


def test_a_form_field_and_a_row_supply_inputs(tmp_path):
    root = {"type": "Form", "props": {"workflow": "FLOW-006", "fields": [{"name": "notification"}]}}
    wf = _app(tmp_path, ["notification"], root, where={"id": "{{notification}}"})
    assert ensure_controls_supply_inputs(str(tmp_path)) == NOTHING
    # a row sends its id, which is what a declared record input is
    doc = json.loads(wf.read_text())
    doc["recordInputs"] = [{"name": "notification", "table": "notifications"}]
    wf.write_text(json.dumps(doc))
    row = {"type": "Table", "props": {"rowActions": [{"label": "Read", "workflow": "FLOW-006"}]}}
    (tmp_path / "src/schemas/admin/notifications.json").write_text(json.dumps({"route": "/x", "root": row}))
    assert ensure_controls_supply_inputs(str(tmp_path)) == NOTHING


def test_an_unread_required_input_is_dropped_not_guessed(tmp_path):
    wf = _app(tmp_path, ["note"], _btn())
    r = ensure_controls_supply_inputs(str(tmp_path))
    assert r["findings"] == [] and r["repaired"][0]["input"] == "note"
    assert json.loads(wf.read_text())["requiredInputs"] == []


def test_rerun_is_idempotent(tmp_path):
    wf = _app(tmp_path, ["userId"], _btn())
    ensure_controls_supply_inputs(str(tmp_path))
    after = wf.read_text()
    assert ensure_controls_supply_inputs(str(tmp_path)) == NOTHING
    assert wf.read_text() == after

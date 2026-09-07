"""The page agent invents status-transition action refs (confirmAppointment) while
the business-logic agent produces one consolidated status workflow
(AppointmentStatusWorkflow updating appointments.status via {appointmentId,
targetStatus}). The mapper bridges them so those buttons dispatch the REAL
workflow with the right args instead of a dead ref."""
import json

from services.workflow_action_mapper import (
    index_status_workflows,
    derive_target_status,
    map_status_action,
)


# A realistic status workflow: a db_update node setting appointments.status from a
# `targetStatus` var, keyed off `appointmentId`, with the allowed transitions in a
# condition expression.
STATUS_WF = {
    "id": "6ae8ad74",
    "name": "AppointmentStatusWorkflow",
    "processVariables": [
        {"name": "appointmentId", "type": "string"},
        {"name": "targetStatus", "type": "string"},
        {"name": "currentStatus", "type": "string"},
    ],
    "definition": {
        "nodes": [
            {"id": "validate", "type": "condition", "data": {"config": {
                "expression": '(currentStatus == "scheduled" && (targetStatus == "confirmed" '
                              '|| targetStatus == "cancelled")) || (currentStatus == "confirmed" '
                              '&& (targetStatus == "completed" || targetStatus == "cancelled"))'
            }}},
            {"id": "upd", "type": "action", "data": {"config": {
                "actionType": "db_update",
                "table": "appointments",
                "where": {"id": "appointmentId"},
                "values": {"status": "targetStatus", "updated_at": "NOW()"},
            }}},
        ]
    },
}


def _write_wf(tmp_path, obj, fname):
    wdir = tmp_path / "workflows"
    wdir.mkdir(exist_ok=True)
    (wdir / fname).write_text(json.dumps(obj), encoding="utf-8")


def test_index_finds_status_workflow_and_its_call_shape(tmp_path):
    _write_wf(tmp_path, STATUS_WF, "6ae8ad74.json")
    # A CRUD workflow that updates the table but NOT status must be ignored.
    _write_wf(tmp_path, {"name": "UpdateAppointment", "definition": {"nodes": [
        {"data": {"config": {"actionType": "db_update", "table": "appointments",
                             "where": {"id": "id"}, "values": {"notes": "notes"}}}}
    ]}}, "UpdateAppointment.json")

    idx = index_status_workflows(tmp_path)
    assert "appointment" in idx                     # singular key from "appointments"
    info = idx["appointment"]
    assert info["name"] == "AppointmentStatusWorkflow"
    assert info["id_var"] == "appointmentId"
    assert info["status_var"] == "targetStatus"
    # Only TARGET values (targetStatus == "X") are harvested; "scheduled" appears
    # solely as a currentStatus guard, so it's correctly excluded.
    assert set(info["statuses"]) == {"confirmed", "cancelled", "completed"}


def test_index_no_dir_is_safe(tmp_path):
    assert index_status_workflows(tmp_path) == {}


def test_derive_prefers_workflows_known_status_value():
    statuses = ["scheduled", "confirmed", "cancelled", "completed"]
    assert derive_target_status("Confirm", statuses) == "confirmed"
    assert derive_target_status("Cancel", statuses) == "cancelled"
    assert derive_target_status("Complete", statuses) == "completed"


def test_derive_label_equal_to_status():
    assert derive_target_status("Completed", ["completed", "pending"]) == "completed"


def test_derive_unmappable_returns_none():
    # "Export" isn't a transition; must not be force-mapped.
    assert derive_target_status("Export", ["confirmed", "cancelled"]) is None


def test_derive_falls_back_to_canonical_when_no_known_statuses():
    assert derive_target_status("Approve", []) == "approved"


def test_map_status_action_builds_workflow_call(tmp_path):
    _write_wf(tmp_path, STATUS_WF, "6ae8ad74.json")
    idx = index_status_workflows(tmp_path)

    # entity given as PascalCase singular (registry shape) must still resolve.
    got = map_status_action("Confirm", "Appointment", idx)
    assert got == {
        "workflow": "AppointmentStatusWorkflow",
        "args": {"appointmentId": "{{item.id}}", "targetStatus": "confirmed"},
    }


def test_map_status_action_unknown_entity_returns_none(tmp_path):
    _write_wf(tmp_path, STATUS_WF, "6ae8ad74.json")
    idx = index_status_workflows(tmp_path)
    assert map_status_action("Confirm", "Invoice", idx) is None       # no status wf
    assert map_status_action("Confirm", "Appointment", {}) is None    # empty index

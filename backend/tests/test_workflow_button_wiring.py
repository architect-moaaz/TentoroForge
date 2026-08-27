"""Harden action-button wiring for the single-execution-path model: every Button's
`props.workflow` must resolve to a real runtime cache key. The runtime caches each
workflow by BOTH `definition.id` and `definition.name`, so a camelCase reference like
`createLeaveRequest` (file id `create-leaverequest`, name `CreateLeaveRequest`) is a
DEAD dispatch. The guard canonicalizes such references to a real key and neutralizes
true phantoms.
"""
from services.schema_binding import canonicalize_and_guard_workflow_buttons as guard
from services.crud_actions import build_workflow_index


# Mirrors the runtime cache: keyed by id AND name; canonical target is the name.
INDEX = {
    "exact": ["create-leaverequest", "CreateLeaveRequest", "leave-review", "LeaveReviewWorkflow"],
    "norm": {
        "createleaverequest": "CreateLeaveRequest",
        "leavereview": "LeaveReviewWorkflow",
        "leavereviewworkflow": "LeaveReviewWorkflow",
    },
}


def _btn(wf, **extra):
    p = {"label": "X"}
    if wf is not None:
        p["workflow"] = wf
    p.update(extra)
    return {"type": "Button", "props": p}


def _tree(*buttons):
    return {"root": {"type": "Stack", "children": list(buttons)}}


def test_camelcase_mismatch_is_canonicalized_to_a_real_cache_key():
    schema = _tree(_btn("createLeaveRequest", args={"id": "{{item.id}}"}))
    out, info = guard(schema, INDEX)
    b = out["root"]["children"][0]["props"]
    assert b["workflow"] == "CreateLeaveRequest"      # rewritten to a real key
    assert b["args"] == {"id": "{{item.id}}"}         # args preserved
    assert info["workflows_canonicalized"] == 1
    assert info["workflows_neutralized"] == 0


def test_exact_key_is_left_untouched():
    schema = _tree(_btn("leave-review"))
    out, info = guard(schema, INDEX)
    assert out["root"]["children"][0]["props"]["workflow"] == "leave-review"
    assert info["workflows_canonicalized"] == 0
    assert info["workflows_neutralized"] == 0


def test_true_phantom_is_neutralized():
    schema = _tree(_btn("doesNotExist", args={"id": "1"}))
    out, info = guard(schema, INDEX)
    p = out["root"]["children"][0]["props"]
    assert "workflow" not in p and "args" not in p
    assert info["workflows_neutralized"] == 1


def test_namespaced_builtin_is_ignored():
    # auth.signOut etc. are renderer builtins, not workflow files.
    schema = _tree(_btn("auth.signOut"))
    out, info = guard(schema, INDEX)
    assert out["root"]["children"][0]["props"]["workflow"] == "auth.signOut"
    assert info["workflows_neutralized"] == 0
    assert info["workflows_canonicalized"] == 0


def test_empty_index_is_noop():
    schema = _tree(_btn("whatever"))
    out, info = guard(schema, {"exact": [], "norm": {}})
    assert out["root"]["children"][0]["props"]["workflow"] == "whatever"
    assert info["workflows_neutralized"] == 0
    assert info["workflows_canonicalized"] == 0


def test_button_without_workflow_untouched():
    schema = _tree(_btn(None, navigate="/x"))
    out, info = guard(schema, INDEX)
    p = out["root"]["children"][0]["props"]
    assert p.get("navigate") == "/x" and "workflow" not in p


# Status-transition index shape produced by index_status_workflows(), letting the
# guard MAP an invented action to the real workflow instead of dropping it.
STATUS_INDEX = {
    "appointment": {
        "name": "AppointmentStatusWorkflow",
        "table": "appointments",
        "id_var": "appointmentId",
        "status_var": "targetStatus",
        "statuses": ["confirmed", "cancelled", "completed"],
    }
}


def test_phantom_status_row_action_is_mapped_not_dropped():
    schema = _table_with_row_actions(
        _ra("Confirm", "confirmAppointment"),
        _ra("Cancel", "cancelAppointment"),
    )
    out, info = guard(schema, INDEX, status_index=STATUS_INDEX, entity="Appointment")
    ras = out["root"]["children"][0]["props"]["rowActions"]
    assert [r["label"] for r in ras] == ["Confirm", "Cancel"]     # kept, not dropped
    assert ras[0]["action"] == {"type": "workflow", "workflow": "AppointmentStatusWorkflow",
                                "args": {"appointmentId": "{{item.id}}", "targetStatus": "confirmed"}}
    assert ras[1]["action"]["args"]["targetStatus"] == "cancelled"
    assert info["workflows_mapped"] == 2
    assert info["workflows_neutralized"] == 0


def test_unmappable_status_row_action_still_dropped():
    # "Export" isn't a status transition → no mapping → dropped as before.
    schema = _table_with_row_actions(_ra("Export", "exportAppointments"))
    out, info = guard(schema, INDEX, status_index=STATUS_INDEX, entity="Appointment")
    assert out["root"]["children"][0]["props"]["rowActions"] == []
    assert info["workflows_mapped"] == 0
    assert info["workflows_neutralized"] == 1


def test_phantom_button_is_mapped_when_status_index_present():
    schema = _tree(_btn("confirmAppointment", label="Confirm"))
    out, info = guard(schema, INDEX, status_index=STATUS_INDEX, entity="Appointment")
    p = out["root"]["children"][0]["props"]
    assert p["workflow"] == "AppointmentStatusWorkflow"
    assert p["args"] == {"appointmentId": "{{item.id}}", "targetStatus": "confirmed"}
    assert info["workflows_mapped"] == 1


def _table_with_row_actions(*actions):
    # Mirrors the real page-agent output: a data node whose props.rowActions carry
    # {label, action: {type: "workflow", workflow}} entries (NOT Button nodes).
    return {"root": {"type": "Stack", "children": [
        {"type": "Table", "props": {"rowActions": list(actions)}},
    ]}}


def _ra(label, wf):
    return {"label": label, "action": {"type": "workflow", "workflow": wf}}


def test_row_action_camelcase_is_canonicalized():
    schema = _table_with_row_actions(_ra("Submit", "createLeaveRequest"))
    out, info = guard(schema, INDEX)
    ra = out["root"]["children"][0]["props"]["rowActions"][0]
    assert ra["action"]["workflow"] == "CreateLeaveRequest"   # rewritten to a real key
    assert info["workflows_canonicalized"] == 1
    assert info["workflows_neutralized"] == 0


def test_row_action_phantom_entry_is_dropped():
    # A row action pointing at a workflow that exists nowhere (no status field, no
    # real workflow) is a dead button — drop the whole entry so it never renders.
    schema = _table_with_row_actions(
        _ra("Confirm", "confirmAppointment"),
        _ra("Cancel", "cancelAppointment"),
        _ra("Edit", "leave-review"),          # exact key → kept
    )
    out, info = guard(schema, INDEX)
    remaining = out["root"]["children"][0]["props"]["rowActions"]
    labels = [r["label"] for r in remaining]
    assert labels == ["Edit"]                  # both phantoms dropped, real kept
    assert info["workflows_neutralized"] == 2


def test_row_action_exact_key_untouched():
    schema = _table_with_row_actions(_ra("Review", "leave-review"))
    out, info = guard(schema, INDEX)
    remaining = out["root"]["children"][0]["props"]["rowActions"]
    assert remaining[0]["action"]["workflow"] == "leave-review"
    assert info["workflows_neutralized"] == 0
    assert info["workflows_canonicalized"] == 0


def test_row_action_empty_index_is_noop():
    schema = _table_with_row_actions(_ra("Confirm", "confirmAppointment"))
    out, info = guard(schema, {"exact": [], "norm": {}})
    assert out["root"]["children"][0]["props"]["rowActions"][0]["label"] == "Confirm"
    assert info["workflows_neutralized"] == 0


def test_build_workflow_index_from_files(tmp_path):
    wf = tmp_path / "workflows"
    wf.mkdir()
    (wf / "CreateLeaveRequest.json").write_text(
        '{"id": "create-leaverequest", "name": "CreateLeaveRequest"}'
    )
    (wf / "leave-review.json").write_text(
        '{"id": "leave-review", "name": "LeaveReviewWorkflow"}'
    )
    idx = build_workflow_index(tmp_path)
    # exact keys = every id + name (the runtime cache keys)
    assert "CreateLeaveRequest" in idx["exact"]
    assert "create-leaverequest" in idx["exact"]
    assert "LeaveReviewWorkflow" in idx["exact"]
    # normalized lookups collapse casing/separators to the canonical name
    assert idx["norm"]["createleaverequest"] == "CreateLeaveRequest"
    assert idx["norm"]["leavereview"] == "LeaveReviewWorkflow"


def test_build_workflow_index_no_dir_is_safe(tmp_path):
    idx = build_workflow_index(tmp_path)
    assert idx == {"exact": [], "norm": {}}

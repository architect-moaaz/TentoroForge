"""Seam 5: row-level Approve/Reject must carry a DISTINCT decision so the execute
route can resolve+resume the pending approval task with the manager's choice.
Previously both dispatched identical args and were indistinguishable no-ops."""
from services.schema_binding import annotate_decision_actions


def _btn(label, wf="leave-review", args=None):
    p = {"label": label}
    if wf is not None:
        p["workflow"] = wf
    p["args"] = {"id": "{{item.id}}"} if args is None else args
    return {"type": "Button", "props": p}


def _tree(*b):
    return {"root": {"type": "Stack", "children": list(b)}}


def test_approve_and_reject_get_distinct_decisions():
    s = _tree(_btn("Approve"), _btn("Reject"))
    out, info = annotate_decision_actions(s)
    kids = out["root"]["children"]
    assert kids[0]["props"]["args"]["__decision"] == "approved"
    assert kids[1]["props"]["args"]["__decision"] == "rejected"
    assert kids[0]["props"]["args"]["id"] == "{{item.id}}"   # entity id preserved
    assert info["decisions_annotated"] == 2


def test_synonyms_map_to_the_right_decision():
    s = _tree(_btn("Accept request"), _btn("Deny"))
    out, info = annotate_decision_actions(s)
    kids = out["root"]["children"]
    assert kids[0]["props"]["args"]["__decision"] == "approved"
    assert kids[1]["props"]["args"]["__decision"] == "rejected"


def test_non_decision_workflow_button_untouched():
    s = _tree({"type": "Button", "props": {"label": "Save", "workflow": "CreateX", "args": {}}})
    out, info = annotate_decision_actions(s)
    assert "__decision" not in out["root"]["children"][0]["props"]["args"]
    assert info["decisions_annotated"] == 0


def test_button_without_workflow_ignored():
    # An approve-labelled button that only navigates isn't a workflow dispatch.
    s = _tree({"type": "Button", "props": {"label": "Approve", "navigate": "/x"}})
    out, info = annotate_decision_actions(s)
    assert info["decisions_annotated"] == 0


def test_idempotent():
    s = _tree(_btn("Approve"))
    annotate_decision_actions(s)
    _, info = annotate_decision_actions(s)
    assert info["decisions_annotated"] == 0
    assert s["root"]["children"][0]["props"]["args"]["__decision"] == "approved"

"""Slice 0 of the validate→repair loop: statically catch the biggest 'buttons do
nothing' cause — an actionable Button with NO resolvable action — and auto-wire the
confident cases (New <Entity> → /entity/new), flagging the rest as findings."""
from services.button_audit import audit_button_actions

IDX = {"exact": ["CreateReservation"], "norm": {"createreservation": "CreateReservation"}}
ROUTES = ["/", "/reservations", "/reservations/new", "/reservations/[id]", "/guests"]


def _btn(label, **p):
    return {"type": "Button", "props": {"label": label, **p}}


def _tree(*b):
    return {"root": {"type": "Stack", "children": list(b)}}


def test_flags_button_with_no_action():
    schema, findings = audit_button_actions(_tree(_btn("Approve")), ROUTES, IDX)
    assert any(f["type"] == "dead_button" and f["buttonLabel"] == "Approve" for f in findings)


def test_autowires_new_button_to_create_route():
    schema, findings = audit_button_actions(_tree(_btn("New Reservation")), ROUTES, IDX)
    assert schema["root"]["children"][0]["props"].get("navigate") == "/reservations/new"
    assert findings == []


def test_button_with_navigate_is_ok():
    schema, findings = audit_button_actions(_tree(_btn("Guests", navigate="/guests")), ROUTES, IDX)
    assert findings == []


def test_button_with_workflow_is_ok():
    schema, findings = audit_button_actions(_tree(_btn("Create", workflow="CreateReservation")), ROUTES, IDX)
    assert findings == []


def test_cancel_and_submit_in_form_not_flagged():
    schema = {"root": {"type": "Form", "children": [
        _btn("Save", variant="primary"),   # form owns submit
        _btn("Cancel"),                      # cancel
    ]}}
    _, findings = audit_button_actions(schema, ROUTES, IDX)
    assert findings == []


def test_carries_route_in_finding_when_given():
    _, findings = audit_button_actions(_tree(_btn("Frobnicate")), ROUTES, IDX, route="/dash")
    assert findings and findings[0]["route"] == "/dash"

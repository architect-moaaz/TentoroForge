"""Task 4 re-test: only a real either/or choice is converted, the emptied row is
removed, the choice reaches the workflow, hidden fields stop being required,
and the guard runs in the suite."""
import json

import pytest

from services.choice_control_guard import ensure_choices_are_controls


def missing_required(wf, inp):
    """templates/runtime/workflows/required-inputs.ts: a required input that is empty is missing."""
    return [n for n in (wf.get("requiredInputs") or []) if inp.get(n) in (None, "")]


def _btn(label, **p):
    return {"type": "Button", "props": {"label": label, **p}}


def _app(tmp_path, buttons, wf=None, schema_cols=None):
    page = {"route": "/order", "root": {"type": "Stack", "children": [
        {"type": "Row", "children": buttons},
        {"type": "Form", "props": {"workflow": "FLOW-1", "fields": [
            {"kind": "text", "name": "tableNumber", "label": "Table number"},
            {"kind": "text", "name": "deliveryAddress", "label": "Delivery address"}]}}]}}
    p = tmp_path / "src/schemas/order.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(page, indent=2))
    w = tmp_path / "workflows/order.json"
    w.parent.mkdir(parents=True)
    w.write_text(json.dumps(wf or {"id": "FLOW-1", "name": "Place Order", "requiredInputs": ["tableNumber", "deliveryAddress"],
                                   "inputs": [{"name": "tableNumber", "required": True}, {"name": "deliveryAddress", "required": True}],
                                   "definition": {"nodes": [{"data": {"config": {"actionType": "db_insert", "table": "orders",
                                                                              "values": {"tableNumber": "{{tableNumber}}"}}}}]}}))
    if schema_cols is not None:
        s = tmp_path / "src/db/schema/orders.ts"
        s.parent.mkdir(parents=True)
        cols = "\n".join(f'  {c}: text("{c}"),' for c in schema_cols)
        s.write_text(f'export const orders = pgTable("orders", {{\n  id: uuid("id").primaryKey(),\n{cols}\n}});\n')
    return p, w


@pytest.mark.parametrize("labels", [("Cancel", "Save"), ("Yes", "No"), ("Previous", "Next"), ("+", "-"),
                                    ("Overview", "Details", "History"), ("OK", "Cancel"), ("Delete", "Cancel"),
                                    ("Edit", "Remove")])
def test_ordinary_buttons_beside_a_form_are_never_made_a_choice(tmp_path, labels):
    p, _ = _app(tmp_path, [_btn(l) for l in labels])
    before = p.read_text()
    assert ensure_choices_are_controls(str(tmp_path)) == {"converted": [], "findings": []}
    assert p.read_text() == before


def test_a_danger_variant_is_never_an_option(tmp_path):
    p, _ = _app(tmp_path, [_btn("Dine-in"), _btn("Delivery", variant="danger")])
    assert ensure_choices_are_controls(str(tmp_path))["converted"] == []


def test_a_recognised_family_is_converted_and_the_empty_row_goes(tmp_path):
    p, _ = _app(tmp_path, [_btn("Dine-in"), _btn("Takeaway")])
    assert ensure_choices_are_controls(str(tmp_path))["converted"]
    root = json.loads(p.read_text())["root"]
    assert [c["type"] for c in root["children"]] == ["Form"]                       # no empty Row left behind


def test_the_choice_reaches_the_workflow_and_hidden_fields_stop_being_required(tmp_path):
    p, w = _app(tmp_path, [_btn("Dine-in"), _btn("Delivery")], schema_cols=["tableNumber", "deliveryAddress", "orderType"])
    ensure_choices_are_controls(str(tmp_path))
    wf = json.loads(w.read_text())
    assert wf["requiredInputs"] == []
    assert any(i["name"] == "orderType" and not i["required"] for i in wf["inputs"])
    node = wf["definition"]["nodes"][0]["data"]["config"]
    assert node["values"]["orderType"] == "{{orderType}}"
    # the engine's own rule: a delivery order with no table number is no longer refused
    assert missing_required(wf, {"orderType": "delivery", "deliveryAddress": "1 Main St"}) == []


def test_a_choice_with_no_column_is_a_named_finding_not_a_silent_loss(tmp_path):
    _p, w = _app(tmp_path, [_btn("Dine-in"), _btn("Delivery")], schema_cols=["tableNumber", "deliveryAddress"])
    r = ensure_choices_are_controls(str(tmp_path))
    assert any("no column" in f.get("detail", "") for f in r["findings"])
    assert "orderType" not in json.dumps(json.loads(w.read_text())["definition"])


def test_the_guard_runs_in_the_suite_and_is_idempotent(tmp_path):
    from services.post_generate_fixes import apply_post_generate_fixes_with_result
    p, _w = _app(tmp_path, [_btn("Dine-in"), _btn("Delivery")], schema_cols=["tableNumber", "deliveryAddress", "orderType"])
    apply_post_generate_fixes_with_result(str(tmp_path), force=True)
    page = json.loads(p.read_text())
    form = next(n for n in page["root"]["children"] if n["type"] == "Form")
    assert form["props"]["fields"][0]["kind"] == "choice"
    assert ensure_choices_are_controls(str(tmp_path)) == {"converted": [], "findings": []}

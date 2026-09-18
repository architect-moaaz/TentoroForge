"""An optional input a step writes is still something the form must collect.

The authoring check skipped every optional input; the engine's dry run
(templates/runtime/workflows/dry-run.ts) refuses any `{{name}}` a step writes
that the payload leaves empty, optional or not. So Neighbourhood Kit's
"Add Listing" and "Submit Decision" passed composition and failed `assemble`
(UAT, 2026-09-18) for latitude/longitude and agreedStartDate/agreedEndDate —
found after the pages were paid for. The two checks now apply one rule.
"""
from services.blueprint.functional_completeness import unsatisfied_inputs


def _doc(values):
    return {
        "pages": [{"id": "PAGE-001", "route": "/tools/new"}],
        "data": {"entities": []},
        "security": {"ownershipRules": []},
        "workflows": [{"id": "FLOW-003", "name": "Create Tool Listing",
                       "inputs": [
                           {"name": "title", "kind": "field", "required": True},
                           {"name": "latitude", "kind": "field", "required": False},
                           {"name": "notes", "kind": "field", "required": False},
                       ],
                       "steps": [{"key": "insert_listing", "type": "action", "config": {
                           "actionType": "db_insert", "table": "tool_listings",
                           "values": values}}]}],
    }


def _form(*names):
    submit = {"type": "Button", "props": {"label": "Add Listing", "workflow": "FLOW-003"}}
    form = {"type": "Form", "props": {"fields": [{"name": n, "label": n} for n in names]},
            "children": [submit]}
    return {"root": form}, submit


def _missing(doc, layout, control):
    return " ".join(unsatisfied_inputs(doc, doc["pages"][0], layout, control, "FLOW-003"))


def test_an_optional_input_a_step_writes_must_be_collected():
    doc = _doc({"title": "{{title}}", "latitude": "{{latitude}}"})
    layout, submit = _form("title")
    assert "'latitude'" in _missing(doc, layout, submit)


def test_collecting_it_satisfies_the_check():
    doc = _doc({"title": "{{title}}", "latitude": "{{latitude}}"})
    layout, submit = _form("title", "latitude")
    assert "latitude" not in _missing(doc, layout, submit)


def test_an_optional_input_nothing_writes_may_still_be_left_out():
    """`notes` is declared but no step templates it: the dry run never reads
    it, so demanding it would be a rule the engine does not have."""
    doc = _doc({"title": "{{title}}"})
    layout, submit = _form("title")
    assert "notes" not in _missing(doc, layout, submit)


# ---- a form collects a field with whatever input the catalogue has for it

def _number_form():
    submit = {"type": "Button", "props": {"label": "Add Listing", "submit": True}}
    form = {"type": "Form", "props": {"entity": "ENTITY-002", "workflow": "FLOW-003"},
            "children": [
                {"type": "Input", "props": {"name": "title", "label": "Title"}},
                {"type": "NumberInput", "props": {"name": "latitude", "label": "Latitude"}},
                submit]}
    return {"root": form}, form


def test_a_number_input_collects_its_field():
    """Neighbourhood Kit's Add Listing collected latitude with a NumberInput,
    which the hand-typed input list did not know — so both the authoring
    check and the engine's dry run called a working form broken."""
    doc = _doc({"title": "{{title}}", "latitude": "{{latitude}}"})
    layout, form = _number_form()
    assert "latitude" not in " ".join(
        unsatisfied_inputs(doc, doc["pages"][0], layout, form, "FLOW-003"))


def test_the_dry_run_payload_carries_it_too():
    """The manifest `assemble` dry-runs is built from the same reading."""
    from services.blueprint.dispatch_contract import control_dispatches
    doc = _doc({"title": "{{title}}", "latitude": "{{latitude}}"})
    layout, _ = _number_form()
    doc["pageLayouts"] = [{"page": "PAGE-001", **layout}]
    [wire] = [d for d in control_dispatches(doc) if d.control == "Form"]
    assert {"title", "latitude"} <= wire.keys


def test_inputs_are_read_off_the_catalogue_not_a_list():
    from services.blueprint.functional_completeness import _field_input_types
    types = _field_input_types()
    for real_input in ("NumberInput", "MoneyInput", "RadioGroup", "Switch",
                       "TimePicker", "DateRangePicker"):
        assert real_input in types, f"{real_input} collects a field"
    for not_an_input in ("Avatar", "PersonCard", "Button"):
        assert not_an_input not in types, f"{not_an_input} has a name but collects nothing"

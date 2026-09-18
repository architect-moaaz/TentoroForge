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

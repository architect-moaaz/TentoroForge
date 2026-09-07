"""A drawn entry point opens a form for what its workflow needs.

Four pages of one file drew "+ New Case", "+ New Ticket" and "+ Raise a new
request" as buttons; the New Case screen was never drawn, so the classifier
bound each to the case workflow and the contract refused all four: a lone
button collects no `caseType`. The button now opens a dialog holding a form
for the workflow's required inputs, and the page passes the same contract.
"""
import copy

from services.blueprint.functional_completeness import page_findings
from services.figma.entry_points import open_forms

DOC = {
    "pages": [{"id": "PAGE-001", "route": "/dashboard", "name": "Dashboard"}],
    "data": {"entities": [
        {"id": "ENTITY-007", "name": "Case", "table": "cases", "labelField": "reference",
         "fields": [{"name": "caseType", "type": "enum", "enumValues": ["Refund", "Complaint", "Ticket"]},
                    {"name": "title", "type": "string"},
                    {"name": "propertyId", "type": "uuid"}]},
        {"id": "ENTITY-004", "name": "Property", "table": "properties", "labelField": "name",
         "fields": [{"name": "name", "type": "string"}]},
    ]},
    "workflows": [{
        "id": "FLOW-011", "name": "Raise and Triage Case",
        "inputs": [
            {"kind": "field", "name": "caseType", "required": True, "type": "enum"},
            {"kind": "field", "name": "title", "required": True, "type": "string"},
            {"kind": "field", "name": "description", "required": True, "type": "text"},
            {"kind": "field", "name": "propertyId", "required": True, "type": "uuid"},
            {"kind": "field", "name": "isAfterHours", "required": True, "type": "boolean"},
            {"kind": "field", "name": "guestId", "required": False, "type": "uuid"},
        ],
        "steps": [{"type": "trigger"}, {"type": "action", "entity": "ENTITY-007"}],
    }, {
        "id": "FLOW-012", "name": "Validate Approve and Post Refund",
        "inputs": [{"kind": "record", "name": "caseRecord", "entity": "ENTITY-007", "required": True}],
        "steps": [{"type": "action", "entity": "ENTITY-007"}],
    }],
    "businessRules": [],
}


def _page(*controls: dict) -> dict:
    return {"type": "Stack", "props": {}, "children": [
        {"type": "Row", "props": {}, "children": [
            {"type": "Heading", "props": {"content": "Operations Dashboard"}},
            *controls,
        ]},
    ]}


def _findings(root, sources):
    return page_findings({
        "pages": DOC["pages"], "workflows": DOC["workflows"], "data": DOC["data"],
        "businessRules": [],
        "pageLayouts": [{"page": "PAGE-001", "root": root, "dataSources": sources}],
    })


def test_the_button_opens_a_dialog_form_for_the_workflows_required_fields():
    root = _page({"type": "Button", "props": {"label": "+ New Case", "workflow": "FLOW-011"}})
    assert _findings(copy.deepcopy(root), []), "the lone button is refused before the rewrite"

    root, added, opened = open_forms(DOC, DOC["pages"][0], root, [])

    assert opened == 1
    button = root["children"][0]["children"][1]
    assert button["props"] == {"label": "+ New Case", "opensDialog": "new-case"}
    dialog = root["children"][-1]
    assert dialog["type"] == "Dialog" and dialog["props"]["id"] == "new-case"
    assert dialog["props"]["title"] == "New Case"
    form = dialog["children"][0]
    assert form["type"] == "Form"
    assert form["props"]["workflow"] == "FLOW-011"
    assert form["props"]["submitLabel"] == "New Case"
    fields = {f["name"]: f for f in form["props"]["fields"]}
    assert list(fields) == ["caseType", "title", "description", "propertyId", "isAfterHours"], \
        "the required inputs, in the workflow's order, and not the optional guest"
    assert fields["caseType"]["kind"] == "select"
    assert [o["value"] for o in fields["caseType"]["options"]] == ["Refund", "Complaint", "Ticket"]
    assert fields["description"]["kind"] == "textarea"
    assert fields["isAfterHours"]["kind"] == "checkbox"
    assert fields["propertyId"]["kind"] == "select"
    assert fields["propertyId"]["interaction"]["optionsFrom"] == {
        "source": "properties", "value": "id", "label": "name"}
    assert fields["propertyId"]["label"] == "Property"
    assert added == [{"name": "properties", "op": "list", "entity": "Property", "limit": 50}]
    assert _findings(root, added) == [], "the page now passes the contract that refused it"


def test_a_control_needing_a_record_is_not_an_entry_point():
    root = _page({"type": "Button", "props": {"label": "Refund", "workflow": "FLOW-012"}})

    root, added, opened = open_forms(DOC, DOC["pages"][0], root, [])

    assert opened == 0 and added == []
    assert root["children"][0]["children"][1]["props"]["workflow"] == "FLOW-012"


def test_a_workflow_needing_both_fields_and_a_record_is_left_alone():
    """"Approve" runs a decision that takes a note field AND the escalation it
    decides on. The field must not lure the button into a form the record can
    never reach."""
    doc = {**DOC, "workflows": DOC["workflows"] + [{
        "id": "FLOW-007", "name": "Review Escalated Decision",
        "inputs": [
            {"kind": "record", "name": "escalation", "entity": "ENTITY-007", "required": True},
            {"kind": "field", "name": "note", "required": True, "type": "text"},
        ],
        "steps": [{"type": "action", "entity": "ENTITY-007"}],
    }]}
    root = _page({"type": "Button", "props": {"label": "Approve", "workflow": "FLOW-007"}})

    root, added, opened = open_forms(doc, doc["pages"][0], root, [])

    assert opened == 0 and added == []
    assert root["children"][0]["children"][1]["props"]["workflow"] == "FLOW-007"


def test_a_button_already_inside_a_form_that_collects_the_fields_is_kept():
    form = {"type": "Form", "props": {"workflow": "FLOW-011", "fields": [
        {"kind": "select", "name": "caseType", "label": "Case type", "options": []},
        {"kind": "text", "name": "title", "label": "Title"},
        {"kind": "textarea", "name": "description", "label": "Description"},
        {"kind": "select", "name": "propertyId", "label": "Property", "options": []},
        {"kind": "checkbox", "name": "isAfterHours", "label": "After hours"},
    ]}, "children": [{"type": "Button", "props": {"label": "Raise", "workflow": "FLOW-011"}}]}
    root = _page(form)

    root, added, opened = open_forms(DOC, DOC["pages"][0], root, [])

    assert opened == 0
    assert root["children"][0]["children"][1]["children"][0]["props"]["workflow"] == "FLOW-011"


def test_two_entry_points_on_one_page_get_their_own_dialogs():
    root = _page({"type": "Button", "props": {"label": "+ New Case", "workflow": "FLOW-011"}},
                 {"type": "Button", "props": {"label": "+ New Case", "workflow": "FLOW-011"}})

    root, added, opened = open_forms(DOC, DOC["pages"][0], root, [])

    assert opened == 2
    ids = [d["props"]["id"] for d in root["children"][-2:]]
    assert ids == ["new-case", "new-case-2"]
    assert len(added) == 1, "one picker source serves both forms"

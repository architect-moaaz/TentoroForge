"""A screen is a job, not a table (Mozato, forge-v3, 2026-10-06: 106 routes for
work a React screen does in about thirty). A page holds its records as
`sections` — a list, the panel a chosen record opens in, tabs, dialogs — and
names what a person does there. Everything downstream reads them: the
workflow agent is asked for each section's actions, the page writer is briefed
on the whole screen, the fallback layout shows each section's records, and the
completeness check counts a section that adds."""
import copy
import json

from services.blueprint.executors import build_prompt
from services.blueprint.functional_completeness import _somewhere_to_go
from services.blueprint.template_page import template_layout
from services.blueprint.ui_engineer import _page_brief
from services.blueprint.workflow_slots import section_slots, workflow_slot_prompt

from tests.services.test_template_page import _accepted, _doc

SECTIONS = [
    {"key": "records", "label": "Records", "entity": "ENTITY-001", "shows": "list", "placement": "main",
     "addsHere": True, "actions": ["Approve record"]},
    {"key": "record", "label": "Record", "entity": "ENTITY-001", "shows": "record", "placement": "panel",
     "opensFrom": "records", "param": "record", "actions": ["Archive record"]},
    {"key": "notes", "label": "Notes", "entity": "ENTITY-002", "shows": "list", "placement": "tab"},
]


def _screen_doc():
    doc = copy.deepcopy(_doc())
    doc["data"]["entities"].append({"id": "ENTITY-002", "name": "Note", "table": "notes",
                                    "fields": [{"name": "id", "type": "uuid"},
                                               {"name": "body", "type": "string"}]})
    doc["pages"] = [p for p in doc["pages"] if p["id"] in ("PAGE-001", "PAGE-004")]
    doc["pages"][0]["sections"] = copy.deepcopy(SECTIONS)
    return doc


def test_the_screens_actions_are_asked_of_the_workflow_agent():
    doc = _screen_doc()
    asked = {(s["section"], s["action"]) for s in section_slots(doc)}
    # "Add Record" is served: FLOW-001 is called "Create Record"? No — it is
    # named for the action, so the slot stays until a workflow says "Add Record".
    assert ("records", "Approve record") in asked and ("record", "Archive record") in asked
    assert ("records", "Add Record") in asked
    doc["workflows"].append({"id": "FLOW-009", "name": "Approve Record", "trigger": {"kind": "manual"},
                             "launchedFrom": ["PAGE-001"], "steps": []})
    assert ("records", "Approve record") not in {(s["section"], s["action"]) for s in section_slots(doc)}
    said = workflow_slot_prompt(doc)
    assert "THE SCREENS' ACTIONS" in said and "Archive record" in said
    _, user = build_prompt(doc, "workflows")
    assert "Archive record" in user, "asked even when no page is a create page"


def test_the_page_writer_is_briefed_on_the_whole_screen():
    doc = _screen_doc()
    screen = _page_brief(doc, doc["pages"][0])["screen"]
    assert "?<param>=<id>" in screen["write"]
    by_key = {s["key"]: s for s in screen["sections"]}
    assert by_key["record"]["placement"] == "panel" and by_key["record"]["param"] == "record"
    assert by_key["notes"]["entity"] == "Note", "records by name, not id"


def test_the_fallback_lays_a_screen_out_with_each_sections_records():
    doc = _screen_doc()
    body = _accepted(doc, "PAGE-001")          # the contract's own layout checks accept it
    kinds = [n.get("type") for n in body["root"]["children"]]
    assert "Dialog" in kinds, "the main records are added in a dialog on the screen"
    edit = next(a for n in body["root"]["children"] if n.get("type") == "Table"
                for a in n["props"].get("rowActions") or [] if a["label"] == "Edit")
    assert edit["navigate"] == "/master-data?record={{id}}", "Edit opens the record's panel"
    sources = {s["name"]: s for s in body["dataSources"]}
    assert "note" in sources and sources["note"]["entity"] == "Note"
    titles = [n.get("props", {}).get("title") for n in body["root"]["children"] if n.get("type") == "Card"]
    assert "Notes" in titles


def test_a_section_that_adds_is_where_create_goes():
    doc = _screen_doc()
    page = copy.deepcopy(doc["pages"][0])
    page.pop("addsHere", None)
    assert _somewhere_to_go(doc, page, "ENTITY-001", {}, ("form",))
    page["sections"][0]["addsHere"] = False
    assert not _somewhere_to_go(doc, page, "ENTITY-001", {}, ("form",))


def test_a_screen_is_a_page_the_contract_accepts():
    import jsonschema, pathlib
    schema = json.loads((pathlib.Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json").read_text())
    page_schema = schema["properties"]["pages"]["items"]
    resolver = jsonschema.RefResolver.from_schema(schema)
    page = {"id": "PAGE-001", "name": "Support desk", "route": "/ops/support", "pattern": "master_detail",
            "purpose": "Work the ticket queue.",
            "sections": SECTIONS}
    jsonschema.validate(page, page_schema, resolver=resolver)
    bad = copy.deepcopy(page)
    bad["sections"][0]["placement"] = "sidebar"
    try:
        jsonschema.validate(bad, page_schema, resolver=resolver)
    except jsonschema.ValidationError:
        pass
    else:
        raise AssertionError("a placement outside the vocabulary is accepted")

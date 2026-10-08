"""Mozato (forge-v3, 2026-10-06) planned 106 pages, 21 of them an "Add a …"
form beside a list of the same record. A list now says it adds its records
(`addsHere`), and everything downstream treats it as the place a record is
created: the workflow agent is asked for its create workflow, the layout floor
draws the form as a dialog on the list, the completeness check counts it as
somewhere `create` can go, and the page-code writer is told to carry the form."""
import copy

from services.blueprint.functional_completeness import _somewhere_to_go
from services.blueprint.template_page import template_layout
from services.blueprint.ui_engineer import _page_brief
from services.blueprint.workflow_slots import workflow_slot_prompt, workflow_slots

from tests.services.test_template_page import _accepted, _doc


def _adds_here():
    """The template fixture with the separate create page gone and the list
    adding its records."""
    doc = copy.deepcopy(_doc())
    doc["pages"] = [p for p in doc["pages"] if p["id"] != "PAGE-002"]
    doc["pages"][0]["addsHere"] = True
    return doc


def _walk(n):
    yield n
    for c in n.get("children") or []:
        yield from _walk(c)


def test_the_list_carries_the_create_form_as_a_dialog():
    doc = _adds_here()
    body = _accepted(doc, "PAGE-001")              # the contract's own checks accept it
    nodes = list(_walk(body["root"]))
    add = next(n for n in nodes if n["type"] == "Button" and n["props"].get("label") == "Add Record")
    dialog = next(n for n in nodes if n["type"] == "Dialog")
    assert add["props"]["opensDialog"] == dialog["props"]["id"] and "navigate" not in add["props"]
    form = next(n for n in _walk(dialog) if n["type"] == "Form")
    assert form["props"]["workflow"] == "FLOW-001"
    assert form["props"]["onSuccess"]["navigate"] == "/master-data", "stays on the list it added to"


def test_a_list_with_a_create_page_still_links_to_it():
    body = template_layout(_doc(), _doc()["pages"][0])
    add = next(n for n in _walk(body["root"]) if n["type"] == "Button" and n["props"].get("label") == "Add Record")
    assert add["props"]["navigate"] == "/add-data"
    assert not any(n["type"] == "Dialog" for n in _walk(body["root"]))


def test_the_workflow_agent_is_asked_for_the_lists_create_workflow():
    doc = _adds_here()
    doc["workflows"] = []
    slot = next(s for s in workflow_slots(doc) if s["page"] == "PAGE-001")
    assert slot["addsHere"] is True and slot["entity"] == "ENTITY-001"
    assert "addsHere" in workflow_slot_prompt(doc)


def test_create_has_somewhere_to_go_on_a_list_that_adds():
    doc = _adds_here()
    page = doc["pages"][0]
    assert _somewhere_to_go(doc, page, "ENTITY-001", {}, ("form",))
    without = copy.deepcopy(doc)
    without["pages"][0].pop("addsHere")
    assert not _somewhere_to_go(without, without["pages"][0], "ENTITY-001", {}, ("form",))


def test_the_page_writer_is_told_the_form_lives_here():
    doc = _adds_here()
    brief = _page_brief(doc, doc["pages"][0])
    assert "added on this page" in brief["addsHere"] and "Record" in brief["addsHere"]
    assert "addsHere" not in _page_brief(_doc(), _doc()["pages"][2])

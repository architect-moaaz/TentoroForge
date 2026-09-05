"""A button fails when its workflow needs something the page never gave it.

The engine finds a workflow's record in its input; a button on a case page
sent `{}` and the first step could not find the case. Nothing could have
caught it: a Workflow declared a trigger, prose and steps, and never what it
needs to start. Now it declares `inputs`, and a control that runs it must
supply every required one from what its page has in scope — the record a
detail page shows, the fields a form collects — or the composer refuses it
and says what is missing and where it could come from.
"""
import json
from pathlib import Path

from services.blueprint.functional_completeness import functional_findings, unsatisfied_inputs
from services.blueprint.page_planner import page_brief
from services.blueprint.record_scope import carry_record

ENTITIES = [{"id": "ENTITY-002", "name": "Case", "fields": [{"name": "id"}, {"name": "title"}]}]
WORKFLOWS = [
    {"id": "FLOW-008", "name": "Submit Refund Case For Approval", "trigger": {"kind": "manual", "detail": "Case owner submits"},
     "steps": [], "inputs": [{"name": "case", "kind": "record", "entity": "ENTITY-002", "required": True}]},
    {"id": "FLOW-010", "name": "Add Case Note", "trigger": {"kind": "manual", "detail": "Anyone adds a note"},
     "steps": [], "inputs": [{"name": "case", "kind": "record", "entity": "ENTITY-002"},
                              {"name": "note", "kind": "field", "type": "text"}]},
    {"id": "FLOW-013", "name": "Overdue Case Sweep", "trigger": {"kind": "schedule"}, "steps": []},
]


def _doc(route, root, sources=()):
    page = {"id": "PAGE-1", "route": route, "name": "p", "requirements": [], "users": [],
            "data": {"primaryEntity": "ENTITY-002"}}
    return {"data": {"entities": ENTITIES}, "workflows": WORKFLOWS, "requirements": [], "roles": [], "widgets": [],
            "pages": [page], "pageLayouts": [{"page": "PAGE-1", "root": root, "dataSources": list(sources)}]}


def _btn(wf, **props):
    return {"type": "Button", "props": {"label": "Go", "workflow": wf, **props}, "children": []}


def _rules(doc):
    return [(f["rule"], f["detail"]) for f in functional_findings(doc)]


# ------------------------------------------------------------ the contract

def test_the_contract_declares_inputs():
    schema = json.loads(Path("contracts/blueprint.schema.json").read_text())
    text = json.dumps(schema)
    assert '"inputs"' in text and '"record"' in text and '"field"' in text


def test_the_page_author_sees_what_each_workflow_needs():
    doc = _doc("/cases", {"type": "Stack", "props": {}, "children": []})
    brief = page_brief(doc, "PAGE-1")
    submit = next(w for w in brief["workflows"] if w["id"] == "FLOW-008")
    assert submit["inputs"] == [{"name": "case", "kind": "record", "entity": "ENTITY-002", "required": True}]


# ---------------------------------------------------------------- the rule

def test_a_record_workflow_on_a_list_page_is_refused_with_where_to_put_it():
    doc = _doc("/cases", {"type": "Stack", "props": {}, "children": [_btn("FLOW-008")]})
    rules = _rules(doc)
    assert any(r == "workflow-inputs-unsatisfied" and "needs a Case record" in d and "detail page" in d for r, d in rules), rules


def test_the_same_control_on_the_detail_page_is_fine():
    doc = _doc("/cases/[id]", {"type": "Stack", "props": {}, "children": [_btn("FLOW-008")]})
    assert not [r for r, _ in _rules(doc) if r == "workflow-inputs-unsatisfied"]


def test_an_explicit_argument_satisfies_a_record_input():
    doc = _doc("/cases", {"type": "Stack", "props": {}, "children": [_btn("FLOW-008", args={"case": "{{selected.id}}"})]})
    assert not [r for r, _ in _rules(doc) if r == "workflow-inputs-unsatisfied"]


def test_a_field_input_needs_a_form_around_the_control():
    doc = _doc("/cases/[id]", {"type": "Stack", "props": {}, "children": [_btn("FLOW-010")]})
    rules = _rules(doc)
    assert any("needs the field 'note'" in d and "in no Form" in d for _r, d in rules), rules


def test_a_form_that_collects_the_field_satisfies_it():
    form = {"type": "Form", "props": {}, "children": [
        {"type": "Input", "props": {"name": "note"}, "children": []}, _btn("FLOW-010")]}
    doc = _doc("/cases/[id]", {"type": "Stack", "props": {}, "children": [form]})
    assert not [r for r, _ in _rules(doc) if r == "workflow-inputs-unsatisfied"]


def test_a_form_missing_the_field_says_which_input_to_add():
    form = {"type": "Form", "props": {}, "children": [
        {"type": "Input", "props": {"name": "other"}, "children": []}, _btn("FLOW-010")]}
    doc = _doc("/cases/[id]", {"type": "Stack", "props": {}, "children": [form]})
    assert any("add an Input named 'note'" in d for _r, d in _rules(doc))


def test_a_workflow_that_declares_nothing_is_not_judged():
    doc = _doc("/cases", {"type": "Stack", "props": {}, "children": [_btn("FLOW-013")]})
    assert not [r for r, _ in _rules(doc) if r == "workflow-inputs-unsatisfied"]


# ---------------------------------------------- the record is carried

def test_a_control_on_the_detail_page_carries_the_record():
    layout = {"root": {"type": "Stack", "props": {}, "children": [_btn("FLOW-008")]},
              "dataSources": [{"name": "cases", "op": "get", "entity": "Case"}]}
    doc = _doc("/cases/[id]", layout["root"], layout["dataSources"])
    assert carry_record(doc, doc["pages"][0], layout) == 1
    assert layout["root"]["children"][0]["props"]["args"] == {"case": "{{cases.id}}", "id": "{{cases.id}}"}


def test_an_authored_argument_is_kept():
    layout = {"root": {"type": "Stack", "props": {}, "children": [_btn("FLOW-008", args={"case": "{{other.id}}"})]},
              "dataSources": [{"name": "cases", "op": "get", "entity": "Case"}]}
    doc = _doc("/cases/[id]", layout["root"], layout["dataSources"])
    carry_record(doc, doc["pages"][0], layout)
    assert layout["root"]["children"][0]["props"]["args"]["case"] == "{{other.id}}"


def test_nothing_is_carried_on_a_list_page_or_without_a_record_source():
    layout = {"root": {"type": "Stack", "props": {}, "children": [_btn("FLOW-008")]}, "dataSources": []}
    doc = _doc("/cases/[id]", layout["root"])
    assert carry_record(doc, doc["pages"][0], layout) == 0
    doc = _doc("/cases", layout["root"], [{"name": "cases", "op": "get", "entity": "Case"}])
    assert carry_record(doc, doc["pages"][0], {"root": layout["root"], "dataSources": doc["pageLayouts"][0]["dataSources"]}) == 0


def test_projection_carries_the_record_where_the_form_is_bound():
    import inspect
    from services.blueprint import page_planner
    src = inspect.getsource(page_planner.plan_page)
    assert "carry_record(doc, page" in src

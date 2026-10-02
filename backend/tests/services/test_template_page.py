"""Every page's layout, laid out from its own contract with no model call:
the three families, the workspace for everything else, and the node that
writes them."""

import json

import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidPatternTemplate, check_pattern_templates,
)
from services.blueprint.orchestrator import DAG, run
from services.blueprint.observer import Observer
from services.blueprint.run_ledger import read, runs
from services.blueprint.service import BlueprintService
from services.blueprint.template_page import family_of, template_layout


def _doc():
    return {
        "application": {"id": "t", "name": "Master Data", "domain": "data"},
        "data": {"entities": [{"id": "ENTITY-001", "name": "Record", "table": "records", "labelField": "fullName",
                               "fields": [{"name": "id", "type": "uuid"},
                                          {"name": "fullName", "type": "string", "required": True},
                                          {"name": "gender", "type": "string", "enumValues": ["Male", "Female"]},
                                          {"name": "age", "type": "integer"},
                                          {"name": "createdAt", "type": "timestamp"}]}]},
        "pages": [
            {"id": "PAGE-001", "name": "Master Data", "route": "/master-data", "pattern": "entity_list",
             "purpose": "Manage records.", "actions": ["view", "edit", "delete", "create"],
             "data": {"primaryEntity": "ENTITY-001"}, "requirements": ["REQ-001"]},
            {"id": "PAGE-002", "name": "Add Record", "route": "/add-data", "pattern": "form", "purpose": "Add a record.",
             "actions": ["create"], "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-003", "name": "Record", "route": "/master-data/[id]", "pattern": "record_workspace", "purpose": "One record.",
             "actions": ["view", "edit", "delete"], "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-004", "name": "Overview", "route": "/overview", "pattern": "dashboard", "purpose": "Numbers.", "actions": []},
        ],
        "workflows": [
            {"id": "FLOW-001", "name": "Create Record", "trigger": {"kind": "manual"},
             "inputs": [{"name": "fullName", "kind": "field", "required": True},
                        {"name": "gender", "kind": "field", "required": True},
                        {"name": "age", "kind": "field", "required": True}],
             "steps": [{"key": "i", "name": "i", "type": "action", "entity": "ENTITY-001",
                        "config": {"actionType": "db_insert", "table": "records",
                                   "values": {"fullName": "{{fullName}}", "gender": "{{gender}}", "age": "{{age}}"}},
                        "next": []}]},
            {"id": "FLOW-002", "name": "Update Record", "trigger": {"kind": "manual"},
             "inputs": [{"name": "record", "kind": "record", "entity": "ENTITY-001", "required": True},
                        {"name": "fullName", "kind": "field", "required": True}],
             "steps": [{"key": "u", "name": "u", "type": "action", "entity": "ENTITY-001",
                        "config": {"actionType": "db_update", "table": "records",
                                   "values": {"fullName": "{{fullName}}"}, "where": {"id": "{{record.id}}"}},
                        "next": []}]},
            {"id": "FLOW-003", "name": "Delete Record", "trigger": {"kind": "manual"},
             "inputs": [{"name": "record", "kind": "record", "entity": "ENTITY-001", "required": True}],
             "steps": [{"key": "d", "name": "d", "type": "action", "entity": "ENTITY-001",
                        "config": {"actionType": "db_delete", "table": "records",
                                   "where": {"id": "{{record.id}}"}}, "next": []}]},
        ],
        "requirements": [{"id": "REQ-001", "description": "Manage records."}],
        "pageLayouts": [],
    }


def _accepted(doc, page_id):
    page = next(p for p in doc["pages"] if p["id"] == page_id)
    body = template_layout(doc, page)
    assert body is not None, page_id
    res = AgentResult(task_id="t", agent="page_template", confidence=1.0,
                      proposals=[ArtifactProposal(section="pageLayouts", natural_key=page_id, body=body)])
    check_pattern_templates(res, doc)          # raises when the contract refuses
    return body


def _controls(root):
    out = []
    def walk(n):
        if isinstance(n, dict):
            p = n.get("props") or {}
            if n.get("type") in ("Button", "Form"):
                out.append((n["type"], p.get("label") or p.get("submitLabel"), p.get("workflow") or p.get("navigate")))
            for a in p.get("rowActions") or []:
                out.append(("rowAction", a.get("label"), a.get("workflow") or a.get("navigate")))
            for c in n.get("children") or []:
                walk(c)
    walk(root)
    return out


def test_every_family_composes_a_page_the_contract_accepts():
    doc = _doc()
    lst = _accepted(doc, "PAGE-001")
    frm = _accepted(doc, "PAGE-002")
    rec = _accepted(doc, "PAGE-003")
    assert (family_of(doc["pages"][0]), family_of(doc["pages"][1]), family_of(doc["pages"][2])) == \
        ("collection", "form", "record")
    assert all(b["composedBy"] == "deterministic" for b in (lst, frm, rec))
    # the list binds its entity and carries every declared control, each bound
    assert lst["dataSources"] == [{"name": "record", "entity": "Record", "op": "list"}]
    assert _controls(lst["root"]) == [
        ("Button", "Add Record", "/add-data"),
        ("rowAction", "View", "/master-data/{{id}}"),
        ("rowAction", "Edit", "/add-data?id={{id}}"),
        ("rowAction", "Delete", "FLOW-003")]
    # the form collects the writable fields and runs the create workflow
    form = next(n for n in _walk(frm["root"]) if n["type"] == "Form")
    assert form["props"]["workflow"] == "FLOW-001"
    assert [f["name"] for f in form["props"]["fields"]] == ["fullName", "gender", "age"]
    assert form["props"]["fields"][1]["kind"] == "select" and form["props"]["fields"][2]["kind"] == "number"
    # the record page reads its record and acts on it
    assert rec["dataSources"] == [{"name": "record", "entity": "Record", "op": "get"}]
    assert ("Button", "Delete Record", "FLOW-003") in _controls(rec["root"])


def _walk(n):
    if isinstance(n, dict):
        yield n
        for c in n.get("children") or []:
            yield from _walk(c)


def test_a_control_appears_only_when_the_blueprint_can_bind_it():
    doc = _doc()
    doc["workflows"] = [w for w in doc["workflows"] if w["id"] != "FLOW-003"]    # no delete
    doc["pages"] = [p for p in doc["pages"] if p["id"] != "PAGE-003"]             # no record page
    lst = _accepted(doc, "PAGE-001")
    assert _controls(lst["root"]) == [("Button", "Add Record", "/add-data"),
                                      ("rowAction", "Edit", "/add-data?id={{id}}")]
    doc["workflows"] = []                                                          # nothing to run at all
    frm = _accepted(doc, "PAGE-002")                                               # still a page, with no Form
    assert not [n for n in _walk(frm["root"]) if n["type"] == "Form"]


def test_a_page_outside_the_families_is_laid_out_as_a_workspace():
    doc = _doc()
    doc["pages"][3]["data"] = {"primaryEntity": "ENTITY-001"}
    doc["pages"][3]["navigatesTo"] = ["PAGE-001", "PAGE-003"]
    doc["workflows"].append({"id": "FLOW-004", "name": "Recount Totals", "trigger": {"kind": "manual"},
                             "launchedFrom": ["PAGE-004"], "inputs": [], "steps": []})
    # "Archive" reads as a delete and this one deletes nothing: the contract
    # would refuse the button, so it is left out rather than cost the page
    doc["workflows"].append({"id": "FLOW-005", "name": "Archive Stale", "trigger": {"kind": "manual"},
                             "launchedFrom": ["PAGE-004"], "inputs": [], "steps": []})
    assert family_of(doc["pages"][3]) is None
    ws = _accepted(doc, "PAGE-004")
    assert ws["composedBy"] == "deterministic"
    # an overview counts what it reads, runs what launches from it, lists its
    # entity, and leads to the pages it names — but not to an [id] route
    assert {"name": "record_count", "entity": "Record", "op": "aggregate",
            "metrics": {"value": {"fn": "count"}}} in ws["dataSources"]
    controls = _controls(ws["root"])
    assert ("Button", "Recount Totals", "FLOW-004") in controls
    assert not any(c[2] == "FLOW-005" for c in controls)
    assert ("Button", "Master Data", "/master-data") in controls
    assert not any(c[2] == "/master-data/[id]" for c in controls)


def test_a_page_with_no_entity_is_still_a_page():
    doc = _doc()
    ws = _accepted(doc, "PAGE-004")
    assert ws["dataSources"] == []
    assert [n["props"]["content"] for n in _walk(ws["root"]) if n["type"] == "Heading"] == ["Overview"]
    assert template_layout(doc, {"id": "X", "route": "/x", "pattern": "entity_list"})["page"] == "X"


def test_a_workflow_the_page_cannot_supply_gets_no_control():
    """Update Record needs a record; on a page with no record in view and no
    list to pick one from, a Form for it would be refused — so none is made."""
    doc = _doc()
    doc["workflows"][1]["launchedFrom"] = ["PAGE-004"]
    doc["workflows"][1]["inputs"][0]["entity"] = "ENTITY-404"       # nothing to choose it from
    ws = _accepted(doc, "PAGE-004")
    assert not any(c[2] == "FLOW-002" for c in _controls(ws["root"]))


def test_a_record_input_is_chosen_from_a_list():
    doc = _doc()
    doc["workflows"][1]["launchedFrom"] = ["PAGE-004"]
    ws = _accepted(doc, "PAGE-004")
    form = next(n for n in _walk(ws["root"]) if n["type"] == "Form")
    pick = next(f for f in form["props"]["fields"] if f["name"] == "record")
    assert pick["interaction"]["optionsFrom"]["value"] == "id"
    assert any(s["op"] == "list" and s["entity"] == "Record" for s in ws["dataSources"])


# --- the node ----------------------------------------------------------------

def test_the_node_calls_no_model():
    assert DAG["page_layouts"].kind == "service"
    assert "composition" not in DAG
    assert "workflow_steps" in DAG["page_layouts"].depends_on   # a Form collects the inputs


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Master Data", domain="data")
    for k, v in _doc().items():
        if k != "application":
            s.doc[k] = v
    s.save()
    return s


def test_every_page_is_laid_out_without_asking_a_model(svc):
    def executor(spec):
        raise AssertionError(f"a model was asked for {spec.node}")
    report = run(svc, executor, plan=["page_layouts"])
    assert "page_layouts" in report.completed and not report.failed
    laid = {l["page"]: l for l in svc.doc["pageLayouts"]}
    assert set(laid) == {"PAGE-001", "PAGE-002", "PAGE-003", "PAGE-004"}
    assert all(l["composedBy"] == "deterministic" for l in laid.values())


def test_a_page_that_has_a_layout_keeps_it(svc):
    """Smith's edits to a screen live in its layout; re-running the node must
    not lay the page out again over them."""
    kept = {"page": "PAGE-001", "composedBy": "agent", "dataSources": [],
            "root": {"type": "Heading", "props": {"content": "Mine", "level": 1}, "children": []}}
    svc.doc["pageLayouts"] = [kept]
    svc.save()
    run(svc, lambda spec: None, plan=["page_layouts"])
    assert next(l for l in svc.doc["pageLayouts"] if l["page"] == "PAGE-001")["root"] == kept["root"]
    assert len(svc.doc["pageLayouts"]) == 4


def test_the_contract_judges_a_page_with_the_other_pages_in_view():
    """A list page composed WITHOUT its Edit row action, when a form page for
    the entity exists: refused. Handed the page alone, the contract could not
    see the form page, accepted the tree, and the observer — reading the
    whole document — flagged the very thing the contract had waved through."""
    doc = _doc()
    page = doc["pages"][0]
    body = template_layout(doc, page)
    table = next(n for n in _walk(body["root"]) if n["type"] == "Table")
    table["props"]["rowActions"] = [a for a in table["props"]["rowActions"] if a["label"] != "Edit"]
    res = AgentResult(task_id="t", agent="page_template", confidence=1.0,
                      proposals=[ArtifactProposal(section="pageLayouts", natural_key="PAGE-001", body=body)])
    with pytest.raises(InvalidPatternTemplate) as e:
        check_pattern_templates(res, doc)
    assert "declares `edit`" in str(e.value)
    assert "PAGE-002" not in str(e.value) and "/add-data" not in str(e.value).split("declares")[0]   # only this page's findings


def test_a_list_column_is_collected_as_tags():
    doc = _doc()
    doc["data"]["entities"][0]["fields"].append({"name": "specialities", "type": "string[]", "required": True})
    doc["workflows"][0]["inputs"].append({"name": "specialities", "kind": "field", "required": True})
    doc["workflows"][0]["steps"][0]["config"]["values"]["specialities"] = "{{specialities}}"
    frm = _accepted(doc, "PAGE-002")
    form = next(n for n in _walk(frm["root"]) if n["type"] == "Form")
    assert next(f for f in form["props"]["fields"] if f["name"] == "specialities")["kind"] == "tags"

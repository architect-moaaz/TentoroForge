"""The composer of last resort, and the two policies around it: four page
attempts, and the observer's verdict on a page recorded but never repaired."""

import json

import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidPatternTemplate, check_pattern_templates,
)
from services.blueprint.orchestrator import (
    ATTEMPTS_BY_NODE, DAG, FALLBACK_BY_NODE, OBSERVER_ROUNDS_BY_NODE, RunReport,
    TaskSpec, _run_agent_subject, run,
)
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
    res = AgentResult(task_id="t", agent="a2ui_pages", confidence=0.5,
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
    assert template_layout(doc, doc["pages"][1]) is None                           # a form with no workflow is not a page


def test_families_without_a_template_get_nothing():
    doc = _doc()
    assert family_of(doc["pages"][3]) is None
    assert template_layout(doc, doc["pages"][3]) is None
    assert template_layout(doc, {"id": "X", "route": "/x", "pattern": "entity_list"}) is None   # no entity


# --- the three policies ------------------------------------------------------

def test_pages_get_four_attempts_and_no_observer_repairs():
    assert ATTEMPTS_BY_NODE["page_layouts"] == 4
    assert OBSERVER_ROUNDS_BY_NODE["page_layouts"] == 0
    assert "page_layouts" in FALLBACK_BY_NODE


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Master Data", domain="data")
    for k, v in _doc().items():
        if k != "application":
            s.doc[k] = v
    s.save()
    return s


def test_a_page_refused_at_the_cap_is_composed_from_its_template(svc):
    seen = []
    def executor(spec):
        seen.append(spec.attempt)
        raise InvalidPatternTemplate("/master-data: Table 'Table' runs Create Record — a table collects no fields")
    report = RunReport()
    out = _run_agent_subject(svc, executor, "page_layouts", DAG["page_layouts"], "PAGE-001",
                             max_attempts=2, commit=False, user_request="", report=report)
    assert seen == [1, 2]                                   # every model attempt was spent first
    assert out == "completed"
    assert report.failed == [] and report.fallbacks == ["page_layouts:PAGE-001"]
    layout = next(l for l in svc.doc["pageLayouts"] if l["page"] == "PAGE-001")
    assert layout["composedBy"] == "deterministic"
    assert ("rowAction", "Delete", "FLOW-003") in _controls(layout["root"])


def test_a_page_with_no_template_still_fails_honestly(svc):
    def executor(spec):
        raise InvalidPatternTemplate("refused")
    report = RunReport()
    _run_agent_subject(svc, executor, "page_layouts", DAG["page_layouts"], "PAGE-004",
                       max_attempts=1, commit=False, user_request="", report=report)
    assert report.failed == ["page_layouts:PAGE-004"] and report.fallbacks == []


class _Critic:
    def __init__(self, reply):
        self.reply, self.calls, self.enforces_schema = reply, [], True

    def __call__(self, *, system, user, schema):
        self.calls.append(json.loads(user))
        return json.dumps(self.reply)


def test_the_observer_judges_a_page_and_records_it_but_never_re_composes_it(svc):
    calls = []
    def executor(spec):
        calls.append((spec.subject, spec.feedback))
        page = next(p for p in svc.doc["pages"] if p["id"] == spec.subject)
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal(section="pageLayouts", natural_key=spec.subject,
                                                       body=template_layout(svc.doc, page))])
    critic = _Critic({"verdict": "fail", "findings": [{
        "section": "pageLayouts", "artifact": "PAGE-001", "requirement": "REQ-001",
        "detail": "the table omits the '#' column the requirement names"}]})
    svc.doc["pages"] = [p for p in svc.doc["pages"] if p["id"] == "PAGE-001"]
    svc.save()
    report = run(svc, executor, plan=["page_layouts"], observer_agent=Observer(critic=critic, rounds=2))
    assert [c[0] for c in calls] == ["PAGE-001"]           # composed once; no repair call
    assert all(c[1] == "" for c in calls)
    events = [l["event"] for l in read(svc.output_dir, runs(svc.output_dir)[0])]
    assert "observer:verdict" in events and "observer:repair" not in events
    assert "page_layouts:PAGE-001" in report.unrepaired    # the verdict is kept as the note
    page = next(p for p in svc.doc["pages"] if p["id"] == "PAGE-001")
    assert page.get("status") == "OUT_OF_SYNC" and "#" in str(page.get("syncNote"))


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
    res = AgentResult(task_id="t", agent="a2ui_pages", confidence=0.5,
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

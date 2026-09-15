"""Verify & Fix settles the Blueprint's own Page↔Workflow gap before it
re-composes: a page that declares `delete` on an entity no workflow deletes
gets that workflow declared — mechanically, contract-checked — so the composer
has a correct target instead of wiring Delete to Update and being refused
every round (DC5 /master-data: 14 refusals, 2 rounds, nothing fixed)."""

import copy

from services.smith.review_gaps import (
    crud_gaps, crud_workflow, workflow_problems, settle_crud_gaps,
)


def _doc():
    return {
        "data": {"entities": [{
            "id": "ENTITY-001", "name": "Record",
            "fields": [{"name": "id", "type": "uuid"},
                       {"name": "fullName", "type": "string"},
                       {"name": "gender", "type": "string"},
                       {"name": "age", "type": "integer"},
                       {"name": "createdAt", "type": "timestamp"},
                       {"name": "updatedAt", "type": "timestamp"}],
        }]},
        "pages": [
            {"id": "PAGE-001", "route": "/master-data", "actions": ["view", "edit", "delete", "create"],
             "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-002", "route": "/add-data", "actions": ["create"],
             "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-003", "route": "/master-data/[id]", "actions": ["view", "edit", "delete"],
             "data": {"primaryEntity": "ENTITY-001"}},
        ],
        "workflows": [
            {"id": "FLOW-001", "name": "Create Record", "trigger": {"kind": "manual"},
             "launchedFrom": ["PAGE-002"],
             "inputs": [{"name": "fullName", "kind": "field", "required": True}],
             "steps": [{"key": "s", "name": "s", "type": "trigger", "config": {"type": "manual"}, "next": ["i"]},
                       {"key": "i", "name": "i", "type": "action", "entity": "ENTITY-001",
                        "config": {"actionType": "db_insert", "table": "records",
                                   "values": {"fullName": "{{fullName}}"}}, "next": ["e"]},
                       {"key": "e", "name": "e", "type": "end", "next": []}]},
            {"id": "FLOW-002", "name": "Update Record", "trigger": {"kind": "manual"},
             "launchedFrom": ["PAGE-002"],
             "inputs": [{"name": "record", "kind": "record", "entity": "ENTITY-001", "required": True}],
             "steps": [{"key": "s", "name": "s", "type": "trigger", "config": {"type": "manual"}, "next": ["u"]},
                       {"key": "u", "name": "u", "type": "action", "entity": "ENTITY-001",
                        "config": {"actionType": "db_update", "table": "records",
                                   "values": {"fullName": "{{fullName}}"}, "where": {"id": "{{record.id}}"}},
                        "next": ["e"]},
                       {"key": "e", "name": "e", "type": "end", "next": []}]},
        ],
        "businessRules": [],
    }


class _Svc:
    """The two BlueprintService calls the seam makes, over a plain doc."""
    def __init__(self, doc):
        self.doc = doc
        self.saved = 0

    def upsert(self, section, artifact, *, natural_key):
        assert section == "workflows"
        assert natural_key == "FLOW:delete record"      # the registry's own key shape
        n = len(self.doc["workflows"]) + 1
        wf = {"id": f"FLOW-{n:03d}", **artifact}
        self.doc["workflows"].append(wf)
        return wf

    def save(self):
        self.saved += 1


def test_the_one_gap_is_the_delete_no_workflow_performs():
    gaps = crud_gaps(_doc())
    assert [(g.entity_name, g.op) for g in gaps] == [("Record", "db_delete")]
    g = gaps[0]
    assert g.pages == ["PAGE-001", "PAGE-003"]          # both pages that declare it
    assert g.routes == ["/master-data", "/master-data/[id]"]
    assert g.verbs == ["delete"]
    assert g.workflow_name == "Delete Record"


def test_create_and_edit_are_served_and_are_not_gaps():
    doc = _doc()
    for p in doc["pages"]:
        p["actions"] = [a for a in p["actions"] if a != "delete"]
    assert crud_gaps(doc) == []


def test_non_crud_verbs_and_bound_ids_are_not_guessed():
    doc = _doc()
    doc["pages"][0]["actions"] = ["approve", "FLOW-009", "view"]
    doc["pages"][2]["actions"] = []
    assert crud_gaps(doc) == []                          # approve is the author's, not ours
    doc["pages"][0]["data"] = {}
    doc["pages"][0]["actions"] = ["delete"]
    assert crud_gaps(doc) == []                          # no entity, nothing to delete


def test_the_declared_workflow_is_the_shape_the_contract_accepts():
    doc = _doc()
    body = crud_workflow(doc, crud_gaps(doc)[0])
    assert body["name"] == "Delete Record"
    assert body["trigger"] == {"kind": "manual", "detail": body["trigger"]["detail"]}
    assert body["launchedFrom"] == ["PAGE-001", "PAGE-003"]
    assert body["inputs"] == [{"name": "record", "kind": "record", "entity": "ENTITY-001",
                               "required": True, "description": "The existing Record being deleted."}]
    kinds = [s["type"] for s in body["steps"]]
    assert kinds == ["trigger", "action", "end"]
    do = body["steps"][1]
    assert do["entity"] == "ENTITY-001"
    assert do["config"] == {"actionType": "db_delete", "table": "records",   # the table its siblings write
                            "where": {"id": "{{record.id}}"}}
    assert [s["next"] for s in body["steps"]] == [["do_delete"], ["done"], []]
    assert workflow_problems(doc, body) == []            # catalog + authoring findings: clean


def test_an_update_gap_carries_the_writable_fields_not_the_managed_ones():
    doc = _doc()
    doc["workflows"] = [doc["workflows"][0]]              # no Update at all
    doc["pages"][2]["actions"] = []
    gaps = {g.op: g for g in crud_gaps(doc)}
    assert set(gaps) == {"db_update", "db_delete"}
    body = crud_workflow(doc, gaps["db_update"])
    assert [i["name"] for i in body["inputs"]] == ["record", "fullName", "gender", "age"]
    cfg = body["steps"][1]["config"]
    assert cfg["actionType"] == "db_update"
    assert set(cfg["values"]) == {"fullName", "gender", "age", "updatedAt"}
    assert cfg["where"] == {"id": "{{record.id}}"}
    assert workflow_problems(doc, body) == []


def test_settle_declares_saves_narrates_and_briefs_the_pages():
    svc = _Svc(_doc())
    said = []
    notes = settle_crud_gaps(svc, emit=lambda k, d: said.append((k, d["text"])))
    assert [w["id"] for w in svc.doc["workflows"]] == ["FLOW-001", "FLOW-002", "FLOW-003"]
    assert svc.saved == 1
    assert crud_gaps(svc.doc) == []                       # settled stays settled
    assert set(notes) == {"PAGE-001", "PAGE-003"}
    assert "Delete Record (FLOW-003)" in notes["PAGE-001"]
    assert 'workflow: "FLOW-003"' in notes["PAGE-001"]    # the composer is told what to bind
    assert said == [("message", "Declared Delete Record (FLOW-003) — /master-data, "
                                "/master-data/[id] had a delete with no workflow that "
                                "deletes a Record.")]


def test_settle_can_be_narrowed_to_the_pages_in_hand():
    svc = _Svc(_doc())
    assert settle_crud_gaps(svc, only_pages={"PAGE-002"}) == {}   # /add-data has no gap
    assert len(svc.doc["workflows"]) == 2 and svc.saved == 0
    notes = settle_crud_gaps(svc, only_pages={"PAGE-003"})
    assert set(notes) == {"PAGE-001", "PAGE-003"}        # the workflow serves every page that declares it


def test_nothing_to_settle_is_silent():
    doc = _doc()
    for p in doc["pages"]:
        p["actions"] = ["view"]
    svc = _Svc(doc)
    said = []
    assert settle_crud_gaps(svc, emit=lambda k, d: said.append(d)) == {}
    assert said == [] and svc.saved == 0

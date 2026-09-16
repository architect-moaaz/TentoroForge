"""A change request that names a capability is contract, not prose: the verb
goes into the page's `actions`, the workflow it needs is declared, and the
page is upserted under the registry's own key so nothing duplicates."""

import json
from types import SimpleNamespace

import pytest

from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import compose as sc


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Med Registration", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                   "fields": [{"name": "id", "type": "uuid"}, {"name": "fullName", "type": "string"},
                                              {"name": "location", "type": "string"}]}]}
    s.doc["workflows"] = [
        {"id": "FLOW-001", "name": "Register Nurse", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"],
         "inputs": [{"name": "fullName", "kind": "field", "required": True}],
         "steps": [{"key": "i", "name": "i", "type": "action", "entity": "ENTITY-001",
                    "config": {"actionType": "db_insert", "table": "nurses", "values": {"fullName": "{{fullName}}"}}, "next": []}]},
        {"id": "FLOW-002", "name": "Edit Nurse Registration", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"],
         "inputs": [{"name": "record", "kind": "record", "entity": "ENTITY-001", "required": True},
                    {"name": "fullName", "kind": "field", "required": True}],
         "steps": [{"key": "u", "name": "u", "type": "action", "entity": "ENTITY-001",
                    "config": {"actionType": "db_update", "table": "nurses", "values": {"fullName": "{{fullName}}"},
                               "where": {"id": "{{record.id}}"}}, "next": []}]},
    ]
    s.upsert("pages", {"name": "Nurse Registration", "route": "/nurse-registration", "pattern": "form",
                       "purpose": "Register.", "actions": ["submit"], "data": {"primaryEntity": "ENTITY-001"}},
             natural_key=page_key("/nurse-registration"))
    s.upsert("pages", {"name": "Master Data", "route": "/master-data", "pattern": "entity_list",
                       "purpose": "All nurses.", "actions": ["view_record", "edit_record"],
                       "data": {"primaryEntity": "ENTITY-001"}, "primaryTasks": ["Search nurses"]},
             natural_key=page_key("/master-data"))
    s.save()
    return s


def _stub_compose(monkeypatch):
    calls = []
    def fake(svc, route, **kw):
        calls.append(route)
        return SimpleNamespace(applied=True, committed=["pageLayouts:PAGE-002"], version=3, reason="")
    monkeypatch.setattr(sc, "compose_route", fake)
    return calls


def test_the_request_names_a_delete_and_the_contract_learns_it(svc, monkeypatch):
    calls = _stub_compose(monkeypatch)
    sc.add_widgets(svc, "/master-data",
                   ["Delete Record action button on each row, with a confirmation prompt before deletion"],
                   request="Can you add delete record functionality")
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    pages = [p for p in doc["pages"] if p["route"] == "/master-data"]
    assert len(pages) == 1, "the page must be updated, not duplicated"
    (page,) = pages
    assert page["actions"] == ["view_record", "edit_record", "delete"]
    assert "Delete Record action button on each row, with a confirmation prompt before deletion" in page["primaryTasks"]
    deletes = [w for w in doc["workflows"] if any((s.get("config") or {}).get("actionType") == "db_delete" for s in w["steps"])]
    assert [(w["name"], w["launchedFrom"]) for w in deletes] == [("Delete Nurse", [page["id"]])]
    assert calls == ["/master-data"]                              # then composed against it


def test_a_second_ask_adds_nothing_and_a_wish_without_a_verb_touches_no_actions(svc, monkeypatch):
    _stub_compose(monkeypatch)
    sc.add_widgets(svc, "/master-data", ["Delete Record button"], request="add delete record functionality")
    n_wf = len(BlueprintService.load(output_dir=svc.output_dir).doc["workflows"])
    sc.add_widgets(svc, "/master-data", ["Delete Record button"], request="add delete record functionality")
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    assert len(doc["workflows"]) == n_wf and [p["route"] for p in doc["pages"]].count("/master-data") == 1
    sc.add_widgets(svc, "/master-data", ["a total count tile"], request="show a total count at the top")
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    assert next(p for p in doc["pages"] if p["route"] == "/master-data")["actions"] == ["view_record", "edit_record", "delete"]


def test_a_new_route_is_allocated_under_the_registrys_key(svc, monkeypatch):
    _stub_compose(monkeypatch)
    sc.add_widgets(svc, "/clients", ["a clients table"], request="add a clients screen")
    ids = json.load(open(f"{svc.output_dir}/.forge/ids.json"))["bindings"]
    assert "PAGE:/clients" in ids and "/clients" not in ids
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    assert [p["route"] for p in doc["pages"]].count("/clients") == 1


def test_the_words_that_name_a_capability():
    assert sc.capabilities_named("triggering permanent removal of that nurse record before deletion") == ["delete"]
    assert sc.capabilities_named("change the title to Nurses") == []
    assert sc.capabilities_named("let users update a nurse and view record details") == ["edit", "view"]
    assert sc.capabilities_named("add a Register Nurse button") == ["create"]


def test_an_edit_request_gets_the_edit_screen_the_definition_never_made(svc, monkeypatch):
    """Med Registration: "implement the edit functionality" re-composed the
    list, whose Edit already pointed at /nurse-registration/{{id}} — a route
    nothing served, because only the create screen existed. The platform's
    rule is that a form page with `[id]` in its route IS the edit screen, so
    Smith creates it, makes it reachable and launchable, and composes it
    before the list."""
    calls = _stub_compose(monkeypatch)
    sc.add_widgets(svc, "/master-data", ["Edit action button on each row"],
                   request="Can you implement the edit functionality")
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    edit = next(p for p in doc["pages"] if p["route"] == "/nurse-registration/[id]")
    assert edit["pattern"] == "form" and edit["name"] == "Edit Nurse"
    assert edit["actions"] == ["save_edit", "cancel"] and edit["data"] == {"primaryEntity": "ENTITY-001"}
    lst = next(p for p in doc["pages"] if p["route"] == "/master-data")
    assert edit["id"] in lst["navigatesTo"]                              # the list reaches it
    upd = next(w for w in doc["workflows"] if w["id"] == "FLOW-002")
    assert edit["id"] in upd["launchedFrom"]                              # the composer may bind it there
    assert calls == ["/nurse-registration/[id]", "/master-data"]          # edit screen first, then the list
    # Asked again: the screen exists, nothing is created twice.
    sc.add_widgets(svc, "/master-data", ["Edit action button on each row"], request="implement edit")
    assert [p["route"] for p in BlueprintService.load(output_dir=svc.output_dir).doc["pages"]].count("/nurse-registration/[id]") == 1


def test_no_edit_screen_is_invented_without_an_update_workflow(svc, monkeypatch):
    calls = _stub_compose(monkeypatch)
    svc.doc["workflows"] = [w for w in svc.doc["workflows"] if w["id"] != "FLOW-002"]; svc.save()
    sc.add_widgets(svc, "/master-data", ["Edit button"], request="implement the edit functionality")
    assert "/nurse-registration/[id]" not in [p["route"] for p in BlueprintService.load(output_dir=svc.output_dir).doc["pages"]]
    assert calls == ["/master-data"]

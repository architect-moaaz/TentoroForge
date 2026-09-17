""""Delete that page" was a sentence with nothing behind it.

The owner's phrasebook listed it among the asks Smith recognised only in order
to refuse: *a page can be hidden from the menu or retired with its record
type, never removed on its own*. The reason was real — a screen is named by
the menu, by the landing route, by links composed onto other screens, and by
the middleware's public matcher — and it was a description of the machinery,
not an answer. Someone who asks twice and still sees the page stops believing
anything else the product says it did.

Removed means retired: the row stays, DEPRECATED, with its layout behind it,
so undo brings the screen back and its id is never given to another. And it
means gone: nothing plans it, so the schema file is swept and the route leaves
the registry; the menu no longer names it; every link to it comes off the
screens that had one, and those screens stop declaring what the link did.
"""

from __future__ import annotations

import json

import pytest

from services.blueprint.ids import IdAllocator, page_key
from services.blueprint.service import BlueprintService
from services.smith import confirm
from services.smith import page_change as pc
from services.smith.limits import cannot
from services.smith_session import SmithSession


def _layout(page_id: str, root: dict) -> dict:
    return {"page": page_id, "composedBy": "a2ui",
            "dataSources": [{"name": "rows", "entity": "Nurse", "op": "list"}], "root": root}


@pytest.fixture()
def project(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Roster", domain="health")
    s.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "Nurse", "table": "nurses", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "fullName", "type": "string"}]}]}
    lst = s.upsert("pages", {"name": "Master Data", "route": "/master-data", "pattern": "entity_list",
                             "purpose": "All nurses.", "actions": ["view", "create"],
                             "data": {"primaryEntity": "ENTITY-001"}},
                   natural_key=page_key("/master-data"))
    form = s.upsert("pages", {"name": "Nurse Registration", "route": "/nurse-registration", "pattern": "form",
                              "purpose": "Register.", "actions": ["create"],
                              "data": {"primaryEntity": "ENTITY-001"}},
                    natural_key=page_key("/nurse-registration"))
    reports = s.upsert("pages", {"name": "Reports", "route": "/reports", "pattern": "dashboard",
                                 "purpose": "Numbers.", "data": {"primaryEntity": "ENTITY-001"}},
                       natural_key=page_key("/reports"))
    # Master Data leads to the form: a Button of its own, and a row action.
    s.doc["pages"][0]["navigatesTo"] = [form["id"]]
    s.upsert("pageLayouts", _layout(lst["id"], {"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "Add Nurse", "navigate": "/nurse-registration"}, "children": []},
        {"type": "Table", "props": {"data": "{{rows}}", "rowHref": "/nurse-registration",
                                    "columns": [{"key": "fullName", "label": "Name"}],
                                    "rowActions": [{"label": "Edit", "navigate": "/nurse-registration"},
                                                   {"label": "Open", "navigate": "/reports"}]},
         "children": []}]}), natural_key=lst["id"])
    s.upsert("pageLayouts", _layout(form["id"], {"type": "Stack", "props": {}, "children": [
        {"type": "Form", "props": {"workflow": "WORKFLOW-001", "submitLabel": "Save"}, "children": []}]}),
        natural_key=form["id"])
    s.upsert("pageLayouts", _layout(reports["id"], {"type": "Stack", "props": {}, "children": []}),
             natural_key=reports["id"])
    s.upsert("workflows", {"name": "Register Nurse", "purpose": "Insert.", "trigger": {"kind": "manual"},
                           "launchedFrom": [form["id"]], "inputs": [],
                           "steps": [{"key": "start", "name": "Start", "type": "trigger",
                                      "config": {"type": "manual"}, "next": ["do"]},
                                     {"key": "do", "name": "Insert", "type": "action", "entity": "ENTITY-001",
                                      "config": {"actionType": "db_insert", "table": "nurses",
                                                 "values": {"fullName": "{{fullName}}"}}, "next": ["end"]},
                                     {"key": "end", "name": "End", "type": "end", "next": []}]},
             natural_key="Register Nurse")
    s.upsert("widgets", {"page": form["id"], "kind": "metric", "label": "Nurses so far",
                         "dataSource": {"op": "aggregate", "entity": "ENTITY-001", "aggregation": "count"}},
             natural_key="registration-nurses")
    s.doc["navigation"] = {"style": "sidebar", "initialRoute": {"default": "/nurse-registration"},
                           "tree": [{"label": "Master Data", "page": lst["id"]},
                                    {"label": "Register", "page": form["id"]},
                                    {"label": "Reports", "page": reports["id"]}]}
    s.save()
    (tmp_path / "app" / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "app" / "src" / "app" / "(dashboard)").mkdir(parents=True)
    s._t = {"lst": lst["id"], "form": form["id"], "reports": reports["id"]}
    return s


def _session(project, verb: str, **understanding) -> SmithSession:
    return SmithSession(
        project_id="p1", output_dir=str(project.output_dir), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": verb, **understanding},
        iteration_move_fn=lambda *a, **kw: None)


# --- the verb stopped being a refusal ----------------------------------------

def test_removing_a_screen_is_no_longer_one_of_the_things_smith_only_explains():
    from services.smith.capabilities import unaccounted, verbs_covered
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP

    assert not cannot("remove_page")
    assert REQUIRED_BY_VERB["remove_page"] == {"route"}
    assert "remove_page" in verbs_covered() and not unaccounted()
    assert "Cannot be done" not in VERB_HELP["remove_page"]


# --- what it takes, named before it is taken ----------------------------------

def test_everything_pointing_at_a_screen_is_named_without_touching_any_of_it(project):
    said = pc.consequences(project.doc, "/nurse-registration")
    assert said["found"] and said["name"] == "Nurse Registration"
    assert said["menu"] == ["Register"] and said["landing"] is True
    assert said["arrows"] == ["Master Data"] and said["launches"] == ["Register Nurse"]
    assert sorted(said["links"]) == ["the row link on Master Data",
                                     "“Add Nurse” on Master Data", "“Edit” on Master Data"]
    fresh = BlueprintService.load(output_dir=str(project.output_dir))
    assert [p["route"] for p in fresh.doc["pages"]] == ["/master-data", "/nurse-registration", "/reports"]
    layout = next(l for l in fresh.doc["pageLayouts"] if l["page"] == project._t["lst"])
    assert layout["root"]["children"][1]["props"]["rowHref"] == "/nurse-registration"
    assert pc.consequences(project.doc, "/nowhere")["found"] is False


# --- the removal ---------------------------------------------------------------

def test_the_screen_is_retired_in_the_record_and_gone_from_the_application(project, tmp_path):
    out = pc.run(str(tmp_path), route="/nurse-registration")
    assert out["applied"], out.get("reason")

    fresh = BlueprintService.load(output_dir=str(tmp_path))
    page = next(p for p in fresh.doc["pages"] if p["route"] == "/nurse-registration")
    assert page["status"] == "DEPRECATED" and page["id"] == project._t["form"]
    layout = next(l for l in fresh.doc["pageLayouts"] if l["page"] == project._t["form"])
    assert layout["status"] == "DEPRECATED" and layout["root"]["children"]      # kept behind it
    assert [n["label"] for n in fresh.doc["navigation"]["tree"]] == ["Master Data", "Reports"]
    assert fresh.doc["navigation"]["initialRoute"] == {}

    schemas = tmp_path / "app" / "src" / "schemas"
    assert not (schemas / "nurse-registration.json").exists()
    registry = (schemas / "registry.ts").read_text()
    assert "/nurse-registration" not in registry
    assert 'export const entryRoute = "/master-data"' in registry


def test_the_gate_and_the_front_door_are_written_again_without_it(project, tmp_path):
    """A retired page used to leave a dead route behind it in two places: the
    middleware's public matcher still named it, and `/` still forwarded to it."""
    reports = next(p for p in project.doc["pages"] if p["route"] == "/reports")
    reports["access"] = "public"
    project.save()
    app = tmp_path / "app"
    assert pc.run(str(tmp_path), route="/reports")["applied"]
    middleware = (app / "src" / "middleware.ts").read_text()
    assert "public: /reports" not in middleware

    # And the screen the application opened on.
    assert pc.run(str(tmp_path), route="/nurse-registration")["applied"]
    root = (app / "src" / "app" / "(dashboard)" / "page.tsx").read_text()
    assert 'redirect("/master-data")' in root


def test_the_id_is_spent_so_no_other_screen_can_be_given_it(project, tmp_path):
    pc.run(str(tmp_path), route="/nurse-registration")
    alloc = IdAllocator.load(output_dir=str(tmp_path))
    assert alloc.is_retired(project._t["form"])


def test_every_link_to_it_comes_off_and_the_screen_stops_promising_what_it_did(project, tmp_path):
    out = pc.run(str(tmp_path), route="/nurse-registration")
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    root = next(l for l in fresh.doc["pageLayouts"] if l["page"] == project._t["lst"])["root"]
    kinds = [c["type"] for c in root["children"]]
    assert "Button" not in kinds                                # the Add Nurse button went with it
    table = next(c for c in root["children"] if c["type"] == "Table")
    assert "rowHref" not in table["props"]
    assert [a["label"] for a in table["props"]["rowActions"]] == ["Open"]   # the /reports one stays
    # The contract retracts: nothing on Master Data creates a nurse any more.
    master = next(p for p in fresh.doc["pages"] if p["route"] == "/master-data")
    assert "create" not in master["actions"] and master["navigatesTo"] == []
    # And the workflow is no longer launched from a screen that is gone.
    assert fresh.doc["workflows"][0]["launchedFrom"] == []
    assert any("Add Nurse" in link for link in out["links"])


def test_a_widget_on_the_screen_is_retired_with_it(project, tmp_path):
    out = pc.run(str(tmp_path), route="/nurse-registration")
    assert out["widgets"] == 1
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    assert fresh.doc["widgets"][0]["status"] == "DEPRECATED"


def test_undo_brings_the_screen_back_exactly_as_it_stood(project, tmp_path):
    from services.smith.revert import run as revert_run

    pc.run(str(tmp_path), route="/nurse-registration")
    out = revert_run(str(tmp_path))
    assert out.get("applied"), out.get("reason")
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    page = next(p for p in fresh.doc["pages"] if p["route"] == "/nurse-registration")
    assert page.get("status") != "DEPRECATED"
    root = next(l for l in fresh.doc["pageLayouts"] if l["page"] == project._t["lst"])["root"]
    assert any(c["type"] == "Button" for c in root["children"])


# --- the one thing that is refused ---------------------------------------------

def test_the_last_screen_anyone_can_arrive_at_is_refused_with_the_reason(project, tmp_path):
    for route in ("/nurse-registration", "/reports"):
        assert pc.run(str(tmp_path), route=route)["applied"]
    out = pc.run(str(tmp_path), route="/master-data")
    assert not out["applied"]
    assert "only screen anyone can arrive at" in out["reason"]
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    assert next(p for p in fresh.doc["pages"] if p["route"] == "/master-data").get("status") != "DEPRECATED"


def test_the_turn_says_why_rather_than_reporting_a_removal_it_did_not_make(project):
    for route in ("/nurse-registration", "/reports"):
        pc.run(str(project.output_dir), route=route)
    result = _session(project, "remove_page", route="/master-data").run_iteration(
        user_message="delete the master data page")
    assert result.status == "needs_user"
    assert "only screen anyone can arrive at" in result.answer


def test_a_record_route_is_not_somewhere_anyone_can_arrive(project):
    project.doc["pages"].append({"id": "PAGE-099", "name": "Nurse", "route": "/master-data/[id]",
                                 "purpose": "One.", "data": {"primaryEntity": "ENTITY-001"}})
    assert "/master-data/[id]" not in pc.arrivable(project.doc)


# --- asked twice ----------------------------------------------------------------

def test_asking_again_says_it_is_already_gone_and_writes_the_app_out_to_match(project, tmp_path):
    pc.run(str(tmp_path), route="/nurse-registration")
    (tmp_path / "app" / "src" / "schemas" / "nurse-registration.json").write_text("{}")
    out = pc.run(str(tmp_path), route="/nurse-registration")
    assert out["applied"] and out["already"]
    assert "was already removed" in out["diff_summary"]
    assert not (tmp_path / "app" / "src" / "schemas" / "nurse-registration.json").exists()


def test_a_screen_nobody_has_is_named_as_such(project, tmp_path):
    out = pc.run(str(tmp_path), route="/wards")
    assert not out["applied"] and "cannot tell which screen" in out["reason"]
    assert "/master-data" in out["reason"]


# --- the turn -------------------------------------------------------------------

def test_the_turn_shows_what_goes_with_it_and_waits(project):
    result = _session(project, "remove_page", route="/nurse-registration").run_iteration(
        user_message="delete the registration page")
    assert result.status == "asked"
    assert "does not only remove what you named" in result.answer
    assert "comes off the menu (Register)" in result.answer
    assert "Add Nurse" in result.answer and "Register Nurse" in result.answer
    assert result.options == [confirm.YES_LABEL, confirm.NO_LABEL]
    fresh = BlueprintService.load(output_dir=str(project.output_dir))
    assert next(p for p in fresh.doc["pages"] if p["route"] == "/nurse-registration").get("status") != "DEPRECATED"


def test_the_yes_removes_it_and_says_so_in_the_owners_terms(project):
    session = _session(project, "remove_page", route="/nurse-registration")
    session.run_iteration(user_message="delete the registration page")
    result = session.run_iteration(user_message=confirm.YES_LABEL)
    assert result.status == "resolved", result.answer
    assert "Removed **Nurse Registration**" in result.answer
    assert "retired" in result.answer and "undo" in result.answer
    fresh = BlueprintService.load(output_dir=str(project.output_dir))
    assert next(p for p in fresh.doc["pages"] if p["route"] == "/nurse-registration")["status"] == "DEPRECATED"


def test_a_screen_nothing_points_at_goes_without_a_question(project):
    project.doc["navigation"]["tree"] = [n for n in project.doc["navigation"]["tree"]
                                         if n["page"] != project._t["reports"]]
    root = next(l for l in project.doc["pageLayouts"] if l["page"] == project._t["lst"])["root"]
    root["children"][1]["props"]["rowActions"] = [{"label": "Edit", "navigate": "/nurse-registration"}]
    project.save()
    result = _session(project, "remove_page", route="/reports").run_iteration(user_message="drop the reports screen")
    assert result.status == "resolved", result.answer
    assert "Removed **Reports**" in result.answer


# --- and the record's screens go the same way -----------------------------------

def test_retiring_a_record_takes_the_links_to_its_screens_too(project, tmp_path):
    from services.smith.entity_change import run as entity_run

    project.doc["pages"][0]["data"] = {"primaryEntity": "ENTITY-002"}      # Master Data survives
    project.doc["data"]["entities"].append({"id": "ENTITY-002", "name": "Ward", "table": "wards",
                                            "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]})
    project.save()
    out = entity_run(str(tmp_path), "remove_entity", entity="Nurse")
    assert out["applied"], out.get("reason")
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    root = next(l for l in fresh.doc["pageLayouts"] if l["page"] == project._t["lst"])["root"]
    table = next(c for c in root["children"] if c["type"] == "Table")
    assert "rowHref" not in table["props"]                     # no link to a retired screen survives
    assert not any(c["type"] == "Button" for c in root["children"])

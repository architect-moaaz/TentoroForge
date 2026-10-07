"""A screen is used inside, by the people each part of it is for (2026-10-07).

A screen holds its records as sections — a list, the panel a chosen record
opens in, tabs, dialogs — and three things followed from that and were not
there:

- the build's check opened a page at its plain address and pressed what was
  on it, so a tab, a record's panel and what a dialog showed were never seen;
- a part of a screen could not be some of its people's only, so the lead's
  refund approvals were either everyone's or a screen of their own;
- Smith read a page as a route and a name, so "add a refunds tab to support"
  read as a new page.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

from services.blueprint import app_check as ac
from services.blueprint.menu_binding import bind_menu
from services.blueprint.projection import project_shell
from services.blueprint.screen_parts import section_audience
from services.blueprint.template_page import _section_cards
from services.blueprint.ui_engineer import _page_brief, frame_prompt, part_prompt
from services.blueprint.workflow_slots import section_slots, workflow_slot_prompt
from services.smith.engine_blueprint_adapter import to_smith_fields
from services.smith_blueprint import Blueprint
from services.smith_blueprint_context import blueprint_to_context

SECTIONS = [
    {"key": "tickets", "label": "Tickets", "entity": "ENTITY-001", "shows": "list", "placement": "main",
     "addsHere": True, "actions": ["Assign ticket"]},
    {"key": "ticket", "label": "Ticket", "entity": "ENTITY-001", "shows": "record", "placement": "panel",
     "opensFrom": "tickets", "param": "ticket"},
    {"key": "macros", "label": "Macros", "entity": "ENTITY-003", "shows": "list", "placement": "tab"},
    {"key": "refunds", "label": "Refunds", "entity": "ENTITY-002", "shows": "list", "placement": "tab",
     "roles": ["ROLE-002"], "actions": ["Approve refund"], "menuEntry": "Support > Refunds"},
    {"key": "note", "label": "New note", "entity": "ENTITY-003", "shows": "form", "placement": "dialog"},
]

DOC = {
    "application": {"name": "Desk"},
    "roles": [{"id": "ROLE-001", "name": "Agent"}, {"id": "ROLE-002", "name": "Lead"}],
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Ticket", "table": "tickets",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "subject", "type": "string"}]},
        {"id": "ENTITY-002", "name": "Refund", "table": "refunds",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "amount", "type": "number"}]},
        {"id": "ENTITY-003", "name": "Macro", "table": "macros",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "body", "type": "string"}]}]},
    "pages": [{"id": "PAGE-001", "name": "Support", "route": "/support", "users": ["ROLE-001", "ROLE-002"],
               "data": {"primaryEntity": "ENTITY-001"}, "menuEntry": "Support",
               "sections": copy.deepcopy(SECTIONS)}],
    "pageCode": [{"page": "PAGE-001", "load": "", "view": "", "parts": {"tickets": "", "refunds": ""}}],
    "navigation": {"tree": [{"label": "Support", "children": [{"label": "Inbox"}, {"label": "Refunds"}]}]},
    "workflows": [],
}


def _doc():
    return copy.deepcopy(DOC)


# --- the check opens what is inside a screen -----------------------------------------

def test_each_tab_and_panel_is_opened_by_its_link_as_each_role_it_is_for():
    got = sorted((v["as"], v.get("open") or v["route"], v.get("entity")) for v in ac.visits(_doc()))
    assert got == [
        ("Agent", "/support", "Ticket"),
        ("Agent", "/support?tab=macros", "Ticket"),
        ("Agent", "/support?ticket=[ticket]", "Ticket"),
        ("Lead", "/support", "Ticket"),
        ("Lead", "/support?tab=macros", "Ticket"),
        ("Lead", "/support?tab=refunds", "Ticket"),
        ("Lead", "/support?ticket=[ticket]", "Ticket"),
    ], "the refunds tab is opened only as the Lead; a dialog is the plain visit's to press"
    plain = {v["as"]: v for v in ac.visits(_doc()) if not v.get("inside")}
    assert plain["Agent"]["hidden_tabs"] == ["Refunds"] and "hidden_tabs" not in plain["Lead"]
    assert len({ac.visit_id(v) for v in ac.visits(_doc())}) == 7, "one shot per place"


def test_what_is_wrong_inside_says_where_and_a_dialogs_contents_are_read():
    doc = _doc()
    tab = next(v for v in ac.visits(doc) if v.get("section") == "macros" and v["as"] == "Agent")
    shot = {"status": 200, "landed": "/support", "text": "Macros · undefined", "states": {}}
    found = ac.shot_findings(shot, tab, doc)
    assert found and all(f.startswith("in its Macros tab, ") for f in found) and "'undefined'" in found[0]
    plain = next(v for v in ac.visits(doc) if v["as"] == "Agent" and not v.get("inside"))
    pressed = {"status": 200, "landed": "/support", "text": "Support", "states": {},
               "controls": [{"kind": "button", "label": "New note", "outcome": "changed",
                             "opened": "New note · Macro: undefined · Save"}]}
    found = ac.shot_findings(pressed, plain, doc)
    assert any(f.startswith('button "New note" opens a dialog where') and "undefined" in f for f in found), found


def test_a_tab_that_is_some_peoples_shown_to_someone_else_is_a_finding():
    doc = _doc()
    agent = next(v for v in ac.visits(doc) if v["as"] == "Agent" and not v.get("inside"))
    lead = next(v for v in ac.visits(doc) if v["as"] == "Lead" and not v.get("inside"))
    shot = {"status": 200, "landed": "/support", "text": "Support", "states": {},
            "tabs": ["Inbox", "Macros", "Refunds"]}
    assert 'it shows the "Refunds" tab to someone signed in as Agent, who it is not for' in ac.shot_findings(shot, agent, doc)
    assert not any("Refunds" in f for f in ac.shot_findings(shot, lead, doc))


def test_inside_a_screen_only_what_is_new_is_said(monkeypatch, tmp_path):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Lead")
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, ref: (ref, [{"name": "c"}]))
    entries_seen = []

    def run_shots(app, entries, out, **k):
        entries_seen.extend(entries)
        return [{"id": e["id"], "status": 200, "landed": "/support", "states": {}, "controls": [],
                 # the header's raw id is on every place of the screen; the
                 # macros tab alone says NaN
                 "text": "Ticket a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"
                         + (" · total NaN" if "tab=macros" in e["route"] else "")}
                for e in entries]
    monkeypatch.setattr("services.blueprint.page_review.run_shots", run_shots)
    report = ac.check_pages(SimpleNamespace(base="http://x"), _doc(), ac.visits(_doc()), tmp_path)
    found = [f for who, f in report["PAGE-001"]["findings"] if who == "Agent"]
    assert sum("raw record ids" in f for f in found) == 1, found
    assert any(f.startswith("in its Macros tab, ") and "NaN" in f for f in found), found
    assert {e["group"] for e in entries_seen} == {"PAGE-001"}, "a screen's places press a control once"
    assert any(e["route"] == "/support?ticket=[ticket]" and e["entity"] == "Ticket" for e in entries_seen)


# --- a section only some roles see -----------------------------------------------------

def test_a_sections_roles_are_names_and_an_unknown_one_narrows_nothing():
    doc = _doc()
    assert section_audience(doc, {"roles": ["ROLE-002"]}) == ["Lead"]
    assert section_audience(doc, {"roles": ["ROLE-404"]}) == [], "shown rather than hidden from all"
    assert section_audience(doc, {}) == []


def test_the_page_writer_is_told_who_sees_a_section():
    doc = _doc()
    screen = _page_brief(doc, doc["pages"][0])["screen"]
    by_key = {s["key"]: s for s in screen["sections"]}
    assert by_key["refunds"]["roles"] == ["Lead"] and "roles" not in by_key["macros"]
    assert "ctx.user?.role" in screen["roles"]
    from services.blueprint.screen_parts import screen_parts
    parts = screen_parts(doc, doc["pages"][0])
    assert "only for those roles" in frame_prompt(doc, doc["pages"][0], parts)
    refunds = next(p for p in parts if p["key"] == "refunds")
    assert '"Lead"' in part_prompt(doc, doc["pages"][0], refunds, "export async function load() {}")


def test_the_fallback_screen_shows_a_section_only_to_its_roles():
    doc = _doc()
    cards = _section_cards(doc, doc["pages"][0], [], {"ticket"})
    by_title = {c["props"]["title"]: c for c in cards}
    assert by_title["Refunds"]["visibleIf"] == 'user.role == "Lead"'
    assert "visibleIf" not in by_title["Macros"]


def test_the_rail_offers_a_tab_only_to_those_it_is_for(tmp_path):
    doc = _doc()
    bind_menu(doc)
    project_shell(doc, tmp_path)
    shell = json.loads(next(tmp_path.rglob("shell.json")).read_text())
    groups = next(c for c in shell["children"] if c["type"] == "SideNav")["props"]["groups"]
    items = [i for g in groups for i in g.get("items") or [g]]
    refunds = next(i for i in items if i.get("route") == "/support?tab=refunds")
    assert refunds["audience"] == ["Lead"]


def test_the_workflow_author_is_told_who_does_a_sections_action():
    doc = _doc()
    slots = {s["action"]: s for s in section_slots(doc)}
    assert slots["Approve refund"]["by"] == ["Lead"] and "by" not in slots["Assign ticket"]
    assert "An action with `by` is done only by" in workflow_slot_prompt(doc)


# --- Smith reads a page as the screen it is ------------------------------------------

def test_smith_reads_a_screens_sections_its_menu_and_its_parts():
    bp = Blueprint(project_id="p")
    for key, value in to_smith_fields(_doc()).items():
        setattr(bp, key, value)
    text = blueprint_to_context(bp)
    assert "- `/support` — Support  · for Agent, Lead  · menu: Support" in text
    assert "· section Refunds [refunds] — tab at ?tab=refunds, list of Refund; only for Lead; " \
           "menu: Support > Refunds; actions: Approve refund" in text
    assert "· section Ticket [ticket] — panel opened from tickets at ?ticket=<id>, record of Ticket" in text
    assert "· section Tickets [tickets] — main, list of Ticket; adds them here; actions: Assign ticket" in text
    assert "parts/refunds.tsx, parts/tickets.tsx" in text


def test_the_fallback_shows_a_sections_action_only_to_its_roles():
    from services.blueprint.template_page import _screen_layout
    doc = _doc()
    doc["workflows"] = [{"id": "FLOW-001", "name": "Approve Refund", "purpose": "Approve it.",
                         "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"], "steps": [],
                         "inputs": []}]
    body = _screen_layout(doc, doc["pages"][0])
    cards = {c.get("props", {}).get("title"): c for c in body["root"]["children"] if c.get("type") == "Card"}
    assert cards["Approve Refund"]["visibleIf"] == 'user.role == "Lead"'
    assert "visibleIf" not in cards["Macros"]

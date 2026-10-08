"""Smith changes what a screen holds — its sections — after the build (2026-10-07).

The planner decided a screen's sections and nothing after the build could
change them: "add a refunds tab to support" could only become code with no
section behind it, which the menu could not open, a notification could not
land in, the check never visited and the next whole rewrite took away. Each
change here is made to the definition, then carried to the menu, the
workflows, the application and the screen's code.
"""
from __future__ import annotations

import copy

import pytest

from services.blueprint.service import BlueprintService
from services.smith import screen_change as sc

ROLES = [{"id": "ROLE-001", "name": "Agent"}, {"id": "ROLE-002", "name": "Lead"},
         {"id": "ROLE-003", "name": "Finance"}]
ENTITIES = [
    {"id": "ENTITY-001", "name": "Ticket", "table": "tickets",
     "fields": [{"name": "id", "type": "uuid"}, {"name": "subject", "type": "string"}]},
    {"id": "ENTITY-002", "name": "Refund", "table": "refunds",
     "fields": [{"name": "id", "type": "uuid"}, {"name": "amount", "type": "decimal"}]},
    {"id": "ENTITY-003", "name": "Note", "table": "notes",
     "fields": [{"name": "id", "type": "uuid"}, {"name": "body", "type": "string"}]},
]
SUPPORT = [
    {"key": "tickets", "label": "Tickets", "entity": "ENTITY-001", "shows": "list", "placement": "main",
     "actions": ["Assign ticket"], "roles": []},
    {"key": "ticket", "label": "Ticket", "entity": "ENTITY-001", "shows": "record", "placement": "panel",
     "opensFrom": "tickets", "param": "ticket", "actions": [], "roles": []},
    {"key": "refunds", "label": "Refunds", "entity": "ENTITY-002", "shows": "list", "placement": "tab",
     "actions": ["Approve refund"], "roles": ["ROLE-002"], "menuEntry": "Support > Refunds"},
    {"key": "refund", "label": "Refund", "entity": "ENTITY-002", "shows": "record", "placement": "panel",
     "opensFrom": "refunds", "param": "refund", "actions": [], "roles": []},
]
PAGES = [
    {"id": "PAGE-001", "name": "Support", "route": "/support", "purpose": "Work the queue.",
     "users": ["ROLE-001", "ROLE-002"], "data": {"primaryEntity": "ENTITY-001"}, "sections": SUPPORT},
    {"id": "PAGE-002", "name": "Finance", "route": "/finance", "purpose": "Money.",
     "users": ["ROLE-003"], "data": {"primaryEntity": "ENTITY-002"}, "sections": []},
    {"id": "PAGE-003", "name": "Notes", "route": "/notes", "purpose": "Notes.",
     "users": ["ROLE-001"], "data": {"primaryEntity": "ENTITY-003"}},
]
WORKFLOWS = [
    {"id": "FLOW-001", "name": "Approve Refund", "purpose": "x", "trigger": {"kind": "manual"},
     "launchedFrom": ["PAGE-001"], "steps": []},
    {"id": "FLOW-002", "name": "Assign Ticket", "purpose": "x", "trigger": {"kind": "manual"},
     "launchedFrom": ["PAGE-001"], "steps": []},
    {"id": "FLOW-003", "name": "Write Note", "purpose": "x", "trigger": {"kind": "manual"},
     "launchedFrom": ["PAGE-003"], "steps": []},
]
NAV = {"tree": [{"label": "Support", "page": "PAGE-001", "children": [
    {"label": "Refunds", "page": "PAGE-001", "section": "refunds"}]},
    {"label": "Finance", "page": "PAGE-002"}, {"label": "Notes", "page": "PAGE-003"}]}


def _doc():
    return {"roles": copy.deepcopy(ROLES), "data": {"entities": copy.deepcopy(ENTITIES)},
            "pages": copy.deepcopy(PAGES), "workflows": copy.deepcopy(WORKFLOWS),
            "navigation": copy.deepcopy(NAV)}


def _page(doc, pid):
    return next(p for p in doc["pages"] if p["id"] == pid)


def _keys(page):
    return [s["key"] for s in page.get("sections") or []]


def _nav_nodes(doc):
    out = []

    def walk(nodes):
        for n in nodes or []:
            out.append(n)
            walk(n.get("children"))
    walk(doc["navigation"]["tree"])
    return out


# --- the changes, to the definition ------------------------------------------------

def test_a_part_is_added_where_it_was_asked_with_its_records_its_link_and_its_menu_entry():
    doc = _doc()
    page = _page(doc, "PAGE-001")
    out = sc.add_section(doc, page, {"label": "Notes", "entity": "notes", "placement": "tab",
                                     "addsHere": True, "actions": ["Pin note"], "roles": ["agent"],
                                     "menuEntry": "Support > Notes", "after": "Tickets"})
    sec = sc.find_section(page, "Notes")
    assert sec["entity"] == "ENTITY-003" and sec["roles"] == ["ROLE-001"] and sec["addsHere"] is True
    assert _keys(page) == ["tickets", "notes", "ticket", "refunds", "refund"], "after Tickets, as asked"
    assert any(n.get("section") == "notes" and n["page"] == "PAGE-001" for n in _nav_nodes(doc))
    assert "added Notes" in out["what"]
    sc.add_section(doc, page, {"label": "Note", "entity": "Note", "shows": "record", "placement": "panel"})
    panel = sc.find_section(page, "Note")
    assert panel["opensFrom"] == "notes" and panel["param"] == "note", \
        "a panel opens from the list of its records, by a link named for the record"


@pytest.mark.parametrize("given,needle", [
    ({"label": "X", "entity": "Invoice"}, "there is no record called 'Invoice'"),
    ({"label": "X", "entity": "Note", "shows": "kanban"}, "`shows` is one of"),
    ({"label": "X", "entity": "Note", "placement": "sidebar"}, "`placement` is one of"),
    ({"label": "X", "entity": "Note", "roles": ["Manager"]}, "there is no role 'Manager'"),
    ({"label": "X"}, "which records does X show"),
    ({"label": "X", "entity": "Note", "colour": "red"}, "a section has no setting 'colour'"),
    ({"label": "Tickets", "entity": "Ticket"}, "already has a section 'Tickets'"),
])
def test_what_cannot_be_a_section_is_refused_with_what_would_work(given, needle):
    doc = _doc()
    page = _page(doc, "PAGE-001")
    before = copy.deepcopy(page["sections"])
    with pytest.raises(sc.ScreenChangeError) as exc:
        sc.add_section(doc, page, given)
    assert needle in str(exc.value)
    assert page["sections"] == before, "a refused section leaves the screen as it was"


@pytest.mark.parametrize("settings,check", [
    ({"label": "Refund requests"}, lambda s: s["label"] == "Refund requests" and s["key"] == "refunds"),
    ({"shows": "board"}, lambda s: s["shows"] == "board"),
    ({"placement": "main"}, lambda s: s["placement"] == "main"),
    ({"roles": []}, lambda s: s["roles"] == []),
    ({"add_roles": ["Agent"]}, lambda s: s["roles"] == ["ROLE-002", "ROLE-001"]),
    ({"remove_roles": ["Lead"]}, lambda s: s["roles"] == []),
    ({"add_actions": ["Reject refund"]}, lambda s: s["actions"] == ["Approve refund", "Reject refund"]),
    ({"remove_actions": ["approve refund"]}, lambda s: s["actions"] == []),
    ({"live": True}, lambda s: s["live"] is True),
    ({"addsHere": True}, lambda s: s["addsHere"] is True),
    ({"entity": "Note"}, lambda s: s["entity"] == "ENTITY-003"),
])
def test_every_setting_of_a_part_can_change(settings, check):
    doc = _doc()
    page = _page(doc, "PAGE-001")
    out = sc.edit_section(doc, page, "refunds", settings)
    assert check(sc.find_section(page, "refunds")), sc.find_section(page, "refunds")
    assert out["what"].startswith("changed Refunds — ")


def test_a_panel_made_a_tab_loses_what_only_a_panel_has_and_a_tab_made_a_panel_gains_it():
    doc = _doc()
    page = _page(doc, "PAGE-001")
    sc.edit_section(doc, page, "Ticket", {"placement": "tab", "shows": "list"})
    tab = sc.find_section(page, "ticket")
    assert "opensFrom" not in tab and "param" not in tab
    sc.edit_section(doc, page, "Ticket", {"placement": "panel", "shows": "record"})
    assert sc.find_section(page, "ticket")["param"] == "ticket"


def test_a_tab_is_put_in_the_menu_moved_in_it_and_taken_out():
    doc = _doc()
    page = _page(doc, "PAGE-001")
    sc.edit_section(doc, page, "Refunds", {"menuEntry": "Money > Refunds"})
    nodes = [n for n in _nav_nodes(doc) if n.get("section") == "refunds"]
    assert len(nodes) == 1 and nodes[0]["label"] == "Refunds"
    assert any(n["label"] == "Money" for n in doc["navigation"]["tree"]), "its heading is made"
    sc.edit_section(doc, page, "Refunds", {"menuEntry": ""})
    assert not [n for n in _nav_nodes(doc) if n.get("section") == "refunds"]


def test_nothing_to_change_is_said_rather_than_committed():
    doc = _doc()
    with pytest.raises(sc.ScreenChangeError, match="nothing about it would change"):
        sc.edit_section(doc, _page(doc, "PAGE-001"), "refunds", {"shows": "list"})


def test_a_part_taken_off_takes_its_panels_its_menu_entry_and_its_processes_start():
    doc = _doc()
    page = _page(doc, "PAGE-001")
    takes = sc.consequences(doc, "remove_section", route="/support", section="Refunds")
    assert any("Refund" in t and "open from it" in t for t in takes)
    assert any("Approve Refund" in t for t in takes)
    out = sc.remove_section(doc, page, "Refunds")
    assert _keys(page) == ["tickets", "ticket"]
    assert not [n for n in _nav_nodes(doc) if n.get("section") == "refunds"]
    flows = {w["id"]: w for w in doc["workflows"]}
    assert flows["FLOW-001"]["launchedFrom"] == [] and flows["FLOW-002"]["launchedFrom"] == ["PAGE-001"]
    assert any("no screen starts Approve Refund" in w for w in out["workflows"])


def test_the_parts_are_put_in_the_order_asked_and_the_rest_keep_theirs():
    doc = _doc()
    page = _page(doc, "PAGE-001")
    sc.reorder_sections(doc, page, ["Refunds", "tickets"])
    assert _keys(page) == ["refunds", "tickets", "ticket", "refund"]
    with pytest.raises(sc.ScreenChangeError, match="already in that order"):
        sc.reorder_sections(doc, page, ["refunds"])


def test_a_part_moved_to_another_screen_takes_its_panel_its_menu_entry_its_process_and_its_people():
    doc = _doc()
    support, finance = _page(doc, "PAGE-001"), _page(doc, "PAGE-002")
    sc.move_section(doc, support, "Refunds", finance)
    assert _keys(support) == ["tickets", "ticket"] and _keys(finance) == ["refunds", "refund"]
    assert sc.find_section(finance, "refund")["opensFrom"] == "refunds"
    node = next(n for n in _nav_nodes(doc) if n["label"] == "Refunds")
    assert node["page"] == "PAGE-002" and node["section"] == "refunds"
    flows = {w["id"]: w for w in doc["workflows"]}
    assert flows["FLOW-001"]["launchedFrom"] == ["PAGE-002"]
    assert finance["users"] == ["ROLE-003", "ROLE-001", "ROLE-002"], "the people who saw it still can"
    assert sc.find_section(finance, "refunds")["roles"] == ["ROLE-002"], "and it stays theirs"


def test_a_screen_folded_into_another_becomes_its_tab_and_everything_pointing_at_it_follows():
    doc = _doc()
    support, notes = _page(doc, "PAGE-001"), _page(doc, "PAGE-003")
    _page(doc, "PAGE-002")["navigatesTo"] = ["PAGE-003"]
    doc["widgets"] = [{"id": "WIDGET-001", "page": "PAGE-003", "label": "Notes today"}]
    out = sc.merge_screens(doc, support, notes)
    folded = sc.find_section(support, "Notes")
    assert folded["placement"] == "tab" and folded["entity"] == "ENTITY-003"
    assert out["tab"] == folded["key"]
    node = next(n for n in _nav_nodes(doc) if n["label"] == "Notes")
    assert node["page"] == "PAGE-001" and node["section"] == folded["key"]
    assert {w["id"]: w for w in doc["workflows"]}["FLOW-003"]["launchedFrom"] == ["PAGE-001"]
    assert _page(doc, "PAGE-002")["navigatesTo"] == ["PAGE-001"]
    assert doc["widgets"][0]["page"] == "PAGE-001"


def test_whats_folded_or_moved_never_takes_a_key_the_screen_already_has():
    doc = _doc()
    finance = _page(doc, "PAGE-002")
    finance["sections"] = [{"key": "refunds", "label": "Refunds owed", "entity": "ENTITY-002",
                            "shows": "list", "placement": "main", "actions": [], "roles": []}]
    sc.move_section(doc, _page(doc, "PAGE-001"), "Refunds", finance)
    assert _keys(finance) == ["refunds", "refunds-2", "refund"]
    assert sc.find_section(finance, "refund")["opensFrom"] == "refunds-2"


# --- the whole change, through the seam ------------------------------------------------

@pytest.fixture
def project(tmp_path, monkeypatch):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    for k, v in _doc().items():
        svc.doc[k] = v
    svc.doc["pageCode"] = [{"page": "PAGE-001", "load": "x", "view": "y"}]
    svc.save()
    (tmp_path / "app").mkdir()
    calls = {"recode": [], "workflows": [], "sync": 0}

    def recode_page(svc, route, *, app_root, request, reasoning=None, **k):
        calls["recode"].append((route, request))
        return {"applied": True, "committed": [f"pageCode:{route}"], "missing": []}

    def add_workflow(svc, ask, *, route="", app_root=None, reasoning=None, compose=True, **k):
        calls["workflows"].append((ask, route, compose))
        return {"name": ask.split(" — ")[0]}

    def sync(svc, app_root):
        calls["sync"] += 1
        return {"changed": ["src/shell.json"], "added": []}
    monkeypatch.setattr("services.smith.compose.recode_page", recode_page)
    monkeypatch.setattr("services.smith.workflow_change.add_workflow", add_workflow)
    monkeypatch.setattr("services.smith.sync_app.sync", sync)
    return tmp_path, calls


def test_a_new_tab_lands_in_the_definition_gets_its_processes_and_its_code_in_one_change(project):
    out_dir, calls = project
    out = sc.run(str(out_dir), "add_section", route="/support",
                 new_section={"label": "Escalations", "entity": "Ticket", "placement": "tab",
                              "actions": ["Escalate ticket", "Assign ticket"], "roles": ["Lead"]})
    assert out["applied"], out
    doc = BlueprintService.load(output_dir=out_dir).doc
    sec = sc.find_section(_page(doc, "PAGE-001"), "Escalations")
    assert sec and sec["roles"] == ["ROLE-002"]
    asked = [a for a, _r, _c in calls["workflows"]]
    assert len(asked) == 1 and asked[0].startswith("Escalate ticket"), "Assign ticket already has one"
    assert calls["workflows"][0][1:] == ("/support", False), "the screen is left to the one rewrite after"
    assert "done by Lead" in asked[0]
    (route, brief), = calls["recode"]
    assert route == "/support" and '"label": "Escalations"' in brief and "ctx.user?.role" in brief
    assert calls["sync"] == 1
    assert "Rewrote /support to match" in out["diff_summary"] and out["left"] == []


def test_a_refused_change_leaves_the_definition_untouched(project):
    out_dir, calls = project
    before = BlueprintService.load(output_dir=out_dir).doc
    out = sc.run(str(out_dir), "edit_section", route="/support", section="Refunds", settings={"shows": "kanban"})
    assert not out["applied"] and "`shows` is one of" in out["reason"]
    assert BlueprintService.load(output_dir=out_dir).doc["pages"] == before["pages"]
    assert calls["recode"] == [] and calls["workflows"] == []


def test_code_that_did_not_follow_is_left_for_the_loop_not_called_done(project, monkeypatch):
    out_dir, _calls = project
    monkeypatch.setattr("services.smith.compose.recode_page",
                        lambda *a, **k: {"applied": False, "reason": "did not compile: TS2322"})
    out = sc.run(str(out_dir), "edit_section", route="/support", section="Refunds", settings={"shows": "board"})
    assert out["applied"]
    assert any("/support still draws its old sections" in x and "TS2322" in x for x in out["left"])


def test_a_part_given_a_screen_of_its_own_is_a_new_screen_with_its_menu_entry_and_processes(project):
    out_dir, calls = project
    out = sc.run(str(out_dir), "split_section", route="/support", section="Refunds")
    assert out["applied"], out
    doc = BlueprintService.load(output_dir=out_dir).doc
    new = next(p for p in doc["pages"] if p["route"] == "/support/refunds")
    assert new["name"] == "Refunds" and new["users"] == ["ROLE-002"]
    assert [s["key"] for s in new["sections"]] == ["refunds", "refund"]
    assert new["sections"][0]["placement"] == "main"
    assert _keys(_page(doc, "PAGE-001")) == ["tickets", "ticket"]
    assert {w["id"]: w for w in doc["workflows"]}["FLOW-001"]["launchedFrom"] == [new["id"]]
    node = next(n for n in _nav_nodes(doc) if n["label"] == "Refunds")
    assert node["page"] == new["id"] and "section" not in node
    assert {r for r, _b in calls["recode"]} == {"/support", "/support/refunds"}


def test_a_folded_screen_is_retired_and_the_screens_linking_to_it_link_to_its_tab(project, monkeypatch):
    out_dir, calls = project
    relinked = []
    monkeypatch.setattr("services.smith.compose.pages_using",
                        lambda svc, pattern: [p for p in svc.doc["pages"] if p["id"] == "PAGE-002"])
    monkeypatch.setattr("services.smith.compose.recode_pages_using",
                        lambda svc, root, pages, reasoning=None, request="": (
                            relinked.append(request) or ([p["route"] for p in pages], [])))
    out = sc.run(str(out_dir), "merge_screens", route="/support", from_route="/notes")
    assert out["applied"], out
    doc = BlueprintService.load(output_dir=out_dir).doc
    assert _page(doc, "PAGE-003")["status"] == "DEPRECATED"
    assert sc.find_section(_page(doc, "PAGE-001"), "Notes")["placement"] == "tab"
    assert relinked and 'tab: "notes"' in relinked[0]
    assert "/finance" in out["rewritten"]


# --- a split screen gains and loses its part files ----------------------------------------

def test_a_split_screen_gains_the_part_for_a_new_tab_and_drops_the_one_for_a_removed_tab(tmp_path, monkeypatch):
    import json as _json
    from types import SimpleNamespace

    from services.blueprint import ui_engineer as ue

    doc = _doc()
    page = _page(doc, "PAGE-001")
    page["sections"] = [
        {"key": "tickets", "label": "Tickets", "entity": "ENTITY-001", "shows": "list", "placement": "main"},
        {"key": "macros", "label": "Macros", "entity": "ENTITY-003", "shows": "list", "placement": "tab"},
        {"key": "refunds", "label": "Refunds", "entity": "ENTITY-002", "shows": "list", "placement": "tab",
         "actions": ["Approve refund"]},
    ]
    current = {"load": "L", "view": 'import TicketsPart from "./parts/tickets";\nimport OldPart from "./parts/old";',
               "parts": {"tickets": "T", "old": "O"}}
    seen = {}

    def compose_page(d, p, root, client, *, brief="", current=None, feedback="", **k):
        if feedback:
            return {"load": current["load"], "view": current["view"], "parts": current["parts"]}, []
        seen["brief"], seen["files"] = brief, sorted(current["parts"])
        seen["launch"] = [w["launchedFrom"] for w in d["workflows"] if w["id"] == "FLOW-001"][0]
        view = ('import TicketsPart from "./parts/tickets";\nimport MacrosPart from "./parts/macros";\n'
                'import RefundsPart from "./parts/refunds";')
        return {"page": "PAGE-001", "load": "L2", "view": view, "parts": dict(current["parts"])}, []

    def client(system, user, schema):
        return SimpleNamespace(text=_json.dumps({"rationale": "r", "code": f"// {user.split(':')[0][:40]}"}),
                               usage=None)
    monkeypatch.setattr(ue, "compose_page", compose_page)
    monkeypatch.setattr(ue, "typecheck", lambda *a, **k: [])
    monkeypatch.setattr(ue, "_unwired_actions", lambda *a, **k: [])
    monkeypatch.setattr(ue, "_unread_handoffs", lambda *a, **k: [])
    monkeypatch.setattr(ue, "system_prompt", lambda d: "system")
    body, _spent = ue.reshape_screen(doc, page, tmp_path, client, current, brief="add two tabs")
    assert sorted(body["parts"]) == ["macros", "refunds", "tickets"], "old is gone, two are new"
    assert body["parts"]["tickets"] == "T", "a part that stays is the edit's"
    assert "// Write ONE PART" in body["parts"]["refunds"], "a new part is written on its own"
    assert seen["files"] == ["macros", "refunds", "tickets"], "the edit sees the new parts as stubs"
    assert "parts/old.tsx" in seen["brief"] and "parts/refunds.tsx" in seen["brief"]
    assert seen["launch"] == [], "the frame is not asked to run what the new part runs"


# --- through Smith: a removal waits for a yes ---------------------------------------------

def test_smith_shows_what_a_removal_takes_and_acts_on_the_yes(project, monkeypatch):
    from services.smith4.verbs import Ctx, perform
    out_dir, calls = project
    u = {"verb": "remove_section", "route": "/support", "section": "Refunds"}
    first = perform(Ctx(output_dir=str(out_dir), project_id="p", message="remove the refunds tab",
                        ask="remove the refunds tab"), "remove_section", dict(u))
    assert first.status == "asked" and "Approve Refund" in first.said and "Go ahead" in first.options
    assert sc.find_section(_page(BlueprintService.load(output_dir=out_dir).doc, "PAGE-001"), "refunds")
    second = perform(Ctx(output_dir=str(out_dir), project_id="p", message="Go ahead",
                         ask="remove the refunds tab"), "remove_section", dict(u))
    assert second.status == "resolved", second
    assert sc.find_section(_page(BlueprintService.load(output_dir=out_dir).doc, "PAGE-001"), "refunds") is None
    assert [r for r, _b in calls["recode"]] == ["/support"]


def test_what_did_not_follow_reaches_the_loop_as_a_finding(project, monkeypatch):
    from services.smith4.verbs import Ctx, perform
    out_dir, _calls = project
    monkeypatch.setattr("services.smith.compose.recode_page",
                        lambda *a, **k: {"applied": False, "reason": "did not compile"})
    step = perform(Ctx(output_dir=str(out_dir), project_id="p", message="x", ask="x"), "edit_section",
                   {"verb": "edit_section", "route": "/support", "section": "Tickets", "set": {"shows": "board"}})
    assert step.status == "resolved" and "write_page_code" in step.finding

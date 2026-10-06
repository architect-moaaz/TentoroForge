"""Mozato's 56 menu entries (forge-v3, 2026-10-06) pointed at no page: the menu
is designed before the pages and nothing linked the two. A screen names the
entry it answers (`menuEntry`) and the entry is linked when the page lands."""
import copy

from services.blueprint.menu_binding import bind_menu, menu_paths
from services.blueprint.page_planner import page_slot_prompt
from services.blueprint.projection import project_shell

TREE = [
    {"label": "Orders", "icon": "receipt", "children": [
        {"label": "Active orders", "view": "active"}, {"label": "Order history", "view": "history"}]},
    {"label": "Admin Console", "children": [
        {"label": "Cities & Zones"}, {"label": "Offers & Campaigns"}, {"label": "Coupons"}]},
]
PAGES = [
    {"id": "PAGE-001", "name": "My orders", "route": "/orders", "pattern": "master_detail",
     "menuEntry": "Orders"},
    {"id": "PAGE-002", "name": "Setup", "route": "/ops/setup", "pattern": "master_detail",
     "menuEntry": "Admin Console > Cities & Zones"},
    {"id": "PAGE-003", "name": "Marketing", "route": "/ops/marketing", "pattern": "master_detail",
     "menuEntry": "admin console > offers & campaigns",
     "sections": [{"key": "coupons", "label": "Coupons", "placement": "tab",
                   "menuEntry": "Admin Console > Coupons"}]},
]


def _doc():
    return {"application": {"name": "Mozato"}, "navigation": {"tree": copy.deepcopy(TREE)},
            "pages": copy.deepcopy(PAGES)}


def _node(doc, *labels):
    nodes = doc["navigation"]["tree"]
    for label in labels:
        node = next(n for n in nodes if n["label"] == label)
        nodes = node.get("children") or []
    return node


def test_each_entry_a_screen_names_is_linked_to_it():
    doc = _doc()
    bind_menu(doc)
    assert _node(doc, "Orders")["page"] == "PAGE-001"
    assert _node(doc, "Admin Console", "Cities & Zones")["page"] == "PAGE-002"
    assert _node(doc, "Admin Console", "Offers & Campaigns")["page"] == "PAGE-003", "case and spacing do not matter"
    coupons = _node(doc, "Admin Console", "Coupons")
    assert coupons["page"] == "PAGE-003" and coupons["section"] == "coupons"


def test_a_saved_view_follows_its_screen():
    doc = _doc()
    bind_menu(doc)
    assert _node(doc, "Orders", "Active orders")["page"] == "PAGE-001"


def test_an_entry_already_on_a_live_page_is_left_alone():
    doc = _doc()
    _node(doc, "Orders")["page"] = "PAGE-002"
    bind_menu(doc)
    assert _node(doc, "Orders")["page"] == "PAGE-002"


def test_the_rail_opens_a_tab_by_its_section(tmp_path):
    doc = _doc()
    bind_menu(doc)
    project_shell(doc, tmp_path)
    import json
    shell = json.loads(next(tmp_path.rglob("shell.json")).read_text())
    text = json.dumps(shell)
    assert '"/ops/marketing?tab=coupons"' in text and '"/orders?view=active"' in text


def test_the_planner_is_shown_the_menu_to_answer():
    doc = {**_doc(), "data": {"entities": []}, "application": {"description": "x"}}
    text = page_slot_prompt(doc)
    assert "THE MENU IS ALREADY DESIGNED" in text
    assert "  - Admin Console > Coupons" in text
    assert menu_paths(doc)[:2] == ["Orders", "Orders > Active orders"]


def test_pages_landing_link_the_menu(tmp_path):
    """Through the one door every page goes through."""
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="m", name="Mozato", domain="food")
    svc.doc["navigation"] = {"tree": copy.deepcopy(TREE)}
    svc.save()
    page = {k: v for k, v in PAGES[0].items() if k != "id"}
    apply_agent_result(svc, AgentResult(task_id="t", agent="page_design", proposals=[
        ArtifactProposal(section="pages", natural_key="/orders", body={**page, "purpose": "Orders."})]))
    node = next(n for n in svc.doc["navigation"]["tree"] if n["label"] == "Orders")
    assert node.get("page", "").startswith("PAGE-")

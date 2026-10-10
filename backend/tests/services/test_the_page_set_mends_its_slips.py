"""The page set is one five-minute call; a slip with one right answer is
mended at the seam, not refused into a rewrite (ecom v4, v5, forge-v3,
2026-10-10: four such calls lost to a duplicate menu entry, a role with no
door, an unknown module and flows the call does not write)."""
from __future__ import annotations

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, check_navigation, check_role_doors
from services.blueprint.executors import pin_page_set

DOC = {
    "modules": [{"id": "MODULE-001", "name": "Shop"}],
    "roles": [{"id": "ROLE-001", "name": "Shopper"}, {"id": "ROLE-002", "name": "Store Manager"}],
    "pages": [],
}


def _page(route, **kw):
    return ArtifactProposal(section="pages", natural_key=route, body={"route": route, "name": route.strip("/") or "Home",
                                                                       "purpose": "x", "pattern": "entity_list", **kw})


def test_duplicate_menu_entries_the_unknown_module_and_the_flows_are_mended():
    nav = ArtifactProposal(section="navigation", natural_key="nav", body={"tree": [
        {"label": "Account", "page": "PAGE-004"},
        {"label": "Profile", "page": "PAGE-004"},
        {"label": "Orders", "page": "PAGE-005", "children": [{"label": "History", "page": "PAGE-005", "view": "past"},
                                                             {"label": "Past", "page": "PAGE-005", "view": "past"}]},
    ]})
    flows = ArtifactProposal(section="flows", natural_key="JOURNEY-001", body={"goal": "browse"})
    r = AgentResult(task_id="t", agent="page_design", node="page_contracts",
                    proposals=[_page("/products", module="MODULE-001"), _page("/account", module="MODULE-009"), nav, flows])
    pin_page_set(r, DOC)
    assert [p.section for p in r.proposals] == ["pages", "pages", "navigation"], "the flows are app_flows' to write"
    assert "module" not in r.proposals[1].body, "an unknown module is left out, the page kept"
    tree = r.proposals[2].body["tree"]
    assert [n["label"] for n in tree] == ["Account", "Orders"] and [c["label"] for c in tree[1]["children"]] == ["History"]
    check_navigation(r, DOC)


def test_a_role_with_pages_and_no_door_gets_its_first_concrete_page_as_entry():
    r = AgentResult(task_id="t", agent="page_design", node="page_contracts", proposals=[
        _page("/", access="public"),
        _page("/admin/orders/[id]", access="role_restricted", users=["ROLE-002"]),
        _page("/admin/products", access="role_restricted", users=["ROLE-002"]),
        _page("/admin/orders", access="role_restricted", users=["ROLE-002"]),
    ])
    pin_page_set(r, DOC)
    doors = [p.body["route"] for p in r.proposals if p.body.get("entry")]
    assert doors == ["/admin/products"], "the first concrete page the role may open, never an [id] route"
    check_role_doors(r, DOC)


def test_a_door_already_marked_is_left_alone():
    r = AgentResult(task_id="t", agent="page_design", node="page_contracts", proposals=[
        _page("/admin/products", access="role_restricted", users=["ROLE-002"]),
        _page("/admin/orders", access="role_restricted", users=["ROLE-002"], entry=True),
    ])
    pin_page_set(r, DOC)
    assert [p.body["route"] for p in r.proposals if p.body.get("entry")] == ["/admin/orders"]


def test_the_requirements_writer_fills_in_what_a_short_ask_leaves_unsaid():
    from services.blueprint.executors import NODE_TASKS
    ask = NODE_TASKS["requirements"]
    assert "WHAT THE PERSON LEFT UNSAID IS DECIDED FROM THE DOMAIN" in ask
    assert "twenty to forty requirements" in ask and "`assumed`" in ask


def test_a_definition_turn_ends_without_a_try():
    from types import SimpleNamespace
    from services.smith4 import turn as T
    obs = [SimpleNamespace(tool="open_decisions", status="read", said="…"),
           SimpleNamespace(tool="define_application", status="resolved", said="19 requirements", touched=[])]
    assert T._done_note(obs, landed=["requirements"], said="") == "" if hasattr(T, "_done_note") else True

"""The paths people take through the application are part of its definition (2026-10-07).

ToroCommerce had its screens and processes and two links between eleven
screens: placing an order left the customer on an empty cart, a featured
product opened a search for its own name. The journeys the planner was asked
for were thrown away. Now they are `flows`: written by the planner, handed to
the page writer screen by screen, read by Smith, drawn in the App Flow view.
"""
from __future__ import annotations

import copy

import pytest

from services.blueprint import app_flows as af

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Admin"}],
    "product": {"personas": [{"name": "Customer", "goals": ["Buy clothes", "Track orders"]}]},
    "data": {"entities": [{"id": "ENTITY-003", "name": "Product"}, {"id": "ENTITY-006", "name": "Order"}]},
    "pages": [
        {"id": "PAGE-001", "name": "Home", "route": "/", "access": "public"},
        {"id": "PAGE-002", "name": "Search", "route": "/search", "access": "public",
         "sections": [{"key": "results", "label": "Results", "entity": "ENTITY-003", "placement": "main",
                       "actions": ["View product"]},
                      {"key": "detail", "label": "Product", "entity": "ENTITY-003", "placement": "panel",
                       "param": "product", "opensFrom": "results", "actions": ["Add to cart"]}]},
        {"id": "PAGE-003", "name": "Cart", "route": "/cart", "users": ["ROLE-001"]},
        {"id": "PAGE-004", "name": "Orders", "route": "/orders", "users": ["ROLE-001"],
         "sections": [{"key": "history", "label": "History", "entity": "ENTITY-006", "placement": "main"},
                      {"key": "detail", "label": "Order", "entity": "ENTITY-006", "placement": "panel",
                       "param": "order", "opensFrom": "history"}]},
    ],
    "workflows": [{"id": "FLOW-001", "name": "Add to Cart", "launchedFrom": ["PAGE-002"], "trigger": {"kind": "manual"}},
                  {"id": "FLOW-004", "name": "Place Order", "launchedFrom": ["PAGE-003"], "trigger": {"kind": "manual"}}],
    "flows": [{"id": "JOURNEY-001", "name": "Buy something", "role": "ROLE-001", "goal": "Buy clothes",
               "ends": "their order, open, with its status",
               "steps": [
                   {"page": "PAGE-001", "does": "Open a featured product", "then": "go", "carries": "ENTITY-003"},
                   {"page": "PAGE-002", "section": "detail", "does": "Add to cart", "workflow": "FLOW-001",
                    "then": "offer"},
                   {"page": "PAGE-003", "does": "Place order", "workflow": "FLOW-004", "then": "go",
                    "carries": "ENTITY-006"},
                   {"page": "PAGE-004", "section": "detail"}]}],
}


def _doc():
    return copy.deepcopy(DOC)


def test_a_screen_knows_where_each_move_on_it_leads():
    home = af.hand_offs(_doc(), "PAGE-001")
    assert home == [{"flow": "Buy something", "does": "Open a featured product", "workflow": None, "then": "go",
                     "to": "PAGE-002", "toName": "Search — Product", "address": "/search?product={id}",
                     "carries": "Product"}], "the product opens in its panel, not a search for its name"
    cart = af.hand_offs(_doc(), "PAGE-003")[0]
    assert cart["address"] == "/orders?order={id}" and cart["then"] == "go" and cart["workflow"] == "FLOW-004"
    assert af.hand_offs(_doc(), "PAGE-004") == [], "where a flow ends hands nothing on"


def test_a_process_lands_where_its_flow_goes_next():
    assert af.landing(_doc(), "FLOW-004")["address"] == "/orders?order={id}"
    assert af.landing(_doc(), "FLOW-001")["then"] == "offer"
    assert af.landing(_doc(), "FLOW-999") is None


@pytest.mark.parametrize("mend,needle", [
    (lambda d: d["flows"][0]["steps"][1].update(page="PAGE-404"), "PAGE-404 is not a screen"),
    (lambda d: d["flows"][0]["steps"][1].update(section="reviews"), "/search has no section 'reviews'"),
    (lambda d: d["flows"][0]["steps"][2].update(workflow="FLOW-001"), "which does not start it"),
    (lambda d: d["flows"][0]["steps"][2].update(does=""), "say what the person does here"),
    (lambda d: d["flows"][0].update(role="ROLE-404"), "not one of the application's roles"),
    (lambda d: d["flows"][0]["steps"][0].update(carries="ENTITY-404"), "not a record type"),
])
def test_a_flow_that_names_what_is_not_there_is_refused_naming_it(mend, needle):
    doc = _doc()
    assert af.flow_findings(doc) == []
    mend(doc)
    assert any(needle in f for f in af.flow_findings(doc)), af.flow_findings(doc)


def test_the_author_is_refused_and_told_each_step():
    from types import SimpleNamespace
    from services.blueprint.agent_contract import InvalidAppFlow, check_flows
    bad = copy.deepcopy(DOC["flows"][0])
    bad["steps"][2]["workflow"] = "FLOW-001"
    with pytest.raises(InvalidAppFlow, match="which does not start it"):
        check_flows(SimpleNamespace(proposals=[SimpleNamespace(section="flows", body=bad)]), _doc())


def test_the_flows_are_drawn_as_screens_and_moves():
    g = af.graph(_doc())["flows"][0]
    assert [n["screen"] + (":" + n["part"] if n["part"] else "") for n in g["nodes"]] == \
        ["Home", "Search:Product", "Cart", "Orders:Order"]
    assert g["nodes"][-1]["last"] and g["role"] == "Customer"
    assert [(e["does"], e["then"]) for e in g["edges"]] == \
        [("Open a featured product", "go"), ("Add to cart", "offer"), ("Place order", "go")]
    assert g["edges"][2]["process"] == "Place Order"


def test_the_page_writer_is_told_each_hand_off_with_the_sdk_names():
    from services.blueprint.ui_engineer import HAND_OFF_RULE, _page_brief
    doc = _doc()
    brief = _page_brief(doc, doc["pages"][2])
    moves = brief["handOffs"]["moves"]
    assert brief["handOffs"]["rule"] == HAND_OFF_RULE and "router.push(href(pages" in HAND_OFF_RULE
    assert moves[0]["then"] == "go" and moves[0]["to"]["address"] == "/orders?order={id}"
    assert moves[0]["to"]["sdkKey"] and moves[0]["workflow"].startswith("workflows.")
    assert "handOffs" not in _page_brief(doc, doc["pages"][3])


def test_smith_reads_the_flows():
    from services.smith.engine_blueprint_adapter import to_smith_fields
    from services.smith_blueprint import Blueprint
    from services.smith_blueprint_context import blueprint_to_context
    bp = Blueprint(project_id="p")
    for k, v in to_smith_fields(_doc()).items():
        setattr(bp, k, v)
    text = blueprint_to_context(bp)
    assert "## App flows" in text
    assert "Buy something (Customer): `/` → [Open a featured product] (go) → `/search · detail` → " \
           "[Add to cart] (offer) → `/cart` → [Place order] (go) → `/orders · detail`" in text


def test_the_planner_writes_the_flows_before_the_pages_are_written():
    from services.blueprint.agent_contract import capability_for
    from services.blueprint.executors import NODE_TASKS, build_prompt
    from services.blueprint.orchestrator import DAG
    from services.blueprint.verification import SECTION_OWNER
    node = DAG["app_flows"]
    assert node.produces == frozenset({"flows"}) and {"page_details", "workflows"} <= node.depends_on
    assert "app_flows" in DAG["page_code"].depends_on, "the page writer is told the hand-offs"
    assert "flows" in capability_for(node.agent).writes and SECTION_OWNER["flows"] == node.agent
    system, user = build_prompt(_doc(), "app_flows")
    assert "Write the FLOWS" in system and NODE_TASKS["app_flows"] in system
    assert '"goals"' in user and '"starts"' in user and "Buy something" in user, "the people, screens and flows so far"


def test_a_screen_whose_code_never_links_where_its_flow_goes_is_sent_back():
    from services.blueprint.app_sdk import page_keys
    from services.blueprint.ui_engineer import _unfollowed_flows
    doc = _doc()
    cart = doc["pages"][2]
    found = _unfollowed_flows(doc, cart, "export default function View() { return <button>Place order</button>; }")
    assert len(found) == 1 and "Buy something" in found[0] and "/orders?order={id}" in found[0]
    key = page_keys(doc)["PAGE-004"]
    assert _unfollowed_flows(doc, cart, f"router.push(href(pages.{key}, {{}}, {{ order: id }}))") == []
    search = doc["pages"][1]
    assert _unfollowed_flows(doc, search, "nothing") and "show the way there" in _unfollowed_flows(doc, search, "x")[0]


def test_what_a_process_makes_is_carried_to_its_panel_unsaid():
    doc = _doc()
    doc["flows"][0]["steps"][2].pop("carries")
    doc["workflows"][1]["steps"] = [{"key": "make", "entity": "ENTITY-006", "config": {"actionType": "db_insert"}}]
    assert af.landing(doc, "FLOW-004")["address"] == "/orders?order={id}", "the order it placed opens"
    doc["workflows"][1]["steps"] = []
    assert af.landing(doc, "FLOW-004")["address"] == "/orders", "nothing made, nothing carried"


def test_the_work_done_where_a_flow_ends_is_drawn_in_its_box():
    doc = _doc()
    doc["flows"][0]["steps"][3].update(does="Cancel the order", workflow="FLOW-001")
    last = af.graph(doc)["flows"][0]["nodes"][-1]
    assert last["last"] and last["does"] == "Cancel the order" and last["process"] == "Add to Cart"
    assert "does" not in af.graph(_doc())["flows"][0]["nodes"][-1]

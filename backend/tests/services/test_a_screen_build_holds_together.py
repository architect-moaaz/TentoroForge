"""What the first build of screens on forge-v3 showed (ToroCommerce, fxj2rza0, 2026-10-07).

Eleven screens instead of dozens of pages, every action with a process — and
five of nine contracts lost, which left admin screens open to customers, a
three-level menu with the catalogue unreachable, a menu entry opening a panel
as a tab, and customers sent links to the administrators' customer list.
"""
from __future__ import annotations

import copy
import json

from services.blueprint.executors import _DECLARED_PAGE_FIELDS, pin_page_set
from services.blueprint.projection import project_shell, restricted_roles, role_routes
from services.blueprint.record_links import notification_link

ROLES = [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Admin"}]
ENTITIES = [{"id": "ENTITY-001", "name": "Customer", "table": "customers"},
            {"id": "ENTITY-006", "name": "Order", "table": "orders"},
            {"id": "ENTITY-003", "name": "Product", "table": "products"}]
PAGES = [
    {"id": "PAGE-004", "name": "Orders", "route": "/orders", "access": "authenticated", "users": ["ROLE-001"],
     "sections": [{"key": "history", "label": "History", "entity": "ENTITY-006", "placement": "main"},
                  {"key": "detail", "label": "Order", "entity": "ENTITY-006", "placement": "panel",
                   "param": "order", "opensFrom": "history"}]},
    {"id": "PAGE-005", "name": "Profile", "route": "/profile", "access": "authenticated", "users": ["ROLE-001"]},
    {"id": "PAGE-006", "name": "Admin Products", "route": "/admin/products", "access": "role_restricted"},
    {"id": "PAGE-007", "name": "Add Product", "route": "/admin/products/new", "access": "role_restricted",
     "users": ["ROLE-002"]},
    {"id": "PAGE-009", "name": "Admin Customers", "route": "/admin/customers", "access": "role_restricted",
     "users": ["ROLE-002"],
     "sections": [{"key": "customers", "label": "Customers", "entity": "ENTITY-001", "placement": "main"},
                  {"key": "customer", "label": "Customer", "entity": "ENTITY-001", "placement": "panel",
                   "param": "customer", "opensFrom": "customers"}]},
]
NAV = {"tree": [
    {"label": "Orders", "children": [{"label": "Order History", "page": "PAGE-004"},
                                     {"label": "Order Detail", "page": "PAGE-004", "section": "detail"}]},
    {"label": "Admin", "children": [
        {"label": "Catalogue", "children": [{"label": "Products", "page": "PAGE-006"},
                                            {"label": "Add Product", "page": "PAGE-007"}]},
        {"label": "Customers", "page": "PAGE-009"}]},
]}


def _doc():
    return {"application": {"name": "ToroCommerce"}, "roles": copy.deepcopy(ROLES),
            "security": {"signupRole": "ROLE-001"},
            "data": {"entities": copy.deepcopy(ENTITIES)}, "pages": copy.deepcopy(PAGES),
            "navigation": copy.deepcopy(NAV)}


def _rail(doc, tmp_path):
    project_shell(doc, tmp_path)
    shell = json.loads(next(tmp_path.rglob("shell.json")).read_text())
    groups = next(c for c in shell["children"] if c["type"] == "SideNav")["props"]["groups"]
    return {i["label"]: i for g in groups for i in (g.get("items") or [g])}


def test_a_restricted_page_that_names_nobody_is_the_administrators_not_everyones():
    doc = _doc()
    page = next(p for p in doc["pages"] if p["id"] == "PAGE-006")
    assert restricted_roles(doc, page) == ["Admin"]
    guarded = {r["route"]: r["roles"] for r in role_routes(doc)}
    assert guarded["/admin/products"] == ["Admin"], "a customer is turned away, not let in"
    assert restricted_roles(doc, next(p for p in doc["pages"] if p["id"] == "PAGE-005")) == ["Customer"]


def test_the_rail_reaches_a_third_level_and_opens_a_panel_entry_on_its_screen(tmp_path):
    items = _rail(_doc(), tmp_path)
    assert items["Products"]["route"] == "/admin/products" and items["Products"]["roles"] == ["Admin"]
    assert items["Add Product"]["route"] == "/admin/products/new"
    assert "Catalogue" not in items, "a heading with no page of its own is not an entry going nowhere"
    assert items["Order Detail"]["route"] == "/orders", "a panel is not a tab"


def test_a_notification_links_only_where_the_person_it_reaches_may_go():
    doc = _doc()
    to_customer = {"actionType": "send_notification", "recipient": "{{customer.id}}",
                   "entity": "Customer", "entityId": "{{customer.id}}"}
    assert notification_link(doc, {}, to_customer) is None, \
        "the only screen opening a customer is the administrators'"
    order = {"actionType": "send_notification", "recipient": "{{order.customerId}}",
             "entity": "Order", "entityId": "{{order.id}}"}
    assert notification_link(doc, {}, order) == "/orders?order={{order.id}}"
    to_admin = dict(to_customer, recipientRole="Admin", recipient="")
    assert notification_link(doc, {}, to_admin) == "/admin/customers?customer={{customer.id}}"
    runner = dict(order, recipient="$user.id")
    wf = {"launchedFrom": ["PAGE-004"]}
    assert notification_link(doc, {}, runner, wf) == "/orders?order={{order.id}}"


def test_a_screen_declared_without_its_record_takes_its_main_sections():
    from types import SimpleNamespace
    body = {"name": "Search", "route": "/search", "states": ["empty"],
            "sections": [{"key": "results", "label": "Results", "entity": "ENTITY-003", "placement": "main"},
                         {"key": "detail", "label": "Product", "entity": "ENTITY-003", "placement": "panel"}]}
    result = SimpleNamespace(proposals=[SimpleNamespace(section="pages", body=body)])
    pin_page_set(result)
    assert result.proposals[0].body["data"] == {"primaryEntity": "ENTITY-003"}
    assert "states" not in result.proposals[0].body and "states" not in _DECLARED_PAGE_FIELDS


def test_what_each_state_looks_like_has_a_place_in_the_contract(tmp_path):
    from services.blueprint.executors import NODE_TASKS
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="T", domain="d")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Orders", "route": "/orders", "purpose": "x",
                         "states": ["loading", "empty"],
                         "stateNotes": {"empty": "No orders yet.", "noSelection": "The list alone."}}]
    svc.validate()
    said = NODE_TASKS["page_details"]
    assert "`stateNotes`" in said and "names only" in said
    assert "no record chosen" not in said.split("`stateNotes`")[0], \
        "the states are not asked to describe the screen — that is what invented state names"


def test_a_yes_or_no_is_seeded_as_one_whatever_its_examples_spell():
    from services.blueprint.projection import _seed_value
    active = {"name": "isActive", "type": "boolean", "required": True, "enumValues": ["true", "false"],
              "examples": ["true", "true", "true", "false"]}
    seeded = [_seed_value(active, "Customer", r) for r in range(1, 5)]
    assert seeded == [True, True, True, False], "not the strings — every customer landed deactivated"
    assert all(isinstance(v, bool) for v in seeded)


def test_a_required_yes_or_no_defaults_to_what_its_examples_mostly_say():
    from services.blueprint.projection import drizzle_column
    active, _ = drizzle_column({"name": "isActive", "type": "boolean", "required": True,
                                "examples": ["true", "true", "false"]})
    archived, _ = drizzle_column({"name": "isArchived", "type": "boolean", "required": True,
                                  "examples": ["false", "false", "true"]})
    assert ".default(true)" in active, "an account made without naming it is not created deactivated"
    assert ".default(false)" in archived
    assert ".default(" not in drizzle_column({"name": "x", "type": "boolean", "required": True})[0]


def test_a_guard_the_workflow_already_carries_is_not_added_twice():
    from services.blueprint.account_model import guard_workflow
    doc = {"data": {"entities": [{"id": "ENTITY-001", "name": "Customer", "table": "customers"}]},
           "businessRules": [{"id": "RULE-011", "name": "Active account", "kind": "prerequisite",
                              "gates": ["FLOW-001"],
                              "requires": {"entity": "ENTITY-001", "account": "id", "where": {"isActive": True}}}]}
    wf = {"id": "FLOW-001"}
    make = lambda i, t, cfg, label: {"id": i, "type": t, "data": cfg}
    nodes = [{"id": "trigger"}, {"id": "prereq_rule_011"}, {"id": "prereq_rule_011_met"},
             {"id": "prereq_rule_011_refused"}, {"id": "add"}]
    edges = [{"id": "e1", "source": "trigger", "target": "prereq_rule_011"}]
    guard_workflow(doc, wf, nodes, edges, make)
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids)), "no id used twice"
    assert edges == [{"id": "e1", "source": "trigger", "target": "prereq_rule_011"}]

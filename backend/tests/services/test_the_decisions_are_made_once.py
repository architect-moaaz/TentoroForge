"""The business facts every writer must agree on are decided once, in the
definition, and the platform enforces them.

E-commerce and TStyle (forge-v3, 2026-10-09): an order created "pending"
and set "processing" in the same process while the merchant's list filtered
"pending"; GBP on one page and USD on the next; £6.99 shipping shown and 0
stored; a glass of water logged replacing the day's total; an "Add to cart"
anyone could press that only a signed-in customer could use; anyone able to
sign up as the merchant. None of these had a place in the definition, so
each writer invented its own. `policies` is that place; the engineer writes
it first; the rest read it; launch roles and sign-up take it as decided.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint.agent_contract import (
    AGENT_REGISTRY, AgentResult, ArtifactProposal, InvalidPolicies, capability_for, check_policies,
)

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Merchant"}],
    "data": {"entities": [
        {"id": "ENTITY-005", "name": "Order", "table": "orders", "fields": [
            {"name": "status", "type": "string", "enumValues": ["pending", "processing", "shipped", "delivered"]},
            {"name": "total", "type": "number"}]}]},
    "workflows": [{"id": "FLOW-001", "name": "Add to Cart", "launchedFrom": ["PAGE-002"]},
                  {"id": "FLOW-013", "name": "Update Order Status", "launchedFrom": ["PAGE-012"]}],
    "pages": [{"id": "PAGE-002", "route": "/products", "access": "public"},
              {"id": "PAGE-012", "route": "/admin/orders", "access": "role_restricted", "users": ["ROLE-002"]}],
}

POLICIES = {
    "money": {"currency": "GBP", "locale": "en-GB",
              "rules": [{"name": "Flat shipping", "applies": "shipping", "formula": "6.99"}]},
    "time": {"mode": "person"},
    "quantities": [{"workflow": "FLOW-001", "mode": "add"}],
    "lifecycles": [{"entity": "ENTITY-005", "field": "status", "initial": "pending",
                    "moves": [{"from": "pending", "to": "processing", "by": ["ROLE-002"]},
                              {"from": "processing", "to": "shipped"}, {"from": "shipped", "to": "delivered"}]}],
    "anonymous": [{"workflow": "FLOW-001", "rule": "sign_in"}],
    "selfRegistration": ["ROLE-001"],
    "decisions": [{"about": "stock", "decided": "a product with zero stock cannot be added to a cart"}],
}


def _result(body):
    return AgentResult(task_id="TASK-decisions", agent="engineer", confidence=0.9,
                       proposals=[ArtifactProposal(section="policies", natural_key="policies", body=body)])


def test_the_definition_holds_the_decisions(tmp_path):
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    svc.doc["policies"] = json.loads(json.dumps(POLICIES))
    svc.validate()
    svc.save()
    again = BlueprintService.load(output_dir=tmp_path).doc
    assert again["policies"]["money"]["currency"] == "GBP"
    assert again["policies"]["lifecycles"][0]["moves"][0]["by"] == ["ROLE-002"]
    assert "policies" in __import__("services.blueprint.service", fromlist=["SINGLETON_SECTIONS"]).SINGLETON_SECTIONS


def test_the_engineer_decides_first_and_every_writer_reads_it():
    from services.blueprint.orchestrator import DAG, levels
    from services.blueprint.executors import NODE_TASKS
    from services.engineer.build import build_nodes
    assert capability_for("engineer").writes == frozenset({"policies"})
    for agent in ("page_design", "workflow", "business_rules", "analytics", "security", "testing"):
        assert "policies" in AGENT_REGISTRY[agent].reads, agent
    node = DAG["decisions"]
    assert node.agent == "engineer" and "policies" in node.produces
    order = [k for lvl in levels() for k in lvl]
    for writer in ("page_details", "workflows", "business_rules", "analytics", "expectations"):
        assert "decisions" in DAG[writer].depends_on, f"{writer} waits for the decisions"
        assert order.index("decisions") < order.index(writer)
    assert "`lifecycles`" in NODE_TASKS["decisions"] and "`anonymous`" in NODE_TASKS["decisions"]
    once, per, last = build_nodes()
    assert "decisions" in once and "decisions" not in per


def test_decisions_are_accepted_when_they_name_what_exists():
    check_policies(_result(POLICIES), DOC)


def test_a_decision_about_something_the_app_does_not_have_is_refused():
    bad = json.loads(json.dumps(POLICIES))
    bad["lifecycles"][0]["moves"].append({"from": "delivered", "to": "returned"})
    bad["lifecycles"].append({"entity": "ENTITY-005", "field": "colour", "initial": "red"})
    bad["anonymous"].append({"workflow": "FLOW-099", "rule": "allowed"})
    bad["selfRegistration"].append("ROLE-009")
    with pytest.raises(InvalidPolicies) as e:
        check_policies(_result(bad), DOC)
    said = str(e.value)
    assert "returned not among its values" in said
    assert "Order.colour: the entity has no such field" in said
    assert "FLOW-099" in said and "ROLE-009" in said


def test_launch_roles_take_the_anonymous_rule_as_decided():
    from services.blueprint.projection import SIGNED_IN, launch_roles
    inferred = launch_roles(DOC)
    assert inferred["FLOW-001"] == ["*"], "a public page's process is open when nothing was decided"
    decided = launch_roles({**DOC, "policies": POLICIES})
    assert decided["FLOW-001"] == [SIGNED_IN], "decided: sign in first"
    assert decided["FLOW-013"] == inferred["FLOW-013"] == ["Merchant"], "a process nobody decided about is as before"
    guest = launch_roles({**DOC, "policies": {"anonymous": [{"workflow": "FLOW-001", "rule": "guest_owned"}]}})
    assert guest["FLOW-001"] == ["*"]


def test_sign_up_offers_the_roles_decided_and_nothing_inferred():
    from services.blueprint.signup_actors import derive_signup_account_types
    two = {**DOC, "policies": {"selfRegistration": ["ROLE-001", "ROLE-002"]}}
    assert [c["value"] for c in derive_signup_account_types(two)] == ["Customer", "Merchant"]
    one = {**DOC, "policies": {"selfRegistration": ["ROLE-001"]}}
    assert derive_signup_account_types(one) == [], "one role: the default, no choice offered"


def test_the_policies_reach_the_app_as_a_contract(tmp_path):
    from services.blueprint.projection import project_policies
    out = project_policies({**DOC, "policies": POLICIES, "product": {"locale": "en"}}, tmp_path)
    body = json.loads((tmp_path / "src" / "contracts" / "policies.json").read_text())
    assert out["lifecycles"] == 1
    assert body["money"] == {"currency": "GBP", "locale": "en-GB",
                             "rules": [{"name": "Flat shipping", "applies": "shipping", "formula": "6.99"}]}
    lc = body["lifecycles"][0]
    assert lc["table"] == "orders" and lc["field"] == "status" and lc["initial"] == "pending"
    assert {"from": "pending", "to": "processing", "by": ["Merchant"]} in lc["moves"], "roles by name, as the session has them"
    empty = project_policies(DOC, tmp_path / "bare")
    assert json.loads((tmp_path / "bare" / "src" / "contracts" / "policies.json").read_text())["lifecycles"] == []


def test_a_process_declares_what_it_writes(tmp_path):
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    svc.doc["data"] = {"entities": [{"id": "ENTITY-005", "name": "Order", "table": "orders", "fields": []}]}
    svc.doc["workflows"] = [{"id": "FLOW-004", "name": "Place Order", "trigger": {"kind": "manual"},
                             "writes": [{"entity": "ENTITY-005", "fields": ["status", "total"], "states": ["pending"]}]}]
    svc.validate()
    assert svc.doc["workflows"][0]["writes"][0]["states"] == ["pending"]

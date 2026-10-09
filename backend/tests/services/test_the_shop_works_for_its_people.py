"""TCommerce and ToroCommerce (forge-v3, 2026-10-05..07) had the same three
faults, both from the platform: the shop front listed only inactive products
(a yes/no filter sent as text — run-ownership-tests.sh), Add to Cart refused
everyone "not enough stock" (`{{quantity ?? 1}}` read as one name —
run-set-variable-tests.sh), and the administrator signed in to the shop front.
This covers the landing, the guest's message, the lookup shape and who the
build's trials run as."""
import pytest

from services.blueprint.account_model import landing_by_role, roles_without_a_door
from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidWorkflowStep, RoleWithoutADoor, check_role_doors,
    check_workflow_steps,
)

ROLES = [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Admin"}]


def _shop(**nav):
    return {"roles": ROLES, "navigation": nav, "pages": [
        {"id": "PAGE-001", "route": "/", "access": "public", "entry": True},
        {"id": "PAGE-006", "route": "/admin/products", "access": "role_restricted", "entry": True},
        {"id": "PAGE-007", "route": "/admin/orders", "access": "role_restricted", "users": ["ROLE-002"]},
        {"id": "PAGE-008", "route": "/admin/orders/[id]", "access": "role_restricted", "users": ["ROLE-002"],
         "entry": True},
    ]}


def test_a_role_the_navigation_names_no_landing_for_lands_at_its_own_door():
    """ToroCommerce's navigation named no landing; /admin/products said `entry`."""
    assert landing_by_role(_shop()) == {"Admin": "/admin/products"}
    assert roles_without_a_door(_shop()) == []


def test_a_declared_landing_still_wins():
    assert landing_by_role(_shop(initialRoute={"ROLE-002": "/admin/orders"}))["Admin"] == "/admin/orders"


def _pages(*bodies):
    return AgentResult(task_id="page_contracts", agent="page_design", proposals=[
        ArtifactProposal(section="pages", natural_key=str(b["route"]), body=b) for b in bodies])


def test_a_role_with_pages_of_its_own_and_no_door_is_refused_at_the_page_author():
    doc = {"roles": ROLES, "navigation": {}, "pages": []}
    with pytest.raises(RoleWithoutADoor) as refused:
        check_role_doors(_pages({"route": "/admin/products", "access": "role_restricted", "users": ["ROLE-002"]},
                                {"route": "/admin/orders", "access": "role_restricted", "users": ["ROLE-002"]}), doc)
    assert "Admin" in str(refused.value) and "`entry: true`" in str(refused.value)
    check_role_doors(_pages({"route": "/admin/products", "access": "role_restricted", "users": ["ROLE-002"],
                             "entry": True}), doc)
    # A page edit that says nothing about its audience is never held up by it.
    check_role_doors(_pages({"route": "/admin/orders", "purpose": "Orders"}),
                     {**doc, "pages": [{"id": "P", "route": "/admin/orders", "access": "role_restricted",
                                        "users": ["ROLE-002"]}]})


def _flow(where):
    return AgentResult(task_id="workflow_steps", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Edit Profile", body={"name": "Edit Profile", "steps": [
            {"key": "check_email", "type": "action",
             "config": {"actionType": "db_query", "table": "customers", "where": where}},
            {"key": "done", "type": "end", "config": {}}]})])


@pytest.mark.parametrize("where", [{"email": "{{email}}", "id__neq": "{{customer.id}}"},
                                   {"id": {"ne": "{{customer.id}}", "eq": "x"}}])
def test_a_lookup_the_engine_cannot_read_is_refused_with_the_shape_it_can(where):
    with pytest.raises(InvalidWorkflowStep) as refused:
        check_workflow_steps(_flow(where), {"data": {"entities": []}})
    assert '{"ne": <value>}' in str(refused.value)


def test_one_comparison_is_a_lookup_the_engine_reads():
    try:
        check_workflow_steps(_flow({"email": "{{email}}", "id": {"ne": "{{customer.id}}"}}), {"data": {"entities": []}})
    except InvalidWorkflowStep as exc:
        assert "where" not in str(exc), str(exc)


def test_the_trials_are_told_who_may_run_a_process_by_name():
    """"Anyone signed in" was handed over as `@signed-in` and read as the
    administrator: ToroCommerce's shopping processes ran as Admin."""
    import json

    from services.blueprint.process_trials import INPUTS_SYSTEM, _brief
    doc = {**_shop(), "workflows": [
        {"id": "FLOW-001", "name": "Add to Cart", "launchedFrom": ["PAGE-001"], "trigger": {"kind": "manual"}},
        {"id": "FLOW-006", "name": "Create Product", "launchedFrom": ["PAGE-006"], "trigger": {"kind": "manual"}}]}
    doc["pages"][0]["access"] = "authenticated"
    shown = {p["workflow"]: p for p in json.loads(_brief(doc, doc["workflows"], {}))["processes"]}
    assert shown["FLOW-001"]["runBy"] == ["Customer", "Admin"]
    assert shown["FLOW-006"]["runBy"] == ["Admin"]
    assert shown["FLOW-006"]["startedFrom"] == [{"route": "/admin/products", "access": "role_restricted",
                                                  "for": ["Admin"]}]
    assert "never as a stand-in for a customer" in INPUTS_SYSTEM


def test_a_shared_signed_in_home_marked_entry_is_every_roles_door():
    """Payroll manager and E-commerce (forge-v3, 2026-10-09): the author marked
    /dashboard — open to everyone signed in — as `entry`; only an entry among a
    role's restricted pages counted, so the answer was refused twice and the
    build ended. A shared home is a door; a public page is not (the shop front
    ToroCommerce's administrator kept landing on), nor one for other users."""
    doc = {"roles": ROLES, "navigation": {}, "pages": []}
    check_role_doors(_pages({"route": "/dashboard", "access": "authenticated", "entry": True},
                            {"route": "/employees", "access": "role_restricted", "users": ["ROLE-002"]}), doc)
    assert landing_by_role({**doc, "pages": [{"id": "P1", "route": "/dashboard", "access": "authenticated",
                                              "entry": True}]})["Admin"] == "/dashboard"
    with pytest.raises(RoleWithoutADoor):
        check_role_doors(_pages({"route": "/", "access": "public", "entry": True},
                                {"route": "/employees", "access": "role_restricted", "users": ["ROLE-002"]}), doc)
    other = [r for r in ROLES if r.get("id") != "ROLE-002"][0]
    with pytest.raises(RoleWithoutADoor):
        check_role_doors(_pages({"route": "/home", "access": "authenticated", "entry": True,
                                 "users": [other["id"]]},
                                {"route": "/employees", "access": "role_restricted", "users": ["ROLE-002"]}), doc)

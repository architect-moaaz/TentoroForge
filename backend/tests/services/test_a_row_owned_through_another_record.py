"""Kids Vaccination Tracker (rafm22pm, forge-v3), 2026-09-26: "Appointment
Details page is empty". The security agent scoped Appointment by a
"denormalized parentId" the appointments table never had; the data engine
refused the rule and every parent saw no appointments. An appointment is a
parent's through its child: `{entity: Appointment, column: childId,
through: Child}`. The engine side is proven by run-ownership-tests.sh.
"""
import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidOwnershipRule, check_security, ownership_findings,
)
from services.blueprint.projection import ownership_rules

DOC = {"data": {"entities": [
    {"id": "ENTITY-001", "name": "Parent", "table": "parents", "account": True, "fields": [{"name": "id"}]},
    {"id": "ENTITY-002", "name": "Child", "table": "children", "fields": [{"name": "id"}, {"name": "parentId"}]},
    {"id": "ENTITY-003", "name": "Appointment", "table": "appointments",
     "fields": [{"name": "id"}, {"name": "childId"}, {"name": "doctorId"}]},
]}}


def _result(rules):
    return AgentResult(task_id="security", agent="security", proposals=[
        ArtifactProposal(section="security", natural_key="security", body={"ownershipRules": rules})])


def test_a_rule_on_a_column_the_record_lacks_is_refused_with_the_way_to_say_it():
    with pytest.raises(InvalidOwnershipRule) as refused:
        check_security(_result([{"entity": "Child", "column": "parentId"},
                                {"entity": "Appointment", "column": "parentId"}]), DOC)
    said = str(refused.value)
    assert "'parentId' is not a field of Appointment" in said and "childId" in said and "`through`" in said


def test_a_row_owned_through_a_scoped_record_is_accepted():
    check_security(_result([{"entity": "Child", "column": "parentId"},
                            {"entity": "Appointment", "column": "childId", "through": "Child"},
                            "Administrators see every record."]), DOC)


def test_through_needs_an_entity_that_exists_and_is_scoped_itself():
    assert ownership_findings({"ownershipRules": [{"entity": "Appointment", "column": "childId",
                                                   "through": "Kid"}]}, DOC) == [
        "ownership rule for Appointment: `through` names 'Kid', which the data model does not have"]
    assert "Child, which has no scope rule of its own" in ownership_findings(
        {"ownershipRules": [{"entity": "Appointment", "column": "childId", "through": "Child"}]}, DOC)[0]


def test_an_entity_the_model_lacks_is_refused():
    assert ownership_findings({"ownershipRules": [{"entity": "Booking", "column": "ownerId"}]}, DOC) == [
        "ownership rule for 'Booking': the data model has no such entity"]


def test_a_snake_case_column_names_the_same_field():
    assert ownership_findings({"ownershipRules": [{"entity": "children", "column": "parent_id"}]}, DOC) == []


def test_the_manifest_names_the_table_the_engine_resolves():
    doc = {**DOC, "security": {"ownershipRules": [
        {"entity": "Child", "column": "parentId", "kind": "scope"},
        {"entity": "Appointment", "column": "childId", "kind": "scope", "through": "Child"}]}}
    rules = ownership_rules(doc)
    assert rules["appointment"] == [{"column": "childId", "kind": "scope", "scope": "user",
                                     "unscopedRoles": [], "through": "children"}]
    assert "through" not in rules["child"][0]


MARKET = {"data": {"entities": [
    {"id": "E1", "name": "User", "table": "users", "account": True, "fields": [{"name": "id"}]},
    {"id": "E2", "name": "VendorProfile", "table": "vendor_profiles", "fields": [{"name": "id"}, {"name": "userId"}]},
    {"id": "E3", "name": "VendorOrder", "table": "vendor_orders", "fields": [{"name": "id"}, {"name": "vendorId"}]},
    {"id": "E4", "name": "OrderItem", "table": "order_items", "fields": [{"name": "id"}, {"name": "vendorOrderId"}]},
    {"id": "E5", "name": "Product", "table": "products", "fields": [{"name": "id"}, {"name": "vendorId"}]},
]}}


def test_a_chain_of_through_rules_ending_at_a_scoped_record_is_accepted():
    """Ecom L1 (2026-10-11): an order item is the vendor's through the vendor
    order, which is the vendor's through their profile — the engine walks
    three records deep, and the checker refused the chain, so the edit that
    answered dropped four entities' rules and every vendor saw every order."""
    check_security(_result([
        {"entity": "VendorProfile", "column": "userId"},
        {"entity": "VendorOrder", "column": "vendorId", "through": "VendorProfile"},
        {"entity": "OrderItem", "column": "vendorOrderId", "through": "VendorOrder"},
        {"entity": "Product", "column": "vendorId", "through": "VendorProfile"},
    ]), MARKET)


def test_a_chain_that_never_reaches_a_scoped_record_is_refused_with_what_to_add():
    found = ownership_findings({"ownershipRules": [
        {"entity": "VendorOrder", "column": "vendorId", "through": "VendorProfile"},
        {"entity": "OrderItem", "column": "vendorOrderId", "through": "VendorOrder"},
    ]}, MARKET)
    assert len(found) == 2
    assert "VendorProfile, which has no scope rule of its own" in found[0]
    assert "add a rule for VendorProfile" in found[0] and "keep this rule" in found[0]


def test_a_cycle_of_through_rules_is_refused():
    found = ownership_findings({"ownershipRules": [
        {"entity": "VendorOrder", "column": "vendorId", "through": "OrderItem"},
        {"entity": "OrderItem", "column": "vendorOrderId", "through": "VendorOrder"},
    ]}, MARKET)
    assert len(found) == 2

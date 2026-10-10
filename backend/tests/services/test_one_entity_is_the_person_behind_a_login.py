"""Exactly one entity is the person behind a login — refused where it is
declared, never charged to the field author who inherited it.

Ecommerce1 (forge-v3, 2026-10-10): the data model marked Customer AND Vendor
`account: true` in one reply; the check compared each against the entities
already applied (none yet) and let both through, then refused each field
author twice for a flag it had been told to keep. The model never finished,
and the dentist app before it (w581vsta) hit the same wall seven builds in a
row.
"""
import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidEntityFields, check_entity_fields


def _result(agent, *bodies):
    return AgentResult(task_id=f"TASK-{agent}", agent=agent, confidence=0.9,
                       proposals=[ArtifactProposal(section="data.entities", natural_key=b["name"], body=b) for b in bodies])


def _fields():
    return [{"name": "id", "type": "uuid", "primaryKey": True}, {"name": "email", "type": "string"}]


def test_two_accounts_in_one_declaration_are_refused_with_the_way_out():
    reply = _result("data_model", {"name": "Customer", "table": "customers", "account": True, "fields": _fields()},
                    {"name": "Vendor", "table": "vendors", "account": True, "fields": _fields()},
                    {"name": "Product", "table": "products", "fields": _fields()})
    with pytest.raises(InvalidEntityFields) as e:
        check_entity_fields(reply, {"data": {"entities": []}})
    said = str(e.value)
    assert "Customer and Vendor are each marked `account: true`" in said
    assert "a `userId`/`accountId` reference" in said and "never a second login" in said


def test_one_account_is_fine():
    reply = _result("data_model", {"name": "Customer", "table": "customers", "account": True, "fields": _fields()},
                    {"name": "Vendor", "table": "vendors", "fields": _fields() + [{"name": "userId", "type": "uuid", "references": "ENTITY-001"}]})
    check_entity_fields(reply, {"data": {"entities": []}})


def test_a_field_author_is_not_refused_for_a_flag_it_inherited():
    doc = {"data": {"entities": [{"id": "ENTITY-001", "name": "Customer", "table": "customers", "account": True, "fields": []},
                                 {"id": "ENTITY-002", "name": "Vendor", "table": "vendors", "account": True, "fields": []}]}}
    fields_reply = _result("data_model", {"name": "Vendor", "table": "vendors", "account": True, "fields": _fields()})
    check_entity_fields(fields_reply, doc), "the declaration is the fault, and its author is the one sent back"


def test_a_second_account_added_beside_an_existing_one_is_still_refused():
    doc = {"data": {"entities": [{"id": "ENTITY-001", "name": "Customer", "table": "customers", "account": True, "fields": []}]}}
    with pytest.raises(InvalidEntityFields, match="already on Customer"):
        check_entity_fields(_result("data_model", {"name": "Vendor", "table": "vendors", "account": True, "fields": _fields()}), doc)

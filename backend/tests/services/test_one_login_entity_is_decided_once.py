"""Two entities marked `account: true` are not both refused for each other.

ECom L4 (7ttp60zi, 2026-10-11): the entity set declared Shopper and
VendorAccount as logins; each entity's fields were refused because the
OTHER had the flag, each repair dropped its own flag "since the other holds
it", and neither landed — the screens and security never ran. The first
login entity is the login; only the other claimants are refused, told who
the login is and what to do."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidEntityFields, check_entity_fields

DOC = {"data": {"entities": [
    {"id": "ENTITY-001", "name": "Shopper", "account": True, "fields": []},
    {"id": "ENTITY-002", "name": "VendorAccount", "account": True, "fields": []},
    {"id": "ENTITY-003", "name": "Product", "fields": []},
]}}


def _fields(name: str, key: str, **extra) -> AgentResult:
    return AgentResult(task_id="t", agent="data_model", proposals=[ArtifactProposal(
        section="data.entities", natural_key=key,
        body={"name": name, "account": True, "fields": [{"name": "displayName", "type": "string"}], **extra})])


def test_the_first_login_entity_passes_and_the_other_is_told_who_the_login_is():
    check_entity_fields(_fields("Shopper", "ENTITY-001"), DOC)           # the login: no refusal
    with pytest.raises(InvalidEntityFields) as exc:
        check_entity_fields(_fields("VendorAccount", "ENTITY-002"), DOC)
    said = str(exc.value)
    assert "already on Shopper" in said and "Drop `account` here" in said and "VendorAccount is a login" in said


def test_two_claimants_in_one_entity_set_are_decided_in_that_reply():
    result = AgentResult(task_id="t", agent="data_model", proposals=[
        ArtifactProposal(section="data.entities", natural_key="Shopper", body={"name": "Shopper", "account": True}),
        ArtifactProposal(section="data.entities", natural_key="VendorAccount", body={"name": "VendorAccount", "account": True}),
    ])
    with pytest.raises(InvalidEntityFields) as exc:
        check_entity_fields(result, {"data": {"entities": []}})
    said = str(exc.value)
    assert "VendorAccount: `account: true` is already on Shopper in this reply" in said
    assert "Shopper: `account: true` is already" not in said

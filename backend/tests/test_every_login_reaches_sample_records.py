"""A person who reaches records through a column of their own — the properties
they are assigned to — holds sample values that reach the sample records.

Refund And Chargeback (pah7lhfz, 2026-10-21): cases were scoped to
`assignedPropertyIds`, whose examples named hotels; the seed wrote filler in
their place, the role logins held nothing, and twelve screens went untried.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint.account_model import login_record, project_account, scope_reach
from services.blueprint.projection import seed_in_dependency_order, seed_rows


def _doc(examples: list | None = None, *, account: bool = False, ftype: str = "json") -> dict:
    staff = {"name": "assignedPropertyIds", "type": ftype}
    if examples is not None:
        staff["examples"] = examples
    user = {"id": "ENT-001", "name": "User", "table": "users",
            "fields": [{"name": "email", "type": "string", "examples": ["a@x.com", "b@x.com", "c@x.com"]}, staff]}
    if account:
        user["account"] = True
    return {
        "data": {"entities": [
            user,
            {"id": "ENT-002", "name": "Property", "table": "properties", "labelField": "name",
             "fields": [{"name": "name", "type": "string", "examples": ["Harbourview", "Mayfair", "Old Town"]}]},
            {"id": "ENT-003", "name": "RefundCase", "table": "refund_cases",
             "fields": [{"name": "propertyId", "type": "uuid", "references": "ENT-002"},
                        {"name": "guestName", "type": "string", "examples": ["Patel", "Okafor"]}]},
        ]},
        "security": {"ownershipRules": [
            {"entity": "RefundCase", "column": "propertyId", "kind": "scope", "scope": "workspace",
             "actorColumn": "assignedPropertyIds"},
        ]},
        "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Finance"}],
    }


def test_the_login_column_a_rule_compares_against_is_read_off_the_rules():
    assert scope_reach(_doc()) == [{"column": "assignedPropertyIds", "table": "properties", "many": True}]
    assert scope_reach(_doc(ftype="uuid")) == [{"column": "assignedPropertyIds", "table": "properties", "many": False}]


def test_the_users_table_is_the_login_without_an_account_flag():
    assert login_record(_doc())["name"] == "User"
    assert login_record(_doc(account=True))["name"] == "User"


def test_examples_that_name_records_become_those_records():
    seed = seed_rows(_doc(['["Mayfair"]', '["Harbourview","Old Town"]', "[]"]))
    assert [u["assignedPropertyIds"] for u in seed["users"]] == [
        ["ref:properties[1]"], ["ref:properties[0]", "ref:properties[2]"], []]


def test_a_person_whose_examples_name_nothing_still_holds_one():
    # Names of hotels the sample properties do not have: the examples are kept
    # out, and each person is given a property in turn.
    seed = seed_rows(_doc(['["Mews Lisbon"]', '["Mews Porto"]', '["Mews Madrid"]']), rows=4, as_described=False)
    assert [u["assignedPropertyIds"] for u in seed["users"]] == [
        ["ref:properties[0]"], ["ref:properties[1]"], ["ref:properties[2]"], ["ref:properties[3]"]]
    one = seed_rows(_doc(ftype="uuid"))
    assert {u["assignedPropertyIds"] for u in one["users"]} <= {f"ref:properties[{i}]" for i in range(3)}


def test_the_records_a_person_holds_are_seeded_before_them():
    order = list(seed_in_dependency_order(seed_rows(_doc(['["Mayfair"]']))))
    assert order.index("properties") < order.index("users")


def test_the_seeder_is_told_which_columns_reach(tmp_path: Path):
    project_account(_doc(), tmp_path)
    text = (tmp_path / "src" / "lib" / "account.ts").read_text()
    line = next(x for x in text.splitlines() if x.startswith("export const SCOPE_REACH"))
    assert json.loads(line.split("= ", 1)[1].rstrip(";")) == [
        {"column": "assignedPropertyIds", "table": "properties", "many": True}]


def test_the_seeder_gives_the_logins_reach_at_every_exit():
    src = (Path(__file__).resolve().parents[1] / "templates" / "runtime" / "seed.ts").read_text()
    assert "try { await seedEverythingElse(); } finally { await giveLoginsReach(); }" in src
    assert "val = val.flatMap(" in src, "a list of refs is resolved to ids"

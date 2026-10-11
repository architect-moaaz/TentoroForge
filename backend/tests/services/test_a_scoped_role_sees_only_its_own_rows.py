"""A record type scoped to its owner is read as two different people of the
role: each gets only theirs, the two sets do not overlap, and a role the rule
exempts gets everything.

Four vendor rules demoted to prose let every vendor see every other vendor's
products and orders, and nothing in the build read the list as a second
vendor to notice (Ecom L1, 2026-10-11)."""
from __future__ import annotations

import json

from services.blueprint import access_check as acc

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Vendor"}],
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Product", "table": "products",
         "fields": [{"name": "name", "type": "string"}, {"name": "vendorId", "type": "string"}]},
        {"id": "ENTITY-002", "name": "Category", "table": "categories", "fields": [{"name": "name", "type": "string"}]},
    ]},
    "security": {"ownershipRules": [
        {"entity": "Product", "column": "vendorId", "kind": "scope", "unscopedRoles": ["Admin"]},
        "Categories are everyone's",
    ]},
}

ROWS = {"v1": [{"id": "p1", "vendorId": "v1"}, {"id": "p2", "vendorId": "v1"}],
        "v2": [{"id": "p3", "vendorId": "v2"}],
        "admin": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]}


def _wire(monkeypatch, rows, counts):
    monkeypatch.setattr(acc, "people_of_role",
                        lambda app, doc, role: [("admin", "Ada"), ("a2", "Al")] if role == "Admin"
                        else [("v1", "Vera"), ("v2", "Vik")])
    monkeypatch.setattr(acc, "_jar", lambda app, role, person: [{"name": "sub", "value": person[0]}])

    def _http(app, method, path, body, cookies):
        assert path.startswith("/api/data/products")
        return 200, "", json.dumps({"data": rows.get(cookies[0]["value"], []), "total": 0})
    monkeypatch.setattr("services.smith.trials._http", _http)
    monkeypatch.setattr("services.blueprint.page_review._query",
                        lambda app, sql: [[str(counts["own"] if "where" in sql else counts["all"])]])


def test_only_a_scoped_record_type_is_checked():
    [(entity, rules)] = acc.scoped_entities(DOC)
    assert entity["name"] == "Product" and rules[0]["column"] == "vendorId"


def test_two_vendors_who_each_get_only_their_own_is_green_and_the_exempt_admin_sees_all(monkeypatch):
    _wire(monkeypatch, ROWS, {"own": 2, "all": 3})
    out = acc.check_access(object(), DOC)
    assert out["total"] == 2 and out["red"] == [] and out["untried"] == []
    assert {g["id"]: g["why"] for g in out["green"]} == {
        "ENTITY-001:Vendor": "each Vendor gets only their own Product records",
        "ENTITY-001:Admin": "sees every Product record, as the rule exempts Admin"}


def test_a_row_that_both_vendors_get_is_red(monkeypatch):
    leaked = {**ROWS, "v2": [{"id": "p1", "vendorId": "v1"}, {"id": "p3", "vendorId": "v2"}]}
    _wire(monkeypatch, leaked, {"own": 2, "all": 3})
    out = acc.check_access(object(), DOC, only={"ENTITY-001"})
    [red] = [r for r in out["red"] if r["id"] == "ENTITY-001:Vendor"]
    assert "both get Product p1" in red["why"] and red["cause"] == "ENTITY-001"


def test_a_vendor_who_gets_someone_elses_row_or_the_wrong_count_is_red(monkeypatch):
    foreign = {**ROWS, "v1": [{"id": "p1", "vendorId": "v1"}, {"id": "p9", "vendorId": "v7"}]}
    _wire(monkeypatch, foreign, {"own": 2, "all": 3})
    out = acc.check_access(object(), DOC)
    assert "someone else's" in [r for r in out["red"] if r["id"] == "ENTITY-001:Vendor"][0]["why"]
    _wire(monkeypatch, ROWS, {"own": 5, "all": 3})
    out = acc.check_access(object(), DOC)
    assert "gets 2 Product records but owns 5" in [r for r in out["red"] if r["id"] == "ENTITY-001:Vendor"][0]["why"]


def test_an_exempt_role_that_misses_rows_is_red_and_no_rows_is_untried(monkeypatch):
    _wire(monkeypatch, {**ROWS, "admin": [{"id": "p1"}]}, {"own": 2, "all": 3})
    out = acc.check_access(object(), DOC)
    assert "exempt from the Product scope but gets 1 of 3" in [r for r in out["red"] if "Admin" in r["id"]][0]["why"]
    _wire(monkeypatch, {"v1": [], "v2": [], "admin": ROWS["admin"]}, {"own": 0, "all": 3})
    out = acc.check_access(object(), DOC)
    assert [u["why"] for u in out["untried"]] == ["no Product records belong to either Vendor on the copy"]

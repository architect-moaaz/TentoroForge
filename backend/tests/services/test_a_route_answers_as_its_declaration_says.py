"""Every route answers as its page declares, for every kind of person — a
visitor is sent to sign in, a signed-in person of another role is refused,
the people a page is for get it. Measured over HTTP, no browser, no model.

"Go to Vendor Dashboard" landed a signed-in vendor on 403 and nothing in the
build had asked the route as a vendor (Ecom L1, 2026-10-11)."""
from __future__ import annotations

import pytest

from services.blueprint import route_check as rc

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Buyer"},
              {"id": "ROLE-003", "name": "Vendor"}],
    "security": {"authentication": "email_password"},
    "data": {"entities": [{"id": "ENTITY-001", "name": "Product", "table": "products", "labelField": "name",
                           "fields": [{"name": "name", "type": "string"}]}]},
    "pages": [
        {"id": "PAGE-001", "name": "Sign in", "route": "/login", "pattern": "auth", "access": "public"},
        {"id": "PAGE-002", "name": "Catalogue", "route": "/", "access": "public"},
        {"id": "PAGE-003", "name": "Product", "route": "/products/[id]", "access": "public",
         "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-004", "name": "My Orders", "route": "/orders", "access": "authenticated"},
        {"id": "PAGE-005", "name": "Vendor Dashboard", "route": "/vendor", "access": "role_restricted",
         "users": ["ROLE-003"]},
        {"id": "PAGE-006", "name": "Old", "route": "/old", "status": "REMOVED"},
    ],
}


def test_what_each_person_should_get_follows_the_declaration():
    got = {(v["route"], v["as"]): v["expect"] for v in rc.expected_outcomes(DOC)}
    assert got[("/login", "signed out")] == "200"
    assert got[("/", "signed out")] == "200" and got[("/", "Buyer")] == "200"
    assert got[("/orders", "signed out")] == "sign-in" and got[("/orders", "Vendor")] == "200"
    assert got[("/vendor", "signed out")] == "sign-in"
    assert got[("/vendor", "Vendor")] == "200" and got[("/vendor", "Buyer")] == "403" and got[("/vendor", "Admin")] == "403"
    assert not [k for k in got if k[0] == "/old"]
    assert len(got) == 1 + 4 + 4 + 4 + 4


@pytest.mark.parametrize("status,location,expect,who,said", [
    (200, "", "200", "Buyer", []),
    (307, "/login?callbackUrl=%2Forders", "200", "Buyer", ["sends a signed-in Buyer to sign in"]),
    (307, "/403", "200", "Vendor", ["refuses Vendor, who it is for"]),
    (500, "", "200", "Buyer", ["answers HTTP 500 to Buyer"]),
    (307, "/login", "sign-in", "signed out", []),
    (200, "", "sign-in", "signed out", ["opens for a visitor who is not signed in"]),
    (307, "/403", "403", "Buyer", []),
    (403, "", "403", "Buyer", []),
    (200, "", "403", "Buyer", ["a Buyer can open /vendor, which is not for them"]),
    (307, "/login", "403", "Buyer", ["sends a signed-in Buyer to sign in instead of refusing them"]),
])
def test_an_answer_is_read_against_what_was_expected(status, location, expect, who, said):
    found = rc.outcome_findings(status, location, {"expect": expect, "as": who, "route": "/vendor"})
    assert [f.split("it ", 1)[-1] if f.startswith("it ") else f for f in found] == said


def test_every_route_is_asked_as_every_person_and_what_is_wrong_is_red(monkeypatch):
    asked = []

    def _http(app, method, path, body, cookies):
        who = cookies[0]["value"] if cookies else "signed out"
        asked.append((path, who))
        if path == "/vendor":
            if who == "signed out":
                return 307, "/login?callbackUrl=%2Fvendor", ""        # withAuth asks a visitor to sign in first
            return (200, "", "") if who in ("Vendor", "Buyer") else (307, "/403", "")
        if path == "/orders" and who == "signed out":
            return 307, "/login?callbackUrl=%2Forders", ""
        if path.startswith("/products/"):
            return (200, "", "") if path == "/products/p-1" else (404, "", "")
        return 200, "", ""
    monkeypatch.setattr("services.smith.trials._http", _http)
    monkeypatch.setattr("services.smith.trials._session",
                        lambda app, doc, ref, guest=None: (ref, [] if ref == "signed out" else [{"name": "s", "value": ref}]))
    out = rc.check_routes(object(), DOC, records={"Product": [{"id": "p-1", "label": "Lamp"}]})
    assert out["total"] == 17 and len(out["green"]) + len(out["red"]) == 17 and out["untried"] == []
    reds = {r["id"]: r["why"] for r in out["red"]}
    assert reds == {"PAGE-005::Buyer": "a Buyer can open /vendor, which is not for them"}
    assert all(r["cause"] == "PAGE-005" for r in out["red"])
    assert ("/products/p-1", "Buyer") in asked                       # the record route was filled with a real id


def test_a_record_route_with_nothing_to_open_is_untried_not_red(monkeypatch):
    monkeypatch.setattr("services.smith.trials._http", lambda *a: (200, "", ""))
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, ref, guest=None: (ref, []))
    out = rc.check_routes(object(), DOC, only={"PAGE-003"}, records={})
    assert out["red"] == [] and out["green"] == []
    assert len(out["untried"]) == 4 and out["untried"][0]["why"] == "no record to open it on"

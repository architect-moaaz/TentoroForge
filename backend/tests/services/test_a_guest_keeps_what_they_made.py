"""TCommerce (forge-v3), 2026-10-06: a signed-out shopper pressed Add to Bag,
the cart and its line were saved, and the bag page showed nothing. Cart was
scoped to `customerId`; a guest has no customer, so the read failed closed and
CartItem, owned through Cart, followed it.

`guestColumn` on an ownership rule names the field holding the visitor's guest
token. The token is the `forge-guest` cookie the workflow route mints on a
signed-out visitor's first action; every reader (SDK server, data route) and
every writer (data engine create, workflow db_insert) carries it. The engine
and workflow halves are proven by run-ownership-tests.sh and
run-insert-tests.sh; this covers the contract, the manifest and the wiring.
"""
from pathlib import Path

from services.blueprint.agent_contract import ownership_findings
from services.blueprint.projection import ownership_rules
from services.runtime_injector import _generate_workflow_api_route

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

DOC = {"data": {"entities": [
    {"id": "ENTITY-001", "name": "Customer", "table": "customers", "account": True, "fields": [{"name": "id"}]},
    {"id": "ENTITY-002", "name": "Cart", "table": "carts",
     "fields": [{"name": "id"}, {"name": "customerId"}, {"name": "guestToken"}]},
    {"id": "ENTITY-003", "name": "CartItem", "table": "cart_items", "fields": [{"name": "id"}, {"name": "cartId"}]},
]}}


def test_the_manifest_carries_the_guest_column():
    doc = {**DOC, "security": {"ownershipRules": [
        {"entity": "Cart", "column": "customerId", "kind": "scope", "guestColumn": "guestToken"},
        {"entity": "CartItem", "column": "cartId", "kind": "scope", "through": "Cart"}]}}
    rules = ownership_rules(doc)
    assert rules["cart"][0]["guestColumn"] == "guestToken"
    assert "guestColumn" not in rules["cartitem"][0]


def test_a_guest_column_the_record_lacks_is_refused():
    found = ownership_findings({"ownershipRules": [
        {"entity": "Cart", "column": "customerId", "guestColumn": "sessionId"}]}, DOC)
    assert len(found) == 1 and "guestColumn 'sessionId' is not a field of Cart" in found[0]
    assert ownership_findings({"ownershipRules": [
        {"entity": "Cart", "column": "customerId", "guestColumn": "guestToken"}]}, DOC) == []


def test_the_workflow_route_gives_a_signed_out_visitor_a_token_and_passes_it_on(tmp_path):
    _generate_workflow_api_route(tmp_path)
    route = (tmp_path / "src/app/api/workflows/[id]/execute/route.ts").read_text()
    # Read from the cookie, minted only for the signed out, handed to the run.
    assert r"forge-guest=([0-9a-f-]{36})" in route and r"(?:^|;\s*)" in route
    assert "user?.id ? undefined : globalThis.crypto.randomUUID()" in route
    assert "(input as any).__guest = _guest" in route
    # Kept by the browser: every answer the route gives sets it when minted.
    assert 'res.cookies.set("forge-guest", _guest' in route and "httpOnly: true" in route
    assert route.count("return _keepGuest(NextResponse.json(") == 2


def test_every_reader_carries_the_token():
    sdk = (TEMPLATES / "app-foundation/src/sdk/server.ts").read_text()
    assert 'get("forge-guest")' in sdk and "{ ...ctx, guest }" in sdk
    data = (TEMPLATES / "data-api-route.ts").read_text()
    assert data.count("guest: guestOf(request)") == 4

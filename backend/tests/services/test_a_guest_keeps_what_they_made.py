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


ROUTE = "src/app/api/workflows/[id]/execute/route.ts"


def test_an_app_built_before_it_is_given_the_current_route(tmp_path):
    """TCommerce was built before the route minted a token: the route is code
    the platform writes, so it is brought up to the platform's like the engine."""
    from services.smith.sync_app import refresh_engine

    app = tmp_path / "app"
    stale = app / ROUTE
    stale.parent.mkdir(parents=True)
    stale.write_text("// the route TCommerce was built with")
    assert ROUTE in refresh_engine(app)
    assert "forge-guest" in stale.read_text()
    assert not (app / "src/app/api/workflows/event/[event]/route.ts").exists(), "only a route the app has"
    assert ROUTE not in refresh_engine(app), "current: not written again"


def test_a_republish_carries_the_current_engine_without_a_smith_turn(tmp_path):
    from services.blueprint.service import BlueprintService
    from services.deploy.vercel_provider import _refresh_platform_files

    BlueprintService.create(output_dir=tmp_path, app_id="t", name="Shop", domain="retail").save()
    app = tmp_path / "app"
    (app / ROUTE).parent.mkdir(parents=True)
    (app / ROUTE).write_text("// stale")
    index = app / "src/lib/workflows/index.ts"
    index.parent.mkdir(parents=True)
    index.write_text("// stale")
    _refresh_platform_files(app)
    assert "forge-guest" in (app / ROUTE).read_text()
    assert "stampGuest" in index.read_text()
    assert 'get("forge-guest")' in (app / "src/sdk/server.ts").read_text()


def test_a_changed_ownership_rule_reaches_the_built_app(tmp_path):
    """TCommerce's Cart rule gained its guest column in the document and the
    app kept the manifest it was built with: nothing after the build wrote it."""
    from services.blueprint.service import BlueprintService
    from services.smith.reproject import everything

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Shop", domain="retail")
    svc.doc.setdefault("data", {})["entities"] = [dict(e) for e in DOC["data"]["entities"]]
    svc.doc.setdefault("security", {})["ownershipRules"] = [
        {"entity": "Cart", "column": "customerId", "kind": "scope", "guestColumn": "guestToken"}]
    app = tmp_path / "app"
    (app / "src/lib").mkdir(parents=True)
    (app / "src/lib/ownership-rules.ts").write_text("// as built")
    everything(svc, str(app))
    assert '"guestColumn": "guestToken"' in (app / "src/lib/ownership-rules.ts").read_text()

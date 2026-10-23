"""An outside system's call is believed only once its signature checks out,
put on the app's own bus once per delivery, and the check proves it by
signing, replaying and forging a call with the check's own secret
(2026-10-12). The route itself is run by `run-webhook-tests.sh`."""
from __future__ import annotations

from pathlib import Path

from services.blueprint import webhook_check as wc
from services.blueprint.projection import inbound_services, integration_slug, project_integrations

DOC = {
    "integrations": [
        {"id": "INT-001", "name": "Shop Platform", "kind": "webhook", "provider": "shop", "status": "APPROVED",
         "secretRefs": ["SHOP_API_KEY", "SHOP_WEBHOOK_SECRET"],
         "inbound": {"events": ["order.paid"], "verify": "hmac_sha256", "signingSecretRef": "SHOP_WEBHOOK_SECRET"}},
        {"id": "INT-002", "name": "Xero", "kind": "other", "provider": "xero", "status": "APPROVED", "secretRefs": ["XERO_API_KEY"]},
    ],
    "workflows": [{"id": "FLOW-020", "name": "Record a paid order", "status": "APPROVED",
                   "trigger": {"kind": "webhook", "integration": "INT-001", "event": "order.paid"}, "steps": []}],
}


def test_an_inbound_integration_is_projected_with_how_its_call_is_verified(tmp_path):
    assert inbound_services(DOC) == [{"slug": "shop-platform", "name": "Shop Platform", "provider": "shop",
                                      "verify": "hmac_sha256", "signingSecretRef": "SHOP_WEBHOOK_SECRET", "events": ["order.paid"]}]
    project_integrations(DOC, tmp_path)
    src = (tmp_path / "src/lib/integrations/connected.ts").read_text()
    assert '"shop-platform": {"name": "Shop Platform"' in src and "SHOP_WEBHOOK_SECRET" in src
    assert '"xero": {"name": "Xero", "provider": "xero", "keys": ["XERO_API_KEY"]}' in src, "every declared name, for a step's auth"
    assert "s3cret" not in src


def test_the_check_signs_replays_and_forges_with_its_own_secret(monkeypatch):
    secrets = wc.signing_secrets(DOC, env={})
    assert list(secrets) == ["SHOP_WEBHOOK_SECRET"] and len(secrets["SHOP_WEBHOOK_SECRET"]) > 20
    calls = []

    def post(app, path, raw, headers):
        calls.append((path, headers))
        sig = headers.get("X-Signature", "")
        if not sig:
            return 401, {"error": "no signature"}
        t = int(sig.split(",")[0].split("=")[1])
        if abs(t - __import__("time").time()) > 300:
            return 401, {"error": "stale signature"}
        if sig != wc.sign(raw, secrets["SHOP_WEBHOOK_SECRET"], at=t):
            return 401, {"error": "bad signature"}
        if calls.count((path, headers)) > 1:
            return 200, {"duplicate": True}
        return 202, {"accepted": True}
    monkeypatch.setattr(wc, "post", post)
    monkeypatch.setattr("services.blueprint.clock_check.runs_since", lambda app, slug, since: 1)
    out = wc.check_webhooks(object(), DOC, secrets=secrets)
    assert [g["id"] for g in out["green"]] == ["INT-001::signed", "FLOW-020::trigger", "INT-001::replay", "INT-001::forged", "INT-001::stale"]
    assert out["red"] == [] and out["untried"] == [] and out["total"] == 5
    assert calls[0][0] == "/api/webhooks/shop-platform"


def test_a_secret_the_copy_lacks_leaves_it_untried_not_red(monkeypatch):
    out = wc.check_webhooks(object(), DOC, secrets={})
    assert out["red"] == [] and out["untried"][0]["why"].startswith("SHOP_WEBHOOK_SECRET is not set")


def test_the_route_ships_outside_the_gate_and_the_bus_dedupes():
    root = Path(__file__).resolve().parents[2]
    injector = (root / "services" / "runtime_injector.py").read_text()
    assert 'src/app/api/webhooks/[integration]/route.ts' in injector
    assert "triggerWorkflowEvent(event, input, user)" not in injector, "the event route goes through the bus"
    bus = (root / "templates" / "runtime" / "events" / "bus.ts").read_text()
    assert "ON CONFLICT (dedupe_key) DO NOTHING" in bus and "{ duplicate: true }" in bus
    schema = (root / "templates" / "runtime" / "db" / "forge-events.schema.ts").read_text()
    assert 'text("dedupe_key").unique()' in schema
    from services.blueprint.platform_routes import PUBLIC
    assert any(r.route == "/api/webhooks" and r.subtree for r in PUBLIC)
    assert integration_slug({"name": "Shop Platform"}) == "shop-platform"

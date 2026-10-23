"""A process that takes money ends by sending the person to a hosted
checkout; the return pages are projected as routes; the stand-in takes
over when no key is set and says so; the cart is emptied by the payment,
not the click (2026-10-12). The adapters run in `run-payment-tests.sh`."""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint.projection import _pages_by_route, currency_of, project_money, project_workflows

ROOT = Path(__file__).resolve().parents[2]


def test_the_return_pages_become_routes_and_money_has_a_currency(tmp_path):
    cfg = _pages_by_route({"successPage": "PAGE-002", "cancelPage": "PAGE-001", "amount": 5}, {"PAGE-001": "/cart", "PAGE-002": "/orders/thanks"})
    assert cfg == {"successPage": "/orders/thanks", "cancelPage": "/cart", "amount": 5}
    assert currency_of({"product": {"currency": "aed"}}) == "AED"
    assert currency_of({"product": {"locale": "en-GB"}}) == "GBP" and currency_of({"product": {"locale": "fr-FR"}}) == "EUR"
    assert currency_of({}) == "USD"
    project_money({"product": {"locale": "ar-AE"}}, tmp_path)
    assert 'export const CURRENCY = "AED";' in (tmp_path / "src/lib/money.ts").read_text()


def test_a_checkout_step_is_projected_with_its_routes(tmp_path):
    doc = {"roles": [], "data": {"entities": [{"id": "ENTITY-001", "name": "Order", "table": "orders", "fields": []}]},
           "pages": [{"id": "PAGE-001", "route": "/cart"}, {"id": "PAGE-002", "route": "/orders/thanks"}],
           "workflows": [{"id": "FLOW-001", "name": "Pay for order", "status": "APPROVED", "trigger": {"kind": "manual"},
                          "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}},
                                    {"key": "checkout", "name": "Pay", "type": "action", "config": {"actionType": "create_checkout",
                                     "amount": "{{total}}", "reference": {"entity": "Order", "id": "{{orderId}}"},
                                     "successPage": "PAGE-002", "cancelPage": "PAGE-001"}},
                                    {"key": "done", "name": "Sent to pay", "type": "end", "config": {"refused": False, "redirect": "{{checkout.url}}"}}]}]}
    project_workflows(doc, tmp_path)
    wf = json.loads((tmp_path / "src/lib/workflows/definitions/pay-for-order.json").read_text())
    step = next(n for n in wf["definition"]["nodes"] if n["id"] == "checkout")
    assert step["data"]["config"]["successPage"] == "/orders/thanks" and step["data"]["config"]["cancelPage"] == "/cart"


def test_the_runtime_ships_the_stand_in_and_the_cart_waits_for_the_payment():
    injector = (ROOT / "services/runtime_injector.py").read_text()
    assert '"payments"]' in injector and "_forge_payments.ts" in injector and "src/app/pay/stand-in/page.tsx" in injector
    assert "input.__origin" in injector, "the run knows where the application is, for the return pages"
    cart = (ROOT / "templates/runtime/api-cart/checkout-route.ts").read_text()
    assert "db.delete(forgeCart)" not in cart and "EMPTIED BY THE PAYMENT" in cart
    handlers = (ROOT / "templates/runtime/workflows/index.ts").read_text()
    for action in ("create_checkout", "refund_payment", "payment_status", "connect_account"):
        assert f'registerActionHandler("{action}"' in handlers
    from services.blueprint.platform_routes import PUBLIC
    assert {"/pay", "/api/pay"} <= {r.route for r in PUBLIC if r.subtree}
    route = (ROOT / "templates/runtime/api-webhooks/route.ts").read_text()
    assert "onProviderCall(" in route, "a payment provider's signed call settles the ledger"

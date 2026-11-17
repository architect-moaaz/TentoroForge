"""A provider is one file in the runtime's registry and one entry in Smith's
adapter — the connect verb, the agent's adapter list and the projection read
the same registry (2026-10-12). Razorpay and PayPal joined Stripe that way
(2026-10-30), and the names each side reads must be the same names."""
from __future__ import annotations

import re
from pathlib import Path

from services.smith import connect_service, payment_connect

ROOT = Path(__file__).resolve().parents[2]


def test_payments_are_an_adapter_the_agent_and_the_projection_know():
    assert "take_payment" in connect_service.actions()
    assert connect_service.providers_of("take_payment") == {
        "stripe": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY"],
        "razorpay": ["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"],
        "paypal": ["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID", "PAYPAL_ENV"],
    }
    assert connect_service.live_key("take_payment", "stripe") == "STRIPE_SECRET_KEY"
    assert connect_service.live_key("take_payment", "razorpay") == "RAZORPAY_KEY_SECRET"
    assert connect_service.live_key("take_payment", "paypal") == "PAYPAL_CLIENT_SECRET"
    lines = connect_service.adapter_lines()
    for provider in ("stripe", "razorpay", "paypal"):
        assert f"take_payment — provider `{provider}`" in lines
    assert payment_connect.service_for("connect our Stripe account").provider == "stripe"
    assert payment_connect.service_for("take payments through Razorpay").provider == "razorpay"
    assert payment_connect.service_for("PayPal").provider == "paypal"
    assert payment_connect.service_for("Square") is None


def _ts_keys(source: str) -> dict[str, str]:
    m = re.search(r"keys:\s*\{([^}]*)\}", source)
    assert m, "an adapter declares its keys"
    return dict(re.findall(r"(\w+):\s*\"([A-Z_]+)\"", m.group(1)))


def test_the_runtime_registry_and_the_platform_keys_agree():
    index = (ROOT / "templates/runtime/payments/index.ts").read_text()
    assert re.search(r"ADAPTERS: Record<string, PaymentAdapter> = \{\s*stripe: stripeAdapter, razorpay: razorpayAdapter, "
                     r"paypal: paypalAdapter, stand_in: standInAdapter,?\s*\}", index)
    from services.payments.app_payments import FIELD_ENV, WEBHOOK_ENV
    for svc in payment_connect.SERVICES:
        ts = _ts_keys((ROOT / f"templates/runtime/payments/{svc.provider}.ts").read_text())
        # Every name the runtime reads is one Smith declares, and the webhook's is the one the route checks.
        assert set(ts.values()) <= set(svc.keys), (svc.provider, ts, svc.keys)
        assert ts["webhookSecret"] == svc.webhook_secret == WEBHOOK_ENV[svc.provider]
        # And every key Settings → Payments stores lands under a name the runtime reads.
        assert set(FIELD_ENV[svc.provider].values()) <= set(ts.values()), (svc.provider, FIELD_ENV[svc.provider], ts)
    from services.node_config_specs import keys_for_provider, providers_for_action
    # The live keys, then their test-mode twins, which only a published app's
    # test version receives (in place of the live ones; services/deploy/environments).
    from services.deploy.environments import TEST_TWINS
    assert [k.key for k in keys_for_provider("stripe")] == [
        "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY",
        TEST_TWINS["STRIPE_SECRET_KEY"], TEST_TWINS["STRIPE_WEBHOOK_SECRET"], TEST_TWINS["STRIPE_PUBLISHABLE_KEY"]]
    for action in ("take_payment", "refund_payment", "payment_status", "connect_account"):
        assert "stripe" in providers_for_action(action)

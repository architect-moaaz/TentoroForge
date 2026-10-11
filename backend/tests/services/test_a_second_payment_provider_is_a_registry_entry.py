"""A second provider is one file in the runtime's registry and one entry
in Smith's adapter — the connect verb, the agent's adapter list and the
projection read the same registry (2026-10-12)."""
from __future__ import annotations

from pathlib import Path

from services.smith import connect_service, payment_connect

ROOT = Path(__file__).resolve().parents[2]


def test_payments_are_an_adapter_the_agent_and_the_projection_know():
    assert "take_payment" in connect_service.actions()
    assert connect_service.providers_of("take_payment") == {"stripe": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY"]}
    assert connect_service.live_key("take_payment", "stripe") == "STRIPE_SECRET_KEY"
    assert "take_payment — provider `stripe`" in connect_service.adapter_lines()
    assert payment_connect.service_for("connect our Stripe account").provider == "stripe"
    assert payment_connect.service_for("PayPal") is None


def test_the_runtime_registry_and_the_platform_keys_agree():
    index = (ROOT / "templates/runtime/payments/index.ts").read_text()
    assert "ADAPTERS: Record<string, PaymentAdapter> = { stripe: stripeAdapter, stand_in: standInAdapter }" in index
    from services.node_config_specs import keys_for_provider, providers_for_action
    assert [k.key for k in keys_for_provider("stripe")] == ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY"]
    for action in ("take_payment", "refund_payment", "payment_status", "connect_account"):
        assert "stripe" in providers_for_action(action)

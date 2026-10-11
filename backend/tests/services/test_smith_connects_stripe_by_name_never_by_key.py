"""Smith connects payments by the service's NAME, records the names of its
secrets and where to register the webhook; refunds run the application's
own refund process; the currency is a product fact (2026-10-12)."""
from __future__ import annotations

from services.blueprint.service import BlueprintService
from services.smith import payment_change, payment_connect


def _svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Shop", domain="retail")
    s.doc["product"] = {"locale": "en-AE"}
    s.save()
    return s


def test_connect_stripe_declares_the_integration_with_names_only(tmp_path):
    svc = _svc(tmp_path)
    out = payment_connect.connect(svc, service="connect Stripe", output_dir=str(tmp_path))
    row = BlueprintService.load(output_dir=tmp_path).doc["integrations"][0]
    assert row["serves"] == "take_payment" and row["provider"] == "stripe" and row["kind"] == "payment"
    assert row["secretRefs"] == ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY"]
    assert row["inbound"] == {"events": ["payment.succeeded", "payment.failed", "refund.succeeded", "account.updated"],
                              "verify": "provider", "signingSecretRef": "STRIPE_WEBHOOK_SECRET"}
    said = payment_connect.summarise(out)
    assert "/api/webhooks/stripe" in said and "STRIPE_SECRET_KEY" in said and "sk_" not in said
    why, options = payment_connect.refusal("PayPal", svc.doc)
    assert "Stripe" in why and options == ["Connect Stripe"]


def test_the_currency_is_set_from_words_or_a_code(tmp_path):
    svc = _svc(tmp_path)
    out = payment_change.set_currency(svc, str(tmp_path), change="prices are in dirhams")
    assert out["applied"] and BlueprintService.load(output_dir=tmp_path).doc["product"]["currency"] == "AED"
    assert payment_change.set_currency(svc, str(tmp_path), change="use GBP")["applied"]
    assert BlueprintService.load(output_dir=tmp_path).doc["product"]["currency"] == "GBP"
    out = payment_change.set_currency(svc, str(tmp_path), change="use money")
    assert not out["applied"] and out["options"]


def test_a_refund_without_a_refund_process_offers_to_add_one(tmp_path):
    svc = _svc(tmp_path)
    out = payment_change.refund(svc, str(tmp_path), change="refund order 1234")
    assert not out["applied"] and "no refund process" in out["reason"] and out["options"]


def test_the_verbs_are_smiths():
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM
    for v in ("refund", "set_currency"):
        assert v in REQUIRED_BY_VERB and v in VERB_HELP and v in VERB_EXAMPLES and v in PERFORM

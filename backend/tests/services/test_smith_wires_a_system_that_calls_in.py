"""Smith lets an outside system call the application: the integration
gets its `inbound`, the reply says the address, the header and the NAME of
the secret to set; connecting a system no adapter carries declares it and
says how a step reaches it (2026-10-12)."""
from __future__ import annotations

import pytest

from services.blueprint.service import BlueprintService
from services.smith import connect_service, webhook_change


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Shop", domain="retail")
    s.doc["integrations"] = [{"id": "INT-001", "name": "Shopify", "kind": "webhook", "provider": "shopify",
                              "status": "APPROVED", "secretRefs": ["SHOPIFY_API_KEY"]}]
    s.save()
    return s


def test_a_system_is_let_in_with_the_address_header_and_name_to_set(svc, tmp_path):
    out = webhook_change.add_webhook(svc, str(tmp_path), integration="shopify", change="tell the app when an order is paid: order.paid")
    assert out["applied"]
    said = out["diff_summary"]
    assert "/api/webhooks/shopify" in said and "X-Signature" in said and "SHOPIFY_WEBHOOK_SECRET" in said and "order.paid" in said
    row = BlueprintService.load(output_dir=tmp_path).doc["integrations"][0]
    assert row["inbound"] == {"events": ["order.paid"], "verify": "hmac_sha256", "signingSecretRef": "SHOPIFY_WEBHOOK_SECRET"}
    assert "SHOPIFY_WEBHOOK_SECRET" in row["secretRefs"]
    again = webhook_change.add_webhook(svc, str(tmp_path), integration="shopify", change="how do I call it")
    assert again["applied"] and "/api/webhooks/shopify" in again["diff_summary"], "asked again, it says how; nothing changes"


def test_an_unknown_system_is_asked_about(svc, tmp_path):
    out = webhook_change.run(str(tmp_path), integration="Xero")
    assert not out["applied"] and "cannot tell which system" in out["reason"] and "Shopify" in out["reason"]


def test_connect_service_tries_every_adapter_then_declares(monkeypatch, tmp_path):
    seen = {}
    def email_run(out, *, service, reasoning=None):
        seen["email"] = service
        return {"applied": True}
    monkeypatch.setattr(connect_service.email_connect, "run", email_run)
    assert connect_service.run(str(tmp_path), service="our Outlook")["applied"] and seen["email"] == "our Outlook"
    monkeypatch.setattr(connect_service, "declare", lambda out, service, reasoning=None: {"applied": True, "diff_summary": f"Declared {service}"})
    assert "Declared Xero" in connect_service.run(str(tmp_path), service="Xero")["diff_summary"]
    assert connect_service.actions() == {"send_email", "take_payment", "sign_in"} and "resend" in connect_service.providers_of("send_email")


def test_the_verb_is_smiths():
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM
    assert "add_webhook" in REQUIRED_BY_VERB and "add_webhook" in VERB_HELP and "add_webhook" in VERB_EXAMPLES and "add_webhook" in PERFORM

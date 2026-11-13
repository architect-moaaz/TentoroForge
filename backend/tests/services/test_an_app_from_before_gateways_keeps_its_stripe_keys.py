"""An app from before payment gateways keeps the Stripe keys it was built with.

#37 review, 2026-11-13: such an app takes money through its own Stripe
integration and has no `payments` section. The next rebuild (or a Smith turn
that mentions payments) asked Forge to decide, which wrote
`decidedBy: "forge"` with no gateway chosen. From then on the gateways
governed the app: every STRIPE_* variable came back None from
`env_for_side`, and the next publish removed them from production. Checkout
and webhooks stopped, though nobody had touched the app's payments.

It stays the older way until a person (or Smith, asked) chooses its gateways.
An app with no Stripe integration of its own is decided for as before.
"""
from __future__ import annotations

from services.blueprint.service import BlueprintService
from services.payments import app_payments as AP
from services.payments.webhooks import governs

STRIPE = {"id": "INT-001", "name": "Stripe", "provider": "stripe", "status": "PROPOSED", "serves": "take_payment"}


def _svc(tmp_path, *, integrations=()):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Shop", domain="retail",
                                  description="A shop where customers pay for orders at checkout.")
    svc.save()
    svc = BlueprintService.load(output_dir=tmp_path)
    svc.doc["integrations"] = [dict(i) for i in integrations]
    return svc


def _never(_prompt):
    raise AssertionError("an app on its own Stripe keys is not decided for")


def test_forge_does_not_decide_for_an_app_on_its_own_stripe(tmp_path):
    svc = _svc(tmp_path, integrations=[STRIPE])
    before = dict(svc.doc.get("payments") or {})
    state = AP.decide_and_record(svc, provider=_never)
    assert (svc.doc.get("payments") or {}) == before and state["decidedBy"] is None
    assert not governs(svc.doc), "the gateways do not govern it, so its STRIPE_* variables are left alone"


def test_an_app_stamped_by_forge_before_this_fix_is_still_left_alone(tmp_path):
    svc = _svc(tmp_path, integrations=[STRIPE])
    svc.doc["payments"] = {"needed": True, "models": ["one_time"], "decidedBy": "forge", "gateways": []}
    assert not governs(svc.doc)


def test_once_its_owner_chooses_gateways_they_govern_it(tmp_path):
    svc = _svc(tmp_path, integrations=[STRIPE])
    svc.doc["payments"] = {"needed": True, "models": ["one_time"], "decidedBy": "person", "gateways": []}
    assert governs(svc.doc), "a person's decision, even 'none chosen yet', hands it to the gateways"
    svc.doc["payments"] = {"needed": True, "models": ["one_time"], "decidedBy": "forge",
                           "gateways": [{"gateway": "g1", "provider": "stripe"}]}
    assert governs(svc.doc)


def test_a_retired_stripe_integration_does_not_hold_it_back(tmp_path):
    svc = _svc(tmp_path, integrations=[{**STRIPE, "status": "REMOVED"}])
    svc.doc["payments"] = {"needed": True, "models": ["one_time"], "decidedBy": "forge", "gateways": []}
    assert governs(svc.doc)


def test_an_app_without_stripe_is_decided_for_as_before(tmp_path):
    svc = _svc(tmp_path)
    calls = []

    def provider(prompt):
        calls.append(prompt)
        return '{"needed": true, "models": ["one_time"], "reason": "Customers pay at checkout."}'
    state = AP.decide_and_record(svc, provider=provider)
    assert calls and state["decidedBy"] == "forge" and governs(svc.doc)

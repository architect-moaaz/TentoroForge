"""A checkout step is refused at the author unless it says what it pays for
and something listens for the payment; the check drives a stand-in
checkout through to settled and refunded (2026-10-12)."""
from __future__ import annotations

import pytest

from services.blueprint import payment_check as pc
from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidTrigger, check_workflow_triggers

DOC = {"roles": [{"id": "ROLE-001", "name": "Shopper"}], "data": {"entities": [{"id": "ENTITY-001", "name": "Order"}]},
       "integrations": [{"id": "INT-001", "name": "Stripe", "status": "APPROVED", "serves": "take_payment",
                         "secretRefs": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
                         "inbound": {"events": ["payment.succeeded"], "verify": "provider", "signingSecretRef": "STRIPE_WEBHOOK_SECRET"}}],
       "workflows": [{"id": "FLOW-002", "name": "Record a paid order", "status": "APPROVED",
                      "trigger": {"kind": "webhook", "integration": "INT-001", "event": "payment.succeeded"}, "steps": []}]}


def _pay(cfg: dict) -> AgentResult:
    return AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Pay for order", body={"name": "Pay for order", "trigger": {"kind": "manual"},
        "steps": [{"key": "checkout", "name": "Pay", "type": "action", "config": {"actionType": "create_checkout", **cfg}}]})])


def test_a_checkout_that_says_what_it_pays_for_passes_when_something_listens():
    check_workflow_triggers(_pay({"amount": "{{total}}", "reference": {"entity": "Order", "id": "{{orderId}}"}}), DOC)


@pytest.mark.parametrize("cfg,doc,said", [
    ({"amount": 5}, DOC, "names the record it pays for"),
    ({"reference": {"entity": "Order", "id": "x"}}, DOC, "says what is paid"),
    ({"amount": 5, "reference": {"entity": "Order", "id": "x"}}, {**DOC, "workflows": []}, "nothing listens for `payment.succeeded`"),
    ({"amount": 5, "reference": {"entity": "Order", "id": "x"}}, {**DOC, "integrations": []}, "no integration `serves: take_payment`"),
])
def test_a_checkout_nobody_can_settle_is_refused(cfg, doc, said):
    with pytest.raises(InvalidTrigger, match=said):
        check_workflow_triggers(_pay(cfg), doc)


def test_the_check_drives_the_stand_in_to_paid_and_refunded(monkeypatch):
    doc = {**DOC, "workflows": DOC["workflows"] + [
        {"id": "FLOW-001", "name": "Pay for order", "status": "APPROVED", "trigger": {"kind": "manual"}, "inputs": [],
         "steps": [{"key": "checkout", "name": "Pay", "type": "action", "config": {"actionType": "create_checkout", "amount": 5, "reference": {"entity": "Order", "id": "x"}}}]},
        {"id": "FLOW-003", "name": "Refund an order", "status": "APPROVED", "trigger": {"kind": "manual"}, "inputs": [{"name": "paymentId"}],
         "steps": [{"key": "refund", "name": "Refund", "type": "action", "config": {"actionType": "refund_payment", "paymentId": "{{paymentId}}"}}]}]}
    assert [w["id"] for w in pc.paying(doc)] == ["FLOW-001"] and [w["id"] for w in pc.refunding(doc)] == ["FLOW-003"]
    state = {"rows": 0, "status": "pending"}

    def rows(app, sql):
        if sql.startswith("select count(*) from forge_payments"):
            return [[str(state["rows"])]]
        if sql.startswith("select id, status, provider"):
            return [["p-1", state["status"], "stand_in"]]
        if "select status from forge_payments" in sql:
            return [[state["status"]]]
        return []
    monkeypatch.setattr(pc, "_rows", rows)
    monkeypatch.setattr("services.blueprint.process_trials._records", lambda app, doc: {})
    monkeypatch.setattr("services.blueprint.process_trials.compose_inputs", lambda doc, flows, records, client: {"FLOW-001": {"as": "Shopper", "input": {}}})

    def run(name, args, *, bench, doc):
        if args["workflow"] == "FLOW-001":
            state["rows"] += 1
            return '`try_workflow` Pay for order: completed\n"redirect": "http://app/pay/stand-in?session=standin_p-1"'
        state["status"] = "refunded"
        return "`try_workflow` Refund an order: completed"
    monkeypatch.setattr("services.smith.trials.run", run)
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, role, guest=None: (role, []))

    def post(app, path, body, cookies):
        state["status"] = "succeeded"
        return 200, {"ok": True}
    monkeypatch.setattr(pc, "_post", post)
    monkeypatch.setattr("services.blueprint.clock_check.runs_since", lambda app, slug, since: 1)
    out = pc.check_payments(object(), doc, bench=object(), client=object())
    assert [g["id"] for g in out["green"]] == ["FLOW-001::checkout", "FLOW-001::settled", "FLOW-003::refund"]
    assert out["red"] == [] and out["untried"] == []
    assert "Record a paid order ran" in out["green"][1]["why"]

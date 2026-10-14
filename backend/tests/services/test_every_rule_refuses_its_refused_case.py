"""Every rule that gates a process is tried with an input it must refuse;
green only when the application refuses with its own message.

Process trials prove the accepting path; the stock cap that made the refusal
unreachable was found by a tester, not the build (Ecom L1, 2026-10-11)."""
from __future__ import annotations

import json
from types import SimpleNamespace

from services.blueprint import rule_trials as rt
from services.smith import trials

FLOWS = [
    {"id": "FLOW-001", "name": "Add to cart", "trigger": {"kind": "manual"},
     "inputs": [{"name": "product", "kind": "record", "entity": "ENTITY-001", "required": True},
                {"name": "quantity", "kind": "field", "type": "number", "required": True}]},
    {"id": "FLOW-002", "name": "Apply as vendor", "trigger": {"kind": "manual"},
     "inputs": [{"name": "shopName", "kind": "field", "type": "string", "required": True}]},
]
DOC = {
    "workflows": FLOWS,
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Buyer"}],
    "data": {"entities": [{"id": "ENTITY-001", "name": "Product", "table": "products", "labelField": "name",
                           "fields": [{"name": "name", "type": "string"}, {"name": "stock", "type": "number"}]}]},
    "pages": [],
    "businessRules": [
        {"id": "RULE-001", "name": "Stock cap", "statement": "A buyer cannot add more than is in stock",
         "kind": "prerequisite", "gates": ["FLOW-001"], "message": "Not enough in stock"},
        {"id": "RULE-002", "name": "One shop per vendor", "statement": "A person may apply once",
         "appliesTo": ["FLOW-002"]},
        {"id": "RULE-003", "name": "Payouts monthly", "statement": "Payouts are split on the first of the month"},
    ],
    "domainReference": {"rules": [{"name": "Stock cap", "statement": "…", "refusedCase": "quantity 999 of a product with stock 3"}]},
}
REFUSED = 'Add to cart (FLOW-001) run as Buyer: HTTP 422\nanswer: {"refused": true, "error": "Not enough in stock"}'
ACCEPTED = "Apply as vendor (FLOW-002) run as Buyer: HTTP 200\nanswer: {}\nsteps:\n  0. Create [db] completed"


def _client(seen):
    def call(*, system, user, schema):
        seen.append(json.loads(user.split("\n\nThe processes", 1)[0]))
        return json.dumps({"runs": [
            {"rule": "RULE-001", "workflow": "FLOW-001", "as": "Buyer",
             "input": [{"name": "product", "value": '"p-1"'}, {"name": "quantity", "value": "999"}]},
            {"rule": "RULE-002", "workflow": "FLOW-002", "as": "Buyer",
             "input": [{"name": "shopName", "value": '"Second shop"'}]}]})
    return call


def test_the_rules_that_gate_a_process_are_tried_and_the_rest_are_untried():
    assert [(r["id"], f["id"]) for r, f in rt.gated(DOC)] == [("RULE-001", "FLOW-001"), ("RULE-002", "FLOW-002")]
    assert [r["id"] for r in rt.ungated(DOC)] == ["RULE-003"]


def test_a_refusal_is_green_an_acceptance_is_red(monkeypatch):
    runs = []

    def run(name, args, *, bench, doc):
        runs.append(args)
        return REFUSED if args["workflow"] == "FLOW-001" else ACCEPTED
    monkeypatch.setattr(trials, "run", run)
    seen = []
    bench = SimpleNamespace(app=lambda: SimpleNamespace(base="http://x"))
    out = rt.refuse_rules(DOC, bench, _client(seen), records={"Product": [{"id": "p-1", "label": "Lamp"}]})
    assert out["total"] == 3
    assert [g["id"] for g in out["green"]] == ["RULE-001"] and "refuses it" in out["green"][0]["why"]
    assert [r["id"] for r in out["red"]] == ["RULE-002"] and "accepts what the rule says to refuse" in out["red"][0]["why"]
    assert [u["id"] for u in out["untried"]] == ["RULE-003"]
    assert runs[0] == {"workflow": "FLOW-001", "input": {"product": "p-1", "quantity": 999}, "as": "Buyer"}
    shown = seen[0]["rules"]
    assert shown[0]["refusedCase"] == "quantity 999 of a product with stock 3"    # the reference's case is used
    assert "refusedCase" not in shown[1]


def test_a_process_that_breaks_instead_of_refusing_is_red_and_a_down_app_is_untried(monkeypatch):
    monkeypatch.setattr(trials, "run", lambda *a, **k: "`try_workflow` failed: TimeoutError: 240s")
    bench = SimpleNamespace(app=lambda: SimpleNamespace(base="http://x"))
    out = rt.refuse_rules(DOC, bench, _client([]), records={}, only={"RULE-001"})
    assert [r["id"] for r in out["red"]] == ["RULE-001"] and "breaks instead of refusing" in out["red"][0]["why"]

    def down():
        raise trials.TrialUnavailable("next dev would not start")
    out = rt.refuse_rules(DOC, SimpleNamespace(app=down), _client([]))
    assert out["green"] == [] and out["red"] == []
    assert sorted(u["id"] for u in out["untried"]) == ["RULE-001", "RULE-002", "RULE-003"]

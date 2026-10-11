"""A `db_change` trigger is projected as the event the data engine emits —
the table's export name, lowercased, then the change — so the bus starts
the process. It used to be written under `definition.trigger.condition`,
which nothing read (2026-10-12). The check proves it by putting the event on
the bus and ticking."""
from __future__ import annotations

from services.blueprint import clock_check as cc
from services.blueprint.projection import _trigger_contract

DOC = {
    "data": {"entities": [{"id": "ENTITY-002", "name": "VendorAccount", "table": "vendor_accounts", "fields": []}]},
    "workflows": [
        {"id": "FLOW-010", "name": "Welcome a vendor", "status": "ACTIVE",
         "trigger": {"kind": "db_change", "detail": "when a vendor signs up", "entity": "ENTITY-002", "on": "created"},
         "steps": [{"key": "start", "type": "trigger", "config": {"type": "db_change"}},
                   {"key": "done", "type": "end", "config": {}}]},
        {"id": "FLOW-011", "name": "Record a payment", "status": "ACTIVE",
         "trigger": {"kind": "api_event", "detail": "payment.succeeded"},
         "steps": [{"key": "start", "type": "trigger", "config": {"type": "api_event"}},
                   {"key": "done", "type": "end", "config": {}}]},
    ],
}


def test_a_record_change_is_the_event_the_engine_emits():
    assert _trigger_contract(DOC, DOC["workflows"][0]) == {"kind": "event", "event": "vendoraccounts.created"}
    assert _trigger_contract(DOC, DOC["workflows"][1]) == {"kind": "event", "event": "payment.succeeded"}
    assert _trigger_contract(DOC, {"trigger": {"kind": "db_change", "entity": "ENTITY-404", "on": "created"}}) is None


def test_the_check_puts_the_event_on_the_bus_and_reads_that_it_ran(monkeypatch, tmp_path):
    put, ticks = [], []
    monkeypatch.setattr(cc, "put_event", lambda app, event: put.append(event))
    monkeypatch.setattr(cc, "tick", lambda app, app_root, **p: ticks.append(p) or (200, {"events": {"dispatched": 1}}))
    monkeypatch.setattr(cc, "runs_since", lambda app, slug, since: 1 if slug == "welcome-a-vendor" else 0)
    out = cc.check_clock(object(), DOC, bench=None, app_root=tmp_path)
    assert put == ["vendoraccounts.created", "payment.succeeded"] and len(ticks) == 2
    assert [g["id"] for g in out["green"]] == ["FLOW-010::trigger"]
    assert out["red"][0]["id"] == "FLOW-011::trigger" and "started nothing" in out["red"][0]["why"]

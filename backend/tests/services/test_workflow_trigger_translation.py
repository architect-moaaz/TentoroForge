"""R1/R2 trigger-contract translation — plan workflow trigger → emitted JSON.

The runtime event bus (templates/runtime/events/bus.ts) and cron scheduler
(templates/runtime/events/scheduler.ts) read a TOP-LEVEL ``trigger`` key on
each workflow JSON:

    {"kind": "event",    "event": "order.created"}
    {"kind": "schedule", "cron":  "0 9 * * 1"}

These tests pin the Python side of that contract:
  * a plan workflow declaring an event trigger → emitted JSON carries it
  * a schedule trigger (explicit cron or cadence shorthand) → idem
  * no/manual/button trigger → NO top-level ``trigger`` key
"""
from __future__ import annotations

import json
from pathlib import Path

from services.workflow_generator import (
    derive_trigger_contract,
    generate_workflow_definitions,
)


# ── unit: derive_trigger_contract shapes ─────────────────────────────


def test_dict_event_trigger_maps_to_event_contract():
    wf = {"name": "OrderFollowup",
          "trigger": {"type": "db_change", "event": "order.created"}}
    assert derive_trigger_contract(wf) == {"kind": "event", "event": "order.created"}


def test_kind_event_shape_accepted():
    wf = {"name": "X", "trigger": {"kind": "event", "event": "Invoice.Paid"}}
    assert derive_trigger_contract(wf) == {"kind": "event", "event": "invoice.paid"}


def test_db_change_entity_and_op_builds_event_name():
    wf = {"name": "X",
          "trigger": {"type": "db_change", "entity": "Order", "on": "update"}}
    assert derive_trigger_contract(wf) == {"kind": "event", "event": "order.updated"}


def test_db_change_entity_defaults_to_created():
    wf = {"name": "X", "trigger": {"type": "db_change", "entity": "Shipment"}}
    assert derive_trigger_contract(wf) == {"kind": "event", "event": "shipment.created"}


def test_explicit_cron_wins():
    wf = {"name": "X", "trigger": {"type": "schedule", "cron": "0 9 * * 1"}}
    assert derive_trigger_contract(wf) == {"kind": "schedule", "cron": "0 9 * * 1"}


def test_cadence_shorthand_maps_to_cron():
    assert derive_trigger_contract(
        {"name": "X", "trigger": {"type": "schedule", "every": "daily"}}
    ) == {"kind": "schedule", "cron": "0 9 * * *"}
    assert derive_trigger_contract(
        {"name": "X", "trigger": {"type": "schedule", "every": "6h"}}
    ) == {"kind": "schedule", "cron": "0 */6 * * *"}
    assert derive_trigger_contract(
        {"name": "X", "trigger": {"type": "schedule", "every": "15 minutes"}}
    ) == {"kind": "schedule", "cron": "*/15 * * * *"}


def test_string_trigger_shapes():
    assert derive_trigger_contract({"trigger": "order.created"}) == {
        "kind": "event", "event": "order.created"}
    assert derive_trigger_contract({"trigger": "0 9 * * 1"}) == {
        "kind": "schedule", "cron": "0 9 * * 1"}


def test_manual_and_prose_triggers_map_to_none():
    assert derive_trigger_contract({"trigger": "manual"}) is None
    assert derive_trigger_contract({"trigger": "button:Approve"}) is None
    assert derive_trigger_contract({"trigger": "user submits the form"}) is None
    assert derive_trigger_contract({"trigger": {"type": "manual"}}) is None
    assert derive_trigger_contract({}) is None
    assert derive_trigger_contract({"trigger": None}) is None


# ── end-to-end: generate_workflow_definitions emits the contract ─────


def _emitted(tmp_path: Path, workflow: dict) -> dict:
    plan = {"workflows": [workflow], "data_models": []}
    count = generate_workflow_definitions(str(tmp_path), plan)
    assert count == 1
    files = list((tmp_path / "workflows").glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_event_trigger_carried_into_emitted_json(tmp_path):
    doc = _emitted(tmp_path, {
        "name": "OrderCreatedNotifier",
        "description": "Notify ops when an order is created",
        "trigger": {"type": "db_change", "event": "order.created"},
        "steps": ["Send notification to ops"],
    })
    assert doc["trigger"] == {"kind": "event", "event": "order.created"}
    # The legacy definition.trigger stays intact for older consumers.
    assert "trigger" in doc["definition"]


def test_schedule_trigger_carried_into_emitted_json(tmp_path):
    doc = _emitted(tmp_path, {
        "name": "WeeklyDigest",
        "description": "Send the weekly digest",
        "trigger": {"type": "schedule", "cron": "0 9 * * 1"},
        "steps": ["Send digest email"],
    })
    assert doc["trigger"] == {"kind": "schedule", "cron": "0 9 * * 1"}


def test_manual_workflow_emits_no_trigger_key(tmp_path):
    doc = _emitted(tmp_path, {
        "name": "ApproveApplication",
        "description": "Manager approves an application",
        "trigger": "button",
        "steps": ["Approve application"],
    })
    assert "trigger" not in doc  # top level — definition.trigger still exists
    assert "trigger" in doc["definition"]

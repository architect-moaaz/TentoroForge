"""capacity_constraints_wire — the fourth wire-pass primitive."""
from __future__ import annotations

import copy

import pytest

from services.capacity_constraints_wire import (
    is_capacity_constraints_enabled,
    wire_capacity_constraints,
)


def _wf(steps):
    return {
        "workflows": [{"name": "wf1", "steps": steps}],
    }


# ── no-op paths ────────────────────────────────────────────────

def test_no_declaration_is_no_op():
    plan = {"entities": [{"name": "X"}], "workflows": []}
    assert wire_capacity_constraints(plan) == plan


def test_none_plan_returns_verbatim():
    assert wire_capacity_constraints(None) is None


def test_malformed_entries_dropped():
    plan = {
        "capacity_constraints": [
            "not a dict",
            {"entity": ""},                           # empty entity
            {"entity": "X"},                          # missing scope_field
            {"entity": "X", "scope_field": ""},       # empty scope_field
            {"entity": "X", "scope_field": "s"},      # missing limit
            {"entity": "X", "scope_field": "s", "limit": 0},   # non-positive
            {"entity": "X", "scope_field": "s", "limit": -3},
            # valid — should get materialized
            {"entity": "X", "scope_field": "s", "limit": 5},
        ],
        **_wf([
            {"id": "t", "type": "trigger"},
            {"id": "i", "type": "db_insert", "entity": "X"},
            {"id": "e", "type": "end"},
        ]),
    }
    result = wire_capacity_constraints(plan)
    ids = [s["id"] for s in result["workflows"][0]["steps"]]
    assert "capacity_check_X" in ids


# ── capacity_check step injection ──────────────────────────────

def test_capacity_check_inserted_before_tracked_insert():
    plan = {
        "capacity_constraints": [
            {"entity": "Application",
             "scope_field": "recruitment_drive_id",
             "limit": 100},
        ],
        **_wf([
            {"id": "t", "type": "trigger", "next": "i"},
            {"id": "i", "type": "db_insert", "entity": "Application",
             "next": "e"},
            {"id": "e", "type": "end"},
        ]),
    }
    result = wire_capacity_constraints(plan)
    steps = result["workflows"][0]["steps"]
    ids = [s["id"] for s in steps]
    assert "capacity_check_Application" in ids
    assert ids.index("capacity_check_Application") < ids.index("i")


def test_capacity_check_carries_declaration_config():
    plan = {
        "capacity_constraints": [
            {"entity": "X", "scope_field": "slot_time",
             "limit": 1, "message": "Slot is taken"},
        ],
        **_wf([
            {"id": "t", "type": "trigger", "next": "i"},
            {"id": "i", "type": "db_insert", "entity": "X"},
            {"id": "e", "type": "end"},
        ]),
    }
    result = wire_capacity_constraints(plan)
    chk = next(s for s in result["workflows"][0]["steps"]
               if s["id"] == "capacity_check_X")
    assert chk["type"] == "capacity_check"
    assert chk["config"]["scope_field"] == "slot_time"
    assert chk["config"]["limit"] == 1
    assert chk["config"]["message"] == "Slot is taken"


def test_capacity_check_wires_pass_and_fail_targets():
    plan = {
        "capacity_constraints": [
            {"entity": "X", "scope_field": "s", "limit": 5},
        ],
        **_wf([
            {"id": "t", "type": "trigger", "next": "i"},
            {"id": "i", "type": "db_insert", "entity": "X", "next": "e"},
            {"id": "e", "type": "end"},
        ]),
    }
    result = wire_capacity_constraints(plan)
    chk = next(s for s in result["workflows"][0]["steps"]
               if s["id"] == "capacity_check_X")
    assert chk["on_pass"] == "i"     # proceed to original insert
    assert chk["on_fail"] == "e"     # short-circuit to end
    # predecessor re-linked
    trig = next(s for s in result["workflows"][0]["steps"] if s["id"] == "t")
    assert trig["next"] == "capacity_check_X"


def test_untracked_entity_not_wrapped():
    plan = {
        "capacity_constraints": [
            {"entity": "X", "scope_field": "s", "limit": 5},
        ],
        **_wf([
            {"id": "t", "type": "trigger"},
            {"id": "i", "type": "db_insert", "entity": "Y"},
            {"id": "e", "type": "end"},
        ]),
    }
    result = wire_capacity_constraints(plan)
    ids = [s["id"] for s in result["workflows"][0]["steps"]]
    assert not any(i.startswith("capacity_check_") for i in ids)


def test_missing_end_step_skipped_defensively():
    plan = {
        "capacity_constraints": [
            {"entity": "X", "scope_field": "s", "limit": 5},
        ],
        **_wf([
            {"id": "t", "type": "trigger"},
            {"id": "i", "type": "db_insert", "entity": "X"},
        ]),
    }
    result = wire_capacity_constraints(plan)
    ids = [s["id"] for s in result["workflows"][0]["steps"]]
    assert not any(i.startswith("capacity_check_") for i in ids)


# ── idempotency + immutability ─────────────────────────────────

def test_wire_is_idempotent():
    plan = {
        "capacity_constraints": [
            {"entity": "X", "scope_field": "s", "limit": 5},
        ],
        **_wf([
            {"id": "t", "type": "trigger", "next": "i"},
            {"id": "i", "type": "db_insert", "entity": "X"},
            {"id": "e", "type": "end"},
        ]),
    }
    once = wire_capacity_constraints(plan)
    twice = wire_capacity_constraints(once)
    assert once == twice


def test_input_not_mutated():
    plan = {
        "capacity_constraints": [
            {"entity": "X", "scope_field": "s", "limit": 5},
        ],
        **_wf([
            {"id": "t", "type": "trigger"},
            {"id": "i", "type": "db_insert", "entity": "X"},
            {"id": "e", "type": "end"},
        ]),
    }
    snap = copy.deepcopy(plan)
    wire_capacity_constraints(plan)
    assert plan == snap


# ── env gate ───────────────────────────────────────────────────

def test_env_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_CAPACITY_CONSTRAINTS", raising=False)
    assert is_capacity_constraints_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_env_gate_truthy(monkeypatch, val):
    monkeypatch.setenv("FORGE_CAPACITY_CONSTRAINTS", val)
    assert is_capacity_constraints_enabled() is True

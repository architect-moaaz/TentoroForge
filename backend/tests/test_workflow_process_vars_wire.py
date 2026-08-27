"""Tests for the plan-wire that backfills workflow processVariables."""

from __future__ import annotations

import os

import pytest

from services.workflow_process_vars_wire import (
    is_workflow_process_vars_enabled,
    wire_workflow_process_variables,
)


def _step(sid: str, cfg: dict, stype: str = "action") -> dict:
    return {"id": sid, "type": stype, "config": cfg}


def test_default_gate_is_on(monkeypatch):
    monkeypatch.delenv("FORGE_WF_PROCESS_VARS_WIRE", raising=False)
    assert is_workflow_process_vars_enabled() is True


def test_gate_off_when_env_says_off(monkeypatch):
    for val in ("off", "0", "false", "no", "OFF"):
        monkeypatch.setenv("FORGE_WF_PROCESS_VARS_WIRE", val)
        assert is_workflow_process_vars_enabled() is False


def test_non_dict_plan_passes_through():
    assert wire_workflow_process_variables("banana") == "banana"


def test_plan_with_no_workflows_unchanged():
    plan = {"pages": []}
    out = wire_workflow_process_variables(plan)
    assert out == plan


def test_planner_declared_vars_are_preserved():
    plan = {"workflows": [{
        "name": "Approve",
        "processVariables": [{"name": "orderId", "type": "uuid", "required": True}],
        "steps": [],
    }]}
    out = wire_workflow_process_variables(plan)
    pv = out["workflows"][0]["processVariables"]
    assert pv == [{"name": "orderId", "type": "uuid", "required": True}]


def test_set_variable_step_backfills_missing_var():
    plan = {"workflows": [{
        "name": "IncrementRetry",
        # Planner forgot processVariables.
        "steps": [
            _step("s1", {"actionType": "set_variable",
                         "variableName": "retryCount", "variableValue": 0}),
        ],
    }]}
    out = wire_workflow_process_variables(plan)
    pv = out["workflows"][0]["processVariables"]
    names = [e["name"] for e in pv]
    assert "retryCount" in names
    entry = next(e for e in pv if e["name"] == "retryCount")
    assert entry["type"] == "number"
    # No `source` breadcrumb ends up on disk.
    assert "source" not in entry


def test_planner_wins_over_derived():
    plan = {"workflows": [{
        "name": "W",
        "processVariables": [{"name": "shared", "type": "uuid", "description": "the row"}],
        "steps": [
            _step("s1", {"actionType": "set_variable",
                         "variableName": "shared", "variableValue": 42}),
        ],
    }]}
    out = wire_workflow_process_variables(plan)
    pv = out["workflows"][0]["processVariables"]
    assert len(pv) == 1
    assert pv[0]["type"] == "uuid"                # planner's, not the derived "number"
    assert pv[0]["description"] == "the row"


def test_promoted_output_backfills():
    plan = {"workflows": [{
        "name": "CreateOrder",
        "steps": [
            _step("create", {
                "actionType": "db_insert",
                "outputMappings": [{"output": "inserted.id", "processVar": "createdOrderId"}],
            }),
        ],
    }]}
    out = wire_workflow_process_variables(plan)
    pv = out["workflows"][0]["processVariables"]
    assert [e["name"] for e in pv] == ["createdOrderId"]


def test_idempotent_running_twice_yields_same_list():
    plan = {"workflows": [{
        "name": "W",
        "steps": [
            _step("s", {"actionType": "set_variable",
                        "variableName": "count", "variableValue": 1}),
        ],
    }]}
    once = wire_workflow_process_variables(plan)
    twice = wire_workflow_process_variables(once)
    assert once["workflows"][0]["processVariables"] == twice["workflows"][0]["processVariables"]


def test_malformed_workflow_left_alone():
    plan = {"workflows": ["banana", {"name": "ok",
                                     "steps": [_step("s", {"actionType": "set_variable",
                                                           "variableName": "x", "variableValue": 1})]}]}
    out = wire_workflow_process_variables(plan)
    # The bogus string is preserved verbatim; the real one gets backfilled.
    assert out["workflows"][0] == "banana"
    assert out["workflows"][1]["processVariables"][0]["name"] == "x"


def test_workflow_with_no_scratchpad_left_untouched():
    """A pure-CRUD workflow with no set_variable + no promoted output stays as-is."""
    plan = {"workflows": [{
        "name": "CreateOnly",
        "steps": [_step("insert", {"actionType": "db_insert", "table": "orders"})],
    }]}
    out = wire_workflow_process_variables(plan)
    # No processVariables field added — nothing to declare.
    assert "processVariables" not in out["workflows"][0]

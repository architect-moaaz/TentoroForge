"""Tests for _sanitize_workflow_connectivity — deterministic backfill of
flow connectivity (next/end) for pure-linear planner workflows that omit it.

Contract:
- Linear workflow missing next/branches → sequential next chain + one end.
- Workflow already carrying connectivity → untouched.
- Branching workflow (gateway/condition/decision) → untouched (unsafe to infer).
- Idempotent, pure, deterministic.
"""
import copy

from agents.planner import _sanitize_workflow_connectivity


def test_linear_workflow_gets_sequential_next():
    plan = {
        "workflows": [
            {
                "name": "create_thing",
                "steps": [
                    {"id": "a", "type": "action", "config": {"x": 1}},
                    {"id": "b", "type": "action", "config": {"x": 2}},
                    {"id": "c", "type": "action", "config": {"x": 3}},
                ],
            }
        ]
    }
    out = _sanitize_workflow_connectivity(plan)
    steps = out["workflows"][0]["steps"]
    by_id = {s["id"]: s for s in steps}
    # An end step must now exist.
    end_ids = [s["id"] for s in steps if s.get("type") in ("end", "end_event")]
    assert len(end_ids) == 1
    end_id = end_ids[0]
    assert by_id["a"]["next"] == "b"
    assert by_id["b"]["next"] == "c"
    assert by_id["c"]["next"] == end_id


def test_already_connected_untouched():
    plan = {
        "workflows": [
            {
                "name": "wf",
                "steps": [
                    {"id": "a", "type": "action", "config": {}, "next": "b"},
                    {"id": "b", "type": "end"},
                ],
            }
        ]
    }
    before = copy.deepcopy(plan)
    out = _sanitize_workflow_connectivity(plan)
    assert out == before


def test_branching_workflow_left_alone():
    plan = {
        "workflows": [
            {
                "name": "approval",
                "steps": [
                    {"id": "a", "type": "action", "config": {}},
                    {"id": "gate", "type": "exclusive_gateway", "config": {}},
                    {"id": "c", "type": "action", "config": {}},
                ],
            }
        ]
    }
    before = copy.deepcopy(plan)
    out = _sanitize_workflow_connectivity(plan)
    # Branch intent can't be inferred deterministically → no backfill.
    assert out == before


def test_idempotent():
    plan = {
        "workflows": [
            {
                "name": "wf",
                "steps": [
                    {"id": "a", "type": "action", "config": {}},
                    {"id": "b", "type": "action", "config": {}},
                ],
            }
        ]
    }
    once = _sanitize_workflow_connectivity(copy.deepcopy(plan))
    twice = _sanitize_workflow_connectivity(copy.deepcopy(once))
    assert twice == once


def test_end_not_duplicated():
    plan = {
        "workflows": [
            {
                "name": "wf",
                "steps": [
                    {"id": "a", "type": "action", "config": {}},
                    {"id": "b", "type": "action", "config": {}},
                    {"id": "end", "type": "end"},
                ],
            }
        ]
    }
    out = _sanitize_workflow_connectivity(plan)
    steps = out["workflows"][0]["steps"]
    end_ids = [s["id"] for s in steps if s.get("type") in ("end", "end_event")]
    assert end_ids == ["end"]  # exactly one, not duplicated
    by_id = {s["id"]: s for s in steps}
    assert by_id["a"]["next"] == "b"
    assert by_id["b"]["next"] == "end"

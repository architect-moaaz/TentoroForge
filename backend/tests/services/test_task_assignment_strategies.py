"""Slice E T3 — 5 advertised assignment strategies.

The runtime already implements ``round_robin`` and ``load_balanced``
inside _resolveAssignee (workflows/index.ts). The plan advertises a
larger menu — creator, entity_field, reporting_manager,
department_head, group — none of which have code. This module is the
authoritative helper; the TS side calls into an equivalent resolver.

The helper is pure — takes a strategy config + a context object and
returns either an assignee id/list or a query-descriptor the TS
runtime can execute against the database. Kept in Python so the
planner + guards + docs stay in sync with the runtime.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────
# creator — the person who kicked off the workflow
# ─────────────────────────────────────────────────────────────────────

def test_creator_returns_workflow_started_by():
    from services.task_assignment_strategies import resolve_assignee

    ctx = {"workflow": {"startedBy": "user-abc"}}
    out = resolve_assignee({"strategy": "creator"}, ctx)
    assert out == {"kind": "user", "id": "user-abc"}


def test_creator_falls_back_to_ctx_user_id():
    """When startedBy is missing, fall back to the acting user."""
    from services.task_assignment_strategies import resolve_assignee

    ctx = {"workflow": {}, "user": {"id": "user-xyz"}}
    out = resolve_assignee({"strategy": "creator"}, ctx)
    assert out == {"kind": "user", "id": "user-xyz"}


def test_creator_returns_none_when_no_user_available():
    from services.task_assignment_strategies import resolve_assignee

    assert resolve_assignee({"strategy": "creator"}, {}) is None


# ─────────────────────────────────────────────────────────────────────
# entity_field — a foreign-key column on the entity row (e.g. Candidate.assignedRecruiterId)
# ─────────────────────────────────────────────────────────────────────

def test_entity_field_reads_from_entity():
    from services.task_assignment_strategies import resolve_assignee

    ctx = {"entity": {"assignedRecruiterId": "user-999", "id": "c-1"}}
    out = resolve_assignee(
        {"strategy": "entity_field", "field": "assignedRecruiterId"},
        ctx,
    )
    assert out == {"kind": "user", "id": "user-999"}


def test_entity_field_missing_field_returns_none():
    from services.task_assignment_strategies import resolve_assignee

    ctx = {"entity": {"id": "c-1"}}
    out = resolve_assignee(
        {"strategy": "entity_field", "field": "assignedRecruiterId"},
        ctx,
    )
    assert out is None


def test_entity_field_without_field_key_returns_none():
    """A misconfigured strategy (no `field`) is not a crash — return None."""
    from services.task_assignment_strategies import resolve_assignee

    ctx = {"entity": {"assignedRecruiterId": "user-999"}}
    assert resolve_assignee({"strategy": "entity_field"}, ctx) is None


# ─────────────────────────────────────────────────────────────────────
# reporting_manager — walk one level up the org chart via users.managerId
# ─────────────────────────────────────────────────────────────────────

def test_reporting_manager_returns_query_descriptor():
    from services.task_assignment_strategies import resolve_assignee

    ctx = {"user": {"id": "user-abc"}}
    out = resolve_assignee({"strategy": "reporting_manager"}, ctx)
    # DB lookup — runtime executes the descriptor.
    assert out == {
        "kind": "query",
        "sql": "SELECT manager_id AS id FROM users WHERE id = $1",
        "params": ["user-abc"],
    }


def test_reporting_manager_uses_workflow_started_by_when_no_user():
    from services.task_assignment_strategies import resolve_assignee

    ctx = {"workflow": {"startedBy": "user-abc"}}
    out = resolve_assignee({"strategy": "reporting_manager"}, ctx)
    assert out["params"] == ["user-abc"]


def test_reporting_manager_returns_none_when_no_anchor_user():
    from services.task_assignment_strategies import resolve_assignee

    assert resolve_assignee({"strategy": "reporting_manager"}, {}) is None


# ─────────────────────────────────────────────────────────────────────
# department_head — everyone whose role matches, filtered by department
# ─────────────────────────────────────────────────────────────────────

def test_department_head_query_descriptor():
    from services.task_assignment_strategies import resolve_assignee

    ctx = {"entity": {"departmentId": "d-42"}}
    out = resolve_assignee(
        {"strategy": "department_head", "role": "head"},
        ctx,
    )
    assert out == {
        "kind": "query",
        "sql": "SELECT id FROM users WHERE role = $1 AND department_id = $2 LIMIT 1",
        "params": ["head", "d-42"],
    }


def test_department_head_missing_department_returns_none():
    from services.task_assignment_strategies import resolve_assignee

    assert (
        resolve_assignee(
            {"strategy": "department_head", "role": "head"},
            {"entity": {}},
        )
        is None
    )


# ─────────────────────────────────────────────────────────────────────
# group — resolve every user in a named group
# ─────────────────────────────────────────────────────────────────────

def test_group_returns_query_descriptor_for_named_group():
    from services.task_assignment_strategies import resolve_assignee

    out = resolve_assignee({"strategy": "group", "group": "approvers"}, {})
    assert out == {
        "kind": "query",
        "sql": "SELECT user_id AS id FROM user_groups WHERE group_name = $1",
        "params": ["approvers"],
        "multi": True,
    }


def test_group_without_name_returns_none():
    from services.task_assignment_strategies import resolve_assignee

    assert resolve_assignee({"strategy": "group"}, {}) is None


# ─────────────────────────────────────────────────────────────────────
# Backwards compatibility with existing static / role / round_robin /
# load_balanced — the helper must not break them if called.
# ─────────────────────────────────────────────────────────────────────

def test_static_assignee_returns_user():
    from services.task_assignment_strategies import resolve_assignee

    out = resolve_assignee({"strategy": "static", "assignee": "user-42"}, {})
    assert out == {"kind": "user", "id": "user-42"}


def test_role_strategy_returns_role_descriptor():
    from services.task_assignment_strategies import resolve_assignee

    out = resolve_assignee({"strategy": "role", "role": "recruiter"}, {})
    assert out == {"kind": "role", "role": "recruiter"}


def test_unknown_strategy_returns_none():
    from services.task_assignment_strategies import resolve_assignee

    assert resolve_assignee({"strategy": "warp-drive"}, {}) is None


def test_strategy_registry_exposes_all_advertised_names():
    """The runtime and planner both need to know which names are valid.
    Exporting a KNOWN_STRATEGIES set keeps them from drifting."""
    from services.task_assignment_strategies import KNOWN_STRATEGIES

    for name in (
        "static",
        "role",
        "round_robin",
        "load_balanced",
        "creator",
        "entity_field",
        "reporting_manager",
        "department_head",
        "group",
    ):
        assert name in KNOWN_STRATEGIES


# ─────────────────────────────────────────────────────────────────────
# TS runtime handshake: the runtime's _resolveAssignee must know the
# new strategies so it can execute the descriptors.
# ─────────────────────────────────────────────────────────────────────

def test_runtime_workflows_index_ts_handles_all_strategies():
    from pathlib import Path

    text = (
        Path(__file__).parent.parent.parent
        / "templates" / "runtime" / "workflows" / "index.ts"
    ).read_text(encoding="utf-8")
    for name in (
        "creator",
        "entity_field",
        "reporting_manager",
        "department_head",
        "group",
    ):
        assert name in text, (
            f"runtime workflow dispatcher does not mention strategy {name!r}"
        )

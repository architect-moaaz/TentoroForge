"""Tests for Spec D Wave 3 (D3-B) — custom_sql strategy + plan-authored
SQL overrides on the deprecated invented-column strategies.
"""
from __future__ import annotations

from services.task_assignment_strategies import (
    KNOWN_STRATEGIES,
    resolve_assignee,
)


class TestCustomSqlStrategy:
    def test_custom_sql_included_in_known_strategies(self):
        assert "custom_sql" in KNOWN_STRATEGIES

    def test_custom_sql_returns_query_verbatim(self):
        cfg = {
            "strategy": "custom_sql",
            "sql": "SELECT id FROM users WHERE id = $1",
            "params": ["u_1"],
            "multi": False,
        }
        r = resolve_assignee(cfg, ctx={})
        assert r == {
            "kind": "query",
            "sql": "SELECT id FROM users WHERE id = $1",
            "params": ["u_1"],
            "multi": False,
        }

    def test_custom_sql_multi_default_false(self):
        r = resolve_assignee(
            {"strategy": "custom_sql", "sql": "SELECT id FROM users"},
            ctx={},
        )
        assert r["multi"] is False
        assert r["params"] == []

    def test_custom_sql_multi_true_returned(self):
        r = resolve_assignee(
            {"strategy": "custom_sql",
             "sql": "SELECT id FROM users WHERE role = $1",
             "params": ["admin"],
             "multi": True},
            ctx={},
        )
        assert r["multi"] is True

    def test_custom_sql_missing_returns_none(self):
        assert resolve_assignee({"strategy": "custom_sql"}, ctx={}) is None
        assert resolve_assignee({"strategy": "custom_sql", "sql": ""}, ctx={}) is None
        assert resolve_assignee({"strategy": "custom_sql", "sql": "   "}, ctx={}) is None


class TestInventedStrategyOverrides:
    """Deprecated invented-SQL strategies now honor a plan-authored
    {sql, params, multi} override. When the override is absent, they
    keep the legacy invented-SQL for backward compat."""

    def test_reporting_manager_uses_override_sql(self):
        r = resolve_assignee(
            {"strategy": "reporting_manager",
             "sql": "SELECT lead_id AS id FROM assignments WHERE user_id = $1",
             "params": ["u_1"]},
            ctx={"user": {"id": "u_1"}},
        )
        assert r["sql"] == "SELECT lead_id AS id FROM assignments WHERE user_id = $1"
        assert r["params"] == ["u_1"]

    def test_reporting_manager_falls_back_to_invented(self):
        # Without override, the legacy invented-SQL still fires (backward compat).
        r = resolve_assignee(
            {"strategy": "reporting_manager"},
            ctx={"user": {"id": "u_1"}},
        )
        assert "manager_id" in r["sql"]

    def test_department_head_uses_override_sql(self):
        r = resolve_assignee(
            {"strategy": "department_head",
             "sql": "SELECT owner_id AS id FROM teams WHERE code = $1",
             "params": ["ENG"]},
            ctx={},
        )
        assert r["sql"] == "SELECT owner_id AS id FROM teams WHERE code = $1"

    def test_group_uses_override_sql_with_multi(self):
        r = resolve_assignee(
            {"strategy": "group",
             "sql": "SELECT member_id AS id FROM squads WHERE name = $1",
             "params": ["backend"],
             "multi": True},
            ctx={},
        )
        assert r["sql"].startswith("SELECT member_id")
        assert r["multi"] is True

    def test_no_override_keeps_original_behavior(self):
        # Regression: no override, no ctx.entity → legacy path returns None
        # for department_head (needs departmentId on entity).
        r = resolve_assignee(
            {"strategy": "department_head", "role": "manager"},
            ctx={},
        )
        assert r is None

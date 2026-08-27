"""Slice E T3 — resolve a workflow ``user_task`` node's assignee from
its declared strategy.

Pure. Takes ``(config, ctx) -> dict | None``. The runtime side of the
same logic lives in ``backend/templates/runtime/workflows/index.ts``
inside ``_resolveAssignee``; the two must agree on strategy names +
descriptor shapes.

Return-value taxonomy:
    ``{"kind": "user",  "id":   str}``      — a specific user id.
    ``{"kind": "role",  "role": str}``      — every user with this role.
    ``{"kind": "query", "sql": str,
       "params": list, "multi": bool}``     — the runtime executes the
                                              SQL against its DB. ``multi``
                                              is True when the query is
                                              expected to return more
                                              than one row (pool → pick
                                              one via round-robin / etc.).
    ``None``                                — misconfigured or missing
                                              context; the runtime should
                                              fall back to whatever it
                                              already does (usually
                                              ``"admin"``).

Strategies:
    ``static``            — direct assignee id from ``config.assignee``.
    ``role``              — pass through ``config.role``.
    ``round_robin``       — runtime-side only, uses ``config.assigneePool``.
    ``load_balanced``     — runtime-side only, uses ``config.assigneePool``.
    ``creator``           — the workflow's starter (``ctx.workflow.startedBy``,
                            falling back to ``ctx.user.id``).
    ``entity_field``      — a FK column on the entity row (e.g.
                            ``Candidate.assignedRecruiterId``).
    ``reporting_manager`` — one level up the org chart via
                            ``users.manager_id``.
    ``department_head``   — the user with role ``config.role`` in the
                            same department as the entity.
    ``group``             — every member of a named group.
"""
from __future__ import annotations

from typing import Any


KNOWN_STRATEGIES: frozenset[str] = frozenset(
    {
        "static",
        "role",
        "round_robin",
        "load_balanced",
        "creator",
        "entity_field",
        "reporting_manager",
        "department_head",
        "group",
        # Spec D Wave 3 — LLM-authored SQL against real registry columns.
        # Escape hatch replacing the invented-SQL branches below (which
        # reference users.manager_id / department_id / user_groups tables
        # that a generated app may not have). Planner emits:
        #   {"strategy": "custom_sql", "sql": "...", "params": [...],
        #    "multi": true|false}
        # SQL is authored against the real entity/user registry, not
        # invented columns.
        "custom_sql",
    }
)


def _first_user_id(ctx: dict[str, Any]) -> str | None:
    """The anchor user for creator / reporting_manager — prefer the
    workflow's starter, fall back to the acting user."""
    started_by = (ctx.get("workflow") or {}).get("startedBy")
    if isinstance(started_by, str) and started_by:
        return started_by
    uid = (ctx.get("user") or {}).get("id")
    return uid if isinstance(uid, str) and uid else None


def resolve_assignee(
    config: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any] | None:
    """Compute the assignee descriptor for a single user_task from its
    strategy + the workflow context. See module docstring for shapes.
    Never raises."""
    if not isinstance(config, dict):
        return None
    strategy = config.get("strategy")
    if not isinstance(strategy, str):
        return None

    if strategy == "static":
        aid = config.get("assignee")
        return {"kind": "user", "id": aid} if isinstance(aid, str) and aid else None

    if strategy == "role":
        role = config.get("role")
        return {"kind": "role", "role": role} if isinstance(role, str) and role else None

    if strategy in ("round_robin", "load_balanced"):
        # Pure-Python side has nothing to add — the runtime resolves the
        # pool from `assigneePool` / `role` against live user counts.
        # We echo the strategy so the caller can pass it through.
        pool = config.get("assigneePool")
        role = config.get("role")
        return {
            "kind": "runtime",
            "strategy": strategy,
            "pool": pool if isinstance(pool, list) else [],
            "role": role if isinstance(role, str) else None,
        }

    if strategy == "creator":
        uid = _first_user_id(ctx)
        return {"kind": "user", "id": uid} if uid else None

    if strategy == "entity_field":
        field = config.get("field")
        if not (isinstance(field, str) and field):
            return None
        entity = ctx.get("entity") or {}
        val = entity.get(field)
        return {"kind": "user", "id": val} if isinstance(val, str) and val else None

    # Spec D Wave 3 — custom_sql: LLM-authored SQL executed verbatim
    # against the runtime DB. Preferred entry point going forward;
    # keeps the runtime free of invented column knowledge.
    if strategy == "custom_sql":
        sql = config.get("sql")
        if not (isinstance(sql, str) and sql.strip()):
            return None
        params = config.get("params")
        if not isinstance(params, list):
            params = []
        return {
            "kind": "query",
            "sql": sql,
            "params": list(params),
            "multi": bool(config.get("multi", False)),
        }

    # ─── Deprecated: invented-SQL branches ─────────────────────────
    # These strategies reference columns (users.manager_id,
    # users.department_id, user_groups.group_name) that a generated
    # app may not have. Kept for backward compat; new plans should
    # emit strategy="custom_sql" with SQL authored against the real
    # registry. Planner-side prefer-custom_sql guidance is expected
    # in a follow-up prompt-hardening commit. Each branch honors an
    # optional {sql, params, multi} override so a plan CAN keep the
    # legacy strategy name AND pin the real SQL.
    if strategy == "reporting_manager":
        # Plan-authored override wins.
        sql_over = config.get("sql")
        if isinstance(sql_over, str) and sql_over.strip():
            return {"kind": "query", "sql": sql_over,
                    "params": list(config.get("params") or []),
                    "multi": bool(config.get("multi", False))}
        anchor = _first_user_id(ctx)
        if not anchor:
            return None
        return {
            "kind": "query",
            "sql": "SELECT manager_id AS id FROM users WHERE id = $1",
            "params": [anchor],
        }

    if strategy == "department_head":
        sql_over = config.get("sql")
        if isinstance(sql_over, str) and sql_over.strip():
            return {"kind": "query", "sql": sql_over,
                    "params": list(config.get("params") or []),
                    "multi": bool(config.get("multi", False))}
        role = config.get("role")
        if not (isinstance(role, str) and role):
            return None
        dept = (ctx.get("entity") or {}).get("departmentId")
        if not (isinstance(dept, str) and dept):
            return None
        return {
            "kind": "query",
            "sql": "SELECT id FROM users WHERE role = $1 AND department_id = $2 LIMIT 1",
            "params": [role, dept],
        }

    if strategy == "group":
        sql_over = config.get("sql")
        if isinstance(sql_over, str) and sql_over.strip():
            return {"kind": "query", "sql": sql_over,
                    "params": list(config.get("params") or []),
                    "multi": bool(config.get("multi", True))}
        group = config.get("group")
        if not (isinstance(group, str) and group):
            return None
        return {
            "kind": "query",
            "sql": "SELECT user_id AS id FROM user_groups WHERE group_name = $1",
            "params": [group],
            "multi": True,
        }

    return None

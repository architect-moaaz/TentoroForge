"""plan_completeness_validator — deterministic gate that catches plans
missing the fields Slices 1–5 need to read."""
from __future__ import annotations

from services.plan_completeness_validator import (
    Violation,
    format_revise_gaps,
    validate_plan_completeness,
)


# ────────────────────────────────────────────────────────────
# Rule: enum_values on restricted-vocabulary columns
# ────────────────────────────────────────────────────────────

def test_enum_missing_when_workflow_writes_literals():
    """The exact Bug 2 shape: workflow sets status to string literals but
    the entity's status column has no enum_values. Validator flags it."""
    plan = {
        "entities": {
            "Application": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "status", "type": "varchar"},   # NO enum_values
            ]},
        },
        "workflows": [
            {"name": "Shortlist", "nodes": [
                {"config": {"values": {"status": "shortlisted"}}},
            ]},
            {"name": "Reject", "nodes": [
                {"config": {"values": {"status": "rejected"}}},
            ]},
        ],
    }
    vs = validate_plan_completeness(plan)
    enum_vs = [v for v in vs if v.rule == "missing_enum_values"]
    assert len(enum_vs) == 1
    v = enum_vs[0]
    assert v.entity == "Application" and v.field == "status"
    assert "shortlisted" in v.msg and "rejected" in v.msg


def test_enum_partial_declaration_still_flagged():
    """Enum_values declared but missing SOME workflow literals is still
    a violation — every literal must be covered."""
    plan = {
        "entities": {
            "Application": {"fields": [
                {"name": "status", "type": "varchar",
                 "enum_values": ["open", "shortlisted"]},   # missing "rejected"
            ]},
        },
        "workflows": [
            {"name": "Shortlist", "nodes": [
                {"config": {"values": {"status": "shortlisted"}}},
            ]},
            {"name": "Reject", "nodes": [
                {"config": {"values": {"status": "rejected"}}},
            ]},
        ],
    }
    enum_vs = [v for v in validate_plan_completeness(plan)
               if v.rule == "missing_enum_values"]
    assert len(enum_vs) == 1
    assert "rejected" in enum_vs[0].msg


def test_enum_complete_declaration_passes():
    plan = {
        "entities": {
            "Application": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "status", "type": "varchar",
                 "enum_values": ["open", "shortlisted", "rejected"]},
            ]},
        },
        "workflows": [
            {"name": "S", "nodes": [{"config": {"values": {"status": "shortlisted"}}}]},
            {"name": "R", "nodes": [{"config": {"values": {"status": "rejected"}}}]},
        ],
    }
    assert not [v for v in validate_plan_completeness(plan)
                if v.rule == "missing_enum_values"]


def test_enum_ignores_binding_references():
    """A workflow that writes `{{userId}}` (a template binding, not a
    literal string) does NOT create an enum requirement."""
    plan = {
        "entities": {
            "Task": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "ownerId", "type": "uuid"},
            ]},
        },
        "workflows": [
            {"name": "Assign", "nodes": [
                {"config": {"values": {"ownerId": "{{userId}}"}}},
            ]},
        ],
    }
    assert not [v for v in validate_plan_completeness(plan)
                if v.rule == "missing_enum_values"]


# ────────────────────────────────────────────────────────────
# Rule: fk on non-primary uuid columns
# ────────────────────────────────────────────────────────────

def test_fk_missing_flagged():
    plan = {
        "entities": {
            "Application": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "candidateId", "type": "uuid"},   # no fk
            ]},
        },
    }
    vs = [v for v in validate_plan_completeness(plan) if v.rule == "missing_fk"]
    assert len(vs) == 1
    assert vs[0].field == "candidateId"


def test_fk_declared_passes():
    plan = {
        "entities": {
            "Application": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "candidateId", "type": "uuid",
                 "fk": {"table": "users", "column": "id"}},
            ]},
        },
    }
    assert not [v for v in validate_plan_completeness(plan) if v.rule == "missing_fk"]


def test_fk_pk_uuid_not_flagged():
    """A uuid PK doesn't need an fk — it IS the primary key."""
    plan = {
        "entities": {
            "Application": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
            ]},
        },
    }
    assert not [v for v in validate_plan_completeness(plan) if v.rule == "missing_fk"]


# ────────────────────────────────────────────────────────────
# Rule: inputs on user-triggered workflows
# ────────────────────────────────────────────────────────────

def test_manual_workflow_missing_inputs_flagged():
    plan = {
        "workflows": [
            {"name": "ScheduleInterview", "trigger": "manual on Interview"},
        ],
    }
    vs = [v for v in validate_plan_completeness(plan)
          if v.rule == "missing_workflow_inputs"]
    assert len(vs) == 1
    assert vs[0].workflow == "ScheduleInterview"


def test_manual_workflow_with_inputs_passes():
    plan = {
        "workflows": [
            {"name": "ScheduleInterview", "trigger": "manual",
             "inputs": ["interviewer", "time", "location"]},
        ],
    }
    assert not [v for v in validate_plan_completeness(plan)
                if v.rule == "missing_workflow_inputs"]


def test_scheduled_workflow_not_flagged():
    """A scheduled/cron workflow doesn't need trigger inputs."""
    plan = {
        "workflows": [
            {"name": "DailyReminder", "trigger": "schedule"},
        ],
    }
    assert not [v for v in validate_plan_completeness(plan)
                if v.rule == "missing_workflow_inputs"]


def test_manual_workflow_empty_inputs_flagged():
    """`inputs: []` on a manual workflow is treated as missing."""
    plan = {
        "workflows": [
            {"name": "X", "trigger": "manual", "inputs": []},
        ],
    }
    assert [v for v in validate_plan_completeness(plan)
            if v.rule == "missing_workflow_inputs"]


# ────────────────────────────────────────────────────────────
# Rule: not_null declared on every field
# ────────────────────────────────────────────────────────────

def test_not_null_missing_flagged():
    plan = {
        "entities": {
            "User": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "email", "type": "varchar"},   # no not_null
            ]},
        },
    }
    vs = [v for v in validate_plan_completeness(plan) if v.rule == "missing_not_null"]
    assert len(vs) == 1
    assert vs[0].field == "email"


def test_not_null_via_nullable_alias_passes():
    """Plans may use `nullable: false` instead of `not_null: true`."""
    plan = {
        "entities": {
            "User": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "email", "type": "varchar", "nullable": False},
            ]},
        },
    }
    assert not [v for v in validate_plan_completeness(plan)
                if v.rule == "missing_not_null"]


def test_not_null_pk_not_flagged():
    plan = {
        "entities": {
            "User": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
            ]},
        },
    }
    assert not [v for v in validate_plan_completeness(plan)
                if v.rule == "missing_not_null"]


# ────────────────────────────────────────────────────────────
# Formatter
# ────────────────────────────────────────────────────────────

def test_revise_prompt_uses_planner_contract_keywords():
    """The REVISE MODE regex triggers on 'GAPS TO FIX:' and the
    per-gap '[BLOCKER]/[IMPORTANT]/[NICE]' markers. Formatter must emit
    both so the planner enters revise mode."""
    vs = [Violation(rule="missing_fk", entity="X", field="y", msg="X.y needs fk")]
    txt = format_revise_gaps(vs)
    assert "GAPS TO FIX:" in txt
    assert "[BLOCKER]" in txt
    assert "X.y" in txt
    assert "data_models[X].fields[y]" in txt


def test_revise_prompt_empty_when_no_violations():
    assert format_revise_gaps([]) == ""


# ────────────────────────────────────────────────────────────
# Full plan sanity — complete plan produces zero violations
# ────────────────────────────────────────────────────────────

def test_complete_plan_produces_no_violations():
    """A well-formed plan with every field declared should produce a
    clean bill of health — no false positives."""
    plan = {
        "entities": {
            "User": {"fields": [
                {"name": "id",    "type": "uuid",    "primaryKey": True},
                {"name": "email", "type": "varchar", "not_null": True},
            ]},
            "Application": {"fields": [
                {"name": "id",          "type": "uuid",    "primaryKey": True},
                {"name": "status",      "type": "varchar", "not_null": True,
                 "enum_values": ["open", "shortlisted", "rejected"]},
                {"name": "candidateId", "type": "uuid",    "not_null": True,
                 "fk": {"table": "users", "column": "id"}},
            ]},
        },
        "workflows": [
            {"name": "Shortlist", "trigger": "manual",
             "inputs": ["applicationId"],
             "nodes": [{"config": {"values": {"status": "shortlisted"}}}]},
            {"name": "Reject", "trigger": "manual",
             "inputs": ["applicationId", "reason"],
             "nodes": [{"config": {"values": {"status": "rejected"}}}]},
        ],
    }
    vs = validate_plan_completeness(plan)
    assert vs == [], f"expected no violations; got: {vs}"

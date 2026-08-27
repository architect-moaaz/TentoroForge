"""Tests for Slice-1 plan-completeness rules — the "executable plan" contract.

Each rule catches ONE way an incomplete plan lets downstream stages guess
(and eventually mis-emit or produce dangling references). Together they
make the plan interpretable in exactly one way; the corresponding emitter
strictness in Slice 2 turns "downstream had to guess" into a build error.

Rules added by this slice (validate_plan_completeness picks them up):
    R1. page_data_source_declared    — list pages must name the entity they bind to
    R2. page_actions_declared        — pages must declare their user actions (may be empty)
    R3. action_target_resolves        — every action.target must exist in the plan
    R4. workflow_has_step             — every referenced workflow has at least one step
    R5. entity_has_surface            — every non-internal entity has ≥ 1 page
"""
from __future__ import annotations

import os

import pytest

from services.plan_completeness_validator import (
    PlanNotExecutableError,
    enforce_plan_executability,
    executability_violations,
    is_strict_plan_enabled,
    validate_plan_completeness,
)


# ────────────────────────────────────────────────────────────
# Slice-2 strict-mode gate
# ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_strict_env(monkeypatch):
    monkeypatch.delenv("FORGE_STRICT_PLAN", raising=False)


def test_strict_mode_disabled_by_default():
    assert is_strict_plan_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "on", "yes", "strict", "TRUE"])
def test_strict_mode_enabled_by_env(monkeypatch, val):
    monkeypatch.setenv("FORGE_STRICT_PLAN", val)
    assert is_strict_plan_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "off", "", "no"])
def test_strict_mode_disabled_by_falsy_env(monkeypatch, val):
    monkeypatch.setenv("FORGE_STRICT_PLAN", val)
    assert is_strict_plan_enabled() is False


def test_executability_violations_returns_only_slice1_rules():
    plan = {
        "entities": {"Ghost": {"table": "ghosts", "fields": {"id": {"type": "uuid"}}}},
        "pages": [],
        "workflows": [],
    }
    slice1 = executability_violations(plan)
    # Only Slice-1 rule slugs may appear.
    assert all(v.rule in {
        "page_data_source_declared", "page_actions_declared",
        "action_target_resolves", "workflow_has_step", "entity_has_surface",
    } for v in slice1)
    # At least the entity_has_surface fires (Ghost has no page).
    assert any(v.rule == "entity_has_surface" for v in slice1)


def test_enforce_returns_violations_when_strict_off():
    plan = {
        "entities": {"Ghost": {"table": "ghosts", "fields": {"id": {}}}},
        "pages": [],
        "workflows": [],
    }
    # No env set → returns list, does not raise.
    result = enforce_plan_executability(plan)
    assert any(v.rule == "entity_has_surface" for v in result)


def test_enforce_raises_when_strict_on_and_incomplete(monkeypatch):
    monkeypatch.setenv("FORGE_STRICT_PLAN", "1")
    plan = {
        "entities": {"Ghost": {"table": "ghosts", "fields": {"id": {}}}},
        "pages": [],
        "workflows": [],
    }
    with pytest.raises(PlanNotExecutableError) as ei:
        enforce_plan_executability(plan)
    # Error must carry the violations for the caller to render / retry.
    assert ei.value.violations
    assert any(v.rule == "entity_has_surface" for v in ei.value.violations)


def test_enforce_does_not_raise_on_complete_plan_even_in_strict(monkeypatch):
    monkeypatch.setenv("FORGE_STRICT_PLAN", "1")
    plan = {
        "entities": {
            "Carer": {"table": "carers", "fields": {"id": {"type": "uuid"}}},
        },
        "workflows": [],
        "pages": [
            {
                "id": "carers-list",
                "route": "/carers",
                "archetype": "list",
                "entity": "Carer",
                "dataSource": {"entity": "Carer", "op": "list"},
                "actions": [],
            }
        ],
    }
    result = enforce_plan_executability(plan)
    assert result == []


# ────────────────────────────────────────────────────────────
# R1 — page_data_source_declared
# ────────────────────────────────────────────────────────────


def _plan(**overrides) -> dict:
    base = {
        "entities": {
            "Carer": {"table": "carers", "fields": {"id": {"type": "uuid"}}},
        },
        "pages": [
            {
                "id": "carers-list",
                "route": "/carers",
                "archetype": "list",
                "entity": "Carer",
                "dataSource": {"entity": "Carer", "op": "list"},
                "actions": [],
            }
        ],
        "workflows": [],
    }
    base.update(overrides)
    return base


def test_r1_flags_list_page_missing_dataSource():
    plan = _plan()
    plan["pages"][0].pop("dataSource")
    violations = validate_plan_completeness(plan)
    rules = [v.rule for v in violations]
    assert "page_data_source_declared" in rules


def test_r1_flags_list_page_dataSource_missing_entity():
    plan = _plan()
    plan["pages"][0]["dataSource"] = {"op": "list"}   # no entity
    violations = validate_plan_completeness(plan)
    assert any(v.rule == "page_data_source_declared" for v in violations)


def test_r1_does_not_flag_non_list_pages():
    plan = _plan()
    plan["pages"][0] = {
        "id": "dashboard",
        "route": "/dashboard",
        "archetype": "dashboard",
        "actions": [],
    }
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "page_data_source_declared" for v in violations)


def test_r1_dataSource_entity_must_be_a_planned_entity():
    plan = _plan()
    plan["pages"][0]["dataSource"] = {"entity": "Unknown", "op": "list"}
    violations = validate_plan_completeness(plan)
    assert any(v.rule == "page_data_source_declared" for v in violations)


# ────────────────────────────────────────────────────────────
# R2 — page_actions_declared
# ────────────────────────────────────────────────────────────


def test_r2_flags_page_without_actions_field():
    plan = _plan()
    plan["pages"][0].pop("actions")
    violations = validate_plan_completeness(plan)
    assert any(v.rule == "page_actions_declared" for v in violations)


def test_r2_allows_empty_actions_list():
    plan = _plan()
    plan["pages"][0]["actions"] = []   # explicit "no user actions here"
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "page_actions_declared" for v in violations)


def test_r2_each_action_must_have_kind_and_target():
    plan = _plan()
    plan["pages"][0]["actions"] = [{"label": "Do it"}]  # no kind, no target
    violations = validate_plan_completeness(plan)
    assert any(v.rule == "page_actions_declared" for v in violations)


# ────────────────────────────────────────────────────────────
# R3 — action_target_resolves (this closes the "unattached button" class)
# ────────────────────────────────────────────────────────────


def test_r3_flags_workflow_action_target_not_in_plan():
    plan = _plan()
    plan["pages"][0]["actions"] = [
        {"label": "Create", "kind": "workflow", "target": "CreatePhantom"},
    ]
    violations = validate_plan_completeness(plan)
    assert any(v.rule == "action_target_resolves" for v in violations)


def test_r3_workflow_action_resolves_when_workflow_planned():
    plan = _plan()
    plan["workflows"] = [{"name": "CreateCarer", "steps": [{"actionType": "db_insert"}]}]
    plan["pages"][0]["actions"] = [
        {"label": "Create", "kind": "workflow", "target": "CreateCarer"},
    ]
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "action_target_resolves" for v in violations)


def test_r3_flags_navigate_action_target_not_in_pages():
    plan = _plan()
    plan["pages"][0]["actions"] = [
        {"label": "Details", "kind": "navigate", "target": "/nowhere"},
    ]
    violations = validate_plan_completeness(plan)
    assert any(v.rule == "action_target_resolves" for v in violations)


def test_r3_navigate_action_resolves_to_another_planned_page():
    plan = _plan()
    plan["pages"].append({
        "id": "carer-detail",
        "route": "/carers/:id",
        "archetype": "detail",
        "actions": [],
    })
    plan["pages"][0]["actions"] = [
        {"label": "View", "kind": "navigate", "target": "/carers/:id"},
    ]
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "action_target_resolves" for v in violations)


def test_r3_accepts_navigate_action_target_matching_by_slug():
    # Planner writes `/carers/:id`, page.route may be `/carers/[id]`. Accept
    # both — normalization is deterministic.
    plan = _plan()
    plan["pages"].append({
        "id": "carer-detail",
        "route": "/carers/[id]",
        "archetype": "detail",
        "actions": [],
    })
    plan["pages"][0]["actions"] = [
        {"label": "View", "kind": "navigate", "target": "/carers/:id"},
    ]
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "action_target_resolves" for v in violations)


def test_r3_none_kind_needs_no_target():
    # Decorative or view-only actions declare kind:"none" instead of leaving
    # target dangling. This is the affirmative signal that a button is
    # intentionally non-interactive.
    plan = _plan()
    plan["pages"][0]["actions"] = [{"label": "Info", "kind": "none"}]
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "action_target_resolves" for v in violations)


# ────────────────────────────────────────────────────────────
# R4 — workflow_has_step
# ────────────────────────────────────────────────────────────


def test_r4_flags_referenced_workflow_with_no_steps():
    plan = _plan()
    plan["workflows"] = [{"name": "CreateCarer"}]  # no steps
    plan["pages"][0]["actions"] = [
        {"label": "Create", "kind": "workflow", "target": "CreateCarer"},
    ]
    violations = validate_plan_completeness(plan)
    assert any(v.rule == "workflow_has_step" for v in violations)


def test_r4_no_flag_when_workflow_has_step():
    plan = _plan()
    plan["workflows"] = [{
        "name": "CreateCarer",
        "steps": [{"actionType": "db_insert", "table": "carers"}],
    }]
    plan["pages"][0]["actions"] = [
        {"label": "Create", "kind": "workflow", "target": "CreateCarer"},
    ]
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "workflow_has_step" for v in violations)


def test_r4_unreferenced_workflows_are_not_checked():
    # An orphan workflow (no action points at it) doesn't get flagged for
    # emptiness — the orphan-detector is a different concern (a warning,
    # not a build gate).
    plan = _plan()
    plan["workflows"] = [{"name": "OrphanWorkflow"}]
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "workflow_has_step" for v in violations)


# ────────────────────────────────────────────────────────────
# R5 — entity_has_surface
# ────────────────────────────────────────────────────────────


def test_r5_flags_entity_with_no_page():
    plan = _plan()
    plan["entities"]["Ghost"] = {"table": "ghosts", "fields": {"id": {"type": "uuid"}}}
    # No page bound to Ghost.
    violations = validate_plan_completeness(plan)
    ghost_v = [v for v in violations if v.rule == "entity_has_surface" and v.entity == "Ghost"]
    assert ghost_v


def test_r5_no_flag_when_any_page_binds_the_entity():
    plan = _plan()
    plan["entities"]["Carer"] = {"table": "carers", "fields": {"id": {"type": "uuid"}}}
    # The default fixture already has a list page for Carer.
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "entity_has_surface" and v.entity == "Carer" for v in violations)


def test_r5_internal_entities_are_exempt():
    plan = _plan()
    plan["entities"]["AuditLog"] = {
        "table": "audit_logs",
        "internal": True,
        "fields": {"id": {"type": "uuid"}},
    }
    violations = validate_plan_completeness(plan)
    assert not any(v.rule == "entity_has_surface" and v.entity == "AuditLog" for v in violations)


def test_r5_flag_message_includes_entity_name():
    plan = _plan()
    plan["entities"]["Notification"] = {"table": "notifications", "fields": {"id": {"type": "uuid"}}}
    violations = validate_plan_completeness(plan)
    match = [v for v in violations if v.rule == "entity_has_surface" and v.entity == "Notification"]
    assert match
    assert "Notification" in match[0].msg


# ────────────────────────────────────────────────────────────
# integration — complete plan produces zero new violations
# ────────────────────────────────────────────────────────────


def test_complete_plan_produces_no_new_slice1_violations():
    plan = {
        "entities": {
            "Carer": {"table": "carers", "fields": {"id": {"type": "uuid"}}},
            "AuditLog": {"table": "audit_logs", "internal": True, "fields": {"id": {"type": "uuid"}}},
        },
        "workflows": [{
            "name": "CreateCarer",
            "steps": [{"actionType": "db_insert", "table": "carers"}],
        }],
        "pages": [
            {
                "id": "carers-list",
                "route": "/carers",
                "archetype": "list",
                "entity": "Carer",
                "dataSource": {"entity": "Carer", "op": "list"},
                "actions": [
                    {"label": "Create", "kind": "workflow", "target": "CreateCarer"},
                    {"label": "Details", "kind": "navigate", "target": "/carers/:id"},
                    {"label": "Info banner", "kind": "none"},
                ],
            },
            {
                "id": "carer-detail",
                "route": "/carers/[id]",
                "archetype": "detail",
                "entity": "Carer",
                "dataSource": {"entity": "Carer", "op": "get"},
                "actions": [],
            },
        ],
    }
    violations = validate_plan_completeness(plan)
    slice1_rules = {
        "page_data_source_declared", "page_actions_declared",
        "action_target_resolves", "workflow_has_step", "entity_has_surface",
    }
    assert not any(v.rule in slice1_rules for v in violations)

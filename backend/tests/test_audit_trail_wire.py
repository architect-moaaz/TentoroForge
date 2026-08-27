"""audit_trail_wire — the pilot for the platform-primitive pattern.

Given a plan that declares ``audit_trail: [{entity, on: [...]}]``,
verify the wire pass materializes the intent by reusing existing
primitives: adds an ``AuditEntry`` entity, appends audit-logging
steps to mutation workflows, and registers a ``/audit`` list page.
"""
from __future__ import annotations

import copy

import pytest

from services.audit_trail_wire import (
    AUDIT_ENTITY_NAME,
    AUDIT_PAGE_ROUTE,
    AUDIT_TABLE_NAME,
    is_audit_trail_enabled,
    wire_audit_trail,
)


# ────────────────────────────────────────────────────────────
# No-op paths (byte-unchanged when audit_trail is absent/empty)
# ────────────────────────────────────────────────────────────

def test_no_audit_trail_slot_is_no_op():
    plan = {"entities": [{"name": "X"}], "pages": [{"route": "/x"}]}
    result = wire_audit_trail(plan)
    assert result == plan
    # Callers can safely re-bind without their local reference mutating.
    assert result is not plan


def test_empty_audit_trail_list_is_no_op():
    plan = {"audit_trail": [], "entities": [{"name": "X"}]}
    assert wire_audit_trail(plan) == plan


def test_none_plan_is_returned_verbatim():
    assert wire_audit_trail(None) is None


def test_malformed_audit_trail_entry_silently_dropped():
    """Bad entries never fail generation — they're just ignored."""
    plan = {
        "audit_trail": [
            {"entity": "X", "on": ["create"]},          # valid
            "not a dict",                                # bad
            {"entity": "", "on": ["create"]},            # empty entity
            {"entity": "Y", "on": []},                   # no actions
            {"entity": "Z"},                             # missing 'on' → defaults
        ],
        "entities": [{"name": "X"}, {"name": "Y"}, {"name": "Z"}],
    }
    result = wire_audit_trail(plan)
    # AuditEntry got added once even though 3 valid + several bad entries
    audit_ents = [e for e in result["entities"]
                  if e.get("name") == AUDIT_ENTITY_NAME]
    assert len(audit_ents) == 1


# ────────────────────────────────────────────────────────────
# AuditEntry entity
# ────────────────────────────────────────────────────────────

def test_audit_entity_added_when_declaration_present():
    plan = {
        "audit_trail": [{"entity": "Feedback", "on": ["create"]}],
        "entities":    [{"name": "Feedback"}],
    }
    result = wire_audit_trail(plan)
    names = {e.get("name") for e in result["entities"]}
    assert AUDIT_ENTITY_NAME in names


def test_audit_entity_carries_expected_columns():
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "entities":    [{"name": "X"}],
    }
    result = wire_audit_trail(plan)
    ae = next(e for e in result["entities"]
              if e.get("name") == AUDIT_ENTITY_NAME)
    field_names = {f["name"] for f in ae["fields"]}
    assert field_names == {
        "id", "actor_id", "action", "entity_type", "entity_id",
        "before", "after", "reason", "created_at",
    }
    # action is enum-scoped to the three legal values
    action_field = next(f for f in ae["fields"] if f["name"] == "action")
    assert set(action_field.get("enum_values") or []) == {
        "create", "update", "delete",
    }


def test_audit_entity_table_name_is_snake_case():
    plan = {"audit_trail": [{"entity": "X", "on": ["create"]}],
            "entities":    [{"name": "X"}]}
    result = wire_audit_trail(plan)
    ae = next(e for e in result["entities"]
              if e.get("name") == AUDIT_ENTITY_NAME)
    assert ae["table"] == AUDIT_TABLE_NAME


def test_audit_entity_not_duplicated_when_already_present():
    """Idempotency: a plan that already has AuditEntry keeps just one."""
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "entities": [
            {"name": "X"},
            {"name": AUDIT_ENTITY_NAME, "table": "custom"},
        ],
    }
    result = wire_audit_trail(plan)
    audit_ents = [e for e in result["entities"]
                  if e.get("name") == AUDIT_ENTITY_NAME]
    assert len(audit_ents) == 1
    # The existing definition wins (we never overwrite user config).
    assert audit_ents[0].get("table") == "custom"


def test_audit_entity_uses_data_models_key_when_plan_uses_that_shape():
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "data_models": [{"name": "X"}],
    }
    result = wire_audit_trail(plan)
    names = {e.get("name") for e in result["data_models"]}
    assert AUDIT_ENTITY_NAME in names
    assert "entities" not in result


# ────────────────────────────────────────────────────────────
# Workflow step injection
# ────────────────────────────────────────────────────────────

def _basic_plan_with_workflow(steps: list[dict]) -> dict:
    return {
        "audit_trail": [{"entity": "Feedback", "on": ["create", "update", "delete"]}],
        "entities":    [{"name": "Feedback"}],
        "workflows": [
            {"name": "wf1", "steps": steps},
        ],
    }


def test_audit_step_injected_for_tracked_entity_create():
    plan = _basic_plan_with_workflow([
        {"id": "trig", "type": "trigger", "next": "ins"},
        {"id": "ins",  "type": "db_insert", "entity": "Feedback", "next": "end"},
        {"id": "end",  "type": "end"},
    ])
    result = wire_audit_trail(plan)
    steps = result["workflows"][0]["steps"]
    ids = [s["id"] for s in steps]
    assert "audit_log_create_Feedback" in ids
    # inserted before 'end'
    assert ids.index("audit_log_create_Feedback") < ids.index("end")


def test_audit_step_configures_expected_values():
    plan = _basic_plan_with_workflow([
        {"id": "trig", "type": "trigger"},
        {"id": "ins",  "type": "db_insert", "entity": "Feedback"},
        {"id": "end",  "type": "end"},
    ])
    result = wire_audit_trail(plan)
    audit = next(s for s in result["workflows"][0]["steps"]
                 if s["id"] == "audit_log_create_Feedback")
    assert audit["type"] == "db_insert"
    assert audit["entity"] == AUDIT_ENTITY_NAME
    vals = audit["config"]["values"]
    assert vals["action"] == "create"
    assert vals["entity_type"] == "Feedback"
    # entity_id comes from the source step's output.id (runtime resolves).
    assert "steps.ins.output.id" in vals["entity_id"]


def test_audit_step_not_injected_for_untracked_entity():
    plan = {
        "audit_trail": [{"entity": "Feedback", "on": ["create"]}],
        "entities":    [{"name": "Feedback"}, {"name": "Other"}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "ins",  "type": "db_insert", "entity": "Other"},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    result = wire_audit_trail(plan)
    ids = [s["id"] for s in result["workflows"][0]["steps"]]
    assert not any(i.startswith("audit_log_") for i in ids)


def test_audit_step_not_injected_when_action_not_declared():
    """If plan says on:[create] only, an update mutation is untouched."""
    plan = {
        "audit_trail": [{"entity": "Feedback", "on": ["create"]}],
        "entities":    [{"name": "Feedback"}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "upd",  "type": "db_update", "entity": "Feedback"},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    result = wire_audit_trail(plan)
    ids = [s["id"] for s in result["workflows"][0]["steps"]]
    assert not any(i.startswith("audit_log_") for i in ids)


def test_step_target_entity_read_from_nested_config():
    """Some emitters wrap the target under config.entity — support both."""
    plan = {
        "audit_trail": [{"entity": "Feedback", "on": ["update"]}],
        "entities":    [{"name": "Feedback"}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "upd",  "type": "db_update",
                 "config": {"entity": "Feedback", "values": {}}},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    result = wire_audit_trail(plan)
    ids = [s["id"] for s in result["workflows"][0]["steps"]]
    assert "audit_log_update_Feedback" in ids


def test_multiple_mutations_get_multiple_audit_steps():
    """A workflow that does both an insert AND an update on the same
    tracked entity gets both logged."""
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create", "update"]}],
        "entities":    [{"name": "X"}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "ins",  "type": "db_insert", "entity": "X"},
                {"id": "upd",  "type": "db_update", "entity": "X"},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    result = wire_audit_trail(plan)
    ids = [s["id"] for s in result["workflows"][0]["steps"]]
    assert "audit_log_create_X" in ids
    assert "audit_log_update_X" in ids
    # both inserted before 'end'
    end_idx = ids.index("end")
    assert ids.index("audit_log_create_X") < end_idx
    assert ids.index("audit_log_update_X") < end_idx


def test_workflow_without_end_node_skipped_defensively():
    """A malformed workflow (no 'end') must not crash the pass."""
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "entities":    [{"name": "X"}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "ins",  "type": "db_insert", "entity": "X"},
            ]},
        ],
    }
    result = wire_audit_trail(plan)
    ids = [s["id"] for s in result["workflows"][0]["steps"]]
    assert not any(i.startswith("audit_log_") for i in ids)


# ────────────────────────────────────────────────────────────
# /audit list page
# ────────────────────────────────────────────────────────────

def test_audit_list_page_added_when_declaration_present():
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "entities":    [{"name": "X"}],
        "pages":       [],
    }
    result = wire_audit_trail(plan)
    routes = [p["route"] for p in result["pages"]]
    assert AUDIT_PAGE_ROUTE in routes


def test_audit_list_page_shape():
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "entities":    [{"name": "X"}],
    }
    result = wire_audit_trail(plan)
    page = next(p for p in result["pages"]
                if p["route"] == AUDIT_PAGE_ROUTE)
    assert page["archetype"] == "list"
    assert page["entity"] == AUDIT_ENTITY_NAME
    assert "admin" in (page.get("roles") or [])
    assert "created_at" in page.get("columns", [])
    assert "action" in page.get("columns", [])


def test_audit_list_page_not_duplicated():
    """If /audit already exists (from a previous wire pass or manual
    authoring), we don't add a second one."""
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "entities":    [{"name": "X"}],
        "pages": [{"route": AUDIT_PAGE_ROUTE, "custom": True}],
    }
    result = wire_audit_trail(plan)
    audit_pages = [p for p in result["pages"]
                   if p.get("route") == AUDIT_PAGE_ROUTE]
    assert len(audit_pages) == 1
    # existing page preserved verbatim (not overwritten)
    assert audit_pages[0].get("custom") is True


# ────────────────────────────────────────────────────────────
# Idempotency + immutability
# ────────────────────────────────────────────────────────────

def test_wire_is_idempotent():
    """Running twice must yield the same result — the pilot pattern
    depends on this so downstream pipeline passes can safely re-run."""
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "entities":    [{"name": "X"}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "ins",  "type": "db_insert", "entity": "X"},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    once = wire_audit_trail(plan)
    twice = wire_audit_trail(once)
    assert once == twice


def test_wire_does_not_mutate_input_plan():
    """Immutability of the input is required — callers pass the same
    plan dict to multiple pipeline steps."""
    plan = {
        "audit_trail": [{"entity": "X", "on": ["create"]}],
        "entities":    [{"name": "X"}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "ins",  "type": "db_insert", "entity": "X"},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    snapshot = copy.deepcopy(plan)
    wire_audit_trail(plan)
    assert plan == snapshot


# ────────────────────────────────────────────────────────────
# Env gate
# ────────────────────────────────────────────────────────────

def test_env_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_AUDIT_TRAIL", raising=False)
    assert is_audit_trail_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_env_gate_accepts_truthy(monkeypatch, val):
    monkeypatch.setenv("FORGE_AUDIT_TRAIL", val)
    assert is_audit_trail_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_env_gate_rejects_falsy(monkeypatch, val):
    monkeypatch.setenv("FORGE_AUDIT_TRAIL", val)
    assert is_audit_trail_enabled() is False

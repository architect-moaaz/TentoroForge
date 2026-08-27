"""immutability_wire — the second wire-pass primitive."""
from __future__ import annotations

import copy

import pytest

from services.immutability_wire import (
    is_immutability_enabled,
    wire_immutability,
)


# ── no-op paths ────────────────────────────────────────────────

def test_no_declaration_is_no_op():
    plan = {"entities": [{"name": "X"}], "workflows": []}
    assert wire_immutability(plan) == plan


def test_none_plan_returns_verbatim():
    assert wire_immutability(None) is None


def test_malformed_entries_dropped_silently():
    plan = {
        "immutability": [
            "not a dict",
            {"entity": ""},        # empty name
            {},                    # missing entity
            {"entity": "X"},       # valid — defaults applied
        ],
        "entities": [{"name": "X", "fields": []}],
    }
    result = wire_immutability(plan)
    fields = {f["name"] for f in result["entities"][0]["fields"]}
    assert "is_locked" in fields


# ── column addition ────────────────────────────────────────────

def test_is_locked_and_locked_at_added_to_tracked_entity():
    plan = {
        "immutability": [{"entity": "Feedback"}],
        "entities":     [{"name": "Feedback", "fields": [{"name": "text"}]}],
    }
    result = wire_immutability(plan)
    fields = {f["name"]: f for f in result["entities"][0]["fields"]}
    assert "is_locked" in fields
    assert fields["is_locked"]["type"] == "boolean"
    assert fields["is_locked"]["default"] is False
    assert "locked_at" in fields
    assert fields["locked_at"]["type"] == "timestamp"


def test_is_locked_not_duplicated_when_column_exists():
    plan = {
        "immutability": [{"entity": "X"}],
        "entities":     [{
            "name": "X",
            "fields": [{"name": "is_locked", "type": "boolean"}],
        }],
    }
    result = wire_immutability(plan)
    is_locked_cols = [f for f in result["entities"][0]["fields"]
                      if f["name"] == "is_locked"]
    assert len(is_locked_cols) == 1


def test_untracked_entity_untouched():
    plan = {
        "immutability": [{"entity": "Feedback"}],
        "entities":     [{"name": "Feedback", "fields": []},
                         {"name": "Other",    "fields": []}],
    }
    result = wire_immutability(plan)
    other = next(e for e in result["entities"] if e["name"] == "Other")
    assert {f["name"] for f in other["fields"]} == set()


# ── detail-page annotation ─────────────────────────────────────

def test_detail_page_gets_immutability_metadata():
    plan = {
        "immutability": [{"entity": "Feedback",
                          "when": "after_submit",
                          "exception_roles": ["admin"]}],
        "entities":     [{"name": "Feedback", "fields": []}],
        "pages": [
            {"route": "/feedback/[id]",
             "archetype": "detail",
             "entity":    "Feedback"},
        ],
    }
    result = wire_immutability(plan)
    page = result["pages"][0]
    assert page["immutability"]["when"] == "after_submit"
    assert "admin" in page["immutability"]["exception_roles"]


def test_list_page_not_annotated():
    plan = {
        "immutability": [{"entity": "X"}],
        "entities":     [{"name": "X", "fields": []}],
        "pages": [{"route": "/xs", "archetype": "list", "entity": "X"}],
    }
    result = wire_immutability(plan)
    assert "immutability" not in result["pages"][0]


# ── mutation-step annotation ───────────────────────────────────

def test_db_update_for_tracked_entity_annotated():
    plan = {
        "immutability": [{"entity": "Feedback"}],
        "entities":     [{"name": "Feedback", "fields": []}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "upd",  "type": "db_update", "entity": "Feedback"},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    result = wire_immutability(plan)
    upd = next(s for s in result["workflows"][0]["steps"] if s["id"] == "upd")
    assert upd["guarded_by"] == "immutability"


def test_db_delete_for_tracked_entity_annotated():
    plan = {
        "immutability": [{"entity": "X"}],
        "entities":     [{"name": "X", "fields": []}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "del",  "type": "db_delete", "entity": "X"},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    result = wire_immutability(plan)
    dele = next(s for s in result["workflows"][0]["steps"] if s["id"] == "del")
    assert dele["guarded_by"] == "immutability"


def test_db_insert_for_tracked_entity_not_annotated():
    """Inserts CREATE the row — no lock to check yet."""
    plan = {
        "immutability": [{"entity": "X"}],
        "entities":     [{"name": "X", "fields": []}],
        "workflows": [
            {"name": "wf1", "steps": [
                {"id": "trig", "type": "trigger"},
                {"id": "ins",  "type": "db_insert", "entity": "X"},
                {"id": "end",  "type": "end"},
            ]},
        ],
    }
    result = wire_immutability(plan)
    ins = next(s for s in result["workflows"][0]["steps"] if s["id"] == "ins")
    assert "guarded_by" not in ins


# ── idempotency + immutability ─────────────────────────────────

def test_wire_is_idempotent():
    plan = {
        "immutability": [{"entity": "X"}],
        "entities":     [{"name": "X", "fields": []}],
        "workflows": [{"name": "w", "steps": [
            {"id": "t", "type": "trigger"},
            {"id": "u", "type": "db_update", "entity": "X"},
            {"id": "e", "type": "end"},
        ]}],
    }
    assert wire_immutability(wire_immutability(plan)) == wire_immutability(plan)


def test_input_not_mutated():
    plan = {
        "immutability": [{"entity": "X"}],
        "entities":     [{"name": "X", "fields": []}],
    }
    snap = copy.deepcopy(plan)
    wire_immutability(plan)
    assert plan == snap


# ── env gate ───────────────────────────────────────────────────

def test_env_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_IMMUTABILITY", raising=False)
    assert is_immutability_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_env_gate_truthy(monkeypatch, val):
    monkeypatch.setenv("FORGE_IMMUTABILITY", val)
    assert is_immutability_enabled() is True

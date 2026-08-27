"""plan_field_lookup — read plan-declared field metadata.

The plan is the authority for enum_values, fk, semantic_type, not_null.
Downstream services call this module to answer field-metadata questions
INSTEAD of guessing from workflow strings or field names.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.plan_field_lookup import (
    get_default_value,
    get_enum_options,
    get_enum_values,
    get_field,
    get_fk,
    get_lifecycle_status,
    get_not_null,
    get_semantic_type,
    load_plan,
    title_case_key,
)


def _write_plan(tmp_path: Path, plan: dict) -> str:
    p = tmp_path / "src" / "contracts"
    p.mkdir(parents=True)
    (p / "plan.json").write_text(json.dumps(plan))
    return str(tmp_path)


# ────────────────────────────────────────────────────────────
# load_plan
# ────────────────────────────────────────────────────────────

def test_load_returns_none_when_missing(tmp_path):
    assert load_plan(tmp_path) is None


def test_load_returns_dict_when_present(tmp_path):
    out = _write_plan(tmp_path, {"module_name": "x"})
    assert load_plan(out) == {"module_name": "x"}


def test_load_caches_across_calls(tmp_path):
    out = _write_plan(tmp_path, {"module_name": "x"})
    first = load_plan(out)
    second = load_plan(out)
    assert first is second  # same cached object


def test_load_invalidates_cache_on_mtime_change(tmp_path):
    out = _write_plan(tmp_path, {"module_name": "old"})
    assert load_plan(out)["module_name"] == "old"
    # Simulate re-persist with different content + advance mtime
    p = Path(out) / "src" / "contracts" / "plan.json"
    p.write_text(json.dumps({"module_name": "new"}))
    import os
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 1))  # bump mtime forward
    assert load_plan(out)["module_name"] == "new"


# ────────────────────────────────────────────────────────────
# get_field — both plan shapes
# ────────────────────────────────────────────────────────────

def test_get_field_from_entities_dict_shape():
    plan = {"entities": {"Application": {"fields": [
        {"name": "status", "type": "varchar"},
    ]}}}
    f = get_field(plan, "Application", "status")
    assert f is not None and f["type"] == "varchar"


def test_get_field_from_data_models_list_shape():
    plan = {"data_models": [
        {"name": "Application", "fields": [
            {"name": "status", "type": "varchar"},
        ]},
    ]}
    f = get_field(plan, "Application", "status")
    assert f is not None and f["type"] == "varchar"


def test_get_field_case_insensitive_entity_name():
    plan = {"entities": {"Application": {"fields": [
        {"name": "status", "type": "varchar"},
    ]}}}
    assert get_field(plan, "application", "status") is not None
    assert get_field(plan, "APPLICATION", "status") is not None


def test_get_field_matches_camel_and_snake_case_column():
    plan = {"entities": {"Application": {"fields": [
        {"name": "basedAt", "type": "varchar"},
    ]}}}
    assert get_field(plan, "Application", "basedAt") is not None
    assert get_field(plan, "Application", "based_at") is not None
    assert get_field(plan, "Application", "BASED_AT") is not None


def test_get_field_returns_none_when_missing():
    plan = {"entities": {"Application": {"fields": []}}}
    assert get_field(plan, "Application", "status") is None
    assert get_field(plan, "Ghost", "status") is None


def test_get_field_returns_none_when_plan_is_none():
    assert get_field(None, "Application", "status") is None


# ────────────────────────────────────────────────────────────
# get_enum_values
# ────────────────────────────────────────────────────────────

def test_enum_values_returned_verbatim():
    plan = {"entities": {"Application": {"fields": [
        {"name": "status", "type": "varchar",
         "enum_values": ["open", "shortlisted", "rejected"]},
    ]}}}
    assert get_enum_values(plan, "Application", "status") == [
        "open", "shortlisted", "rejected"]


def test_enum_values_empty_list_treated_as_none():
    """A mis-emitted `enum_values: []` should not produce an empty dropdown.
    Callers get None so they fall back to their existing derivation."""
    plan = {"entities": {"Application": {"fields": [
        {"name": "status", "type": "varchar", "enum_values": []},
    ]}}}
    assert get_enum_values(plan, "Application", "status") is None


def test_enum_values_none_when_field_missing():
    plan = {"entities": {"Application": {"fields": []}}}
    assert get_enum_values(plan, "Application", "status") is None


def test_enum_values_filters_out_non_strings():
    plan = {"entities": {"Application": {"fields": [
        {"name": "status", "enum_values": ["open", None, 42, "closed"]},
    ]}}}
    assert get_enum_values(plan, "Application", "status") == ["open", "closed"]


def test_enum_values_accepts_object_shape():
    """Spec B1: enum_values may be `[{key,label}]` (or `{value,label}`).
    `get_enum_values` still returns the raw keys so old callers keep working."""
    plan = {"entities": {"Payment": {"fields": [
        {"name": "method", "enum_values": [
            {"key": "ach", "label": "ACH Transfer"},
            {"key": "cash", "label": "Cash"},
        ]},
    ]}}}
    assert get_enum_values(plan, "Payment", "method") == ["ach", "cash"]


def test_enum_values_accepts_value_key_shape():
    plan = {"entities": {"Payment": {"fields": [
        {"name": "method", "enum_values": [
            {"value": "ach", "label": "ACH"},
        ]},
    ]}}}
    assert get_enum_values(plan, "Payment", "method") == ["ach"]


# ────────────────────────────────────────────────────────────
# get_enum_options — Spec B1 (returns [{value, label}])
# ────────────────────────────────────────────────────────────

def test_enum_options_from_flat_strings_title_cases_label():
    """Flat `[str]` input: label auto-derived via Title Case."""
    plan = {"entities": {"Application": {"fields": [
        {"name": "status", "enum_values": ["open", "in_progress", "closed"]},
    ]}}}
    assert get_enum_options(plan, "Application", "status") == [
        {"value": "open", "label": "Open"},
        {"value": "in_progress", "label": "In Progress"},
        {"value": "closed", "label": "Closed"},
    ]


def test_enum_options_prefers_authored_label():
    """Object input with `label`: use it verbatim, don't re-Title-Case."""
    plan = {"entities": {"Payment": {"fields": [
        {"name": "method", "enum_values": [
            {"key": "ach", "label": "ACH Transfer"},
            {"key": "cash", "label": "Cash"},
        ]},
    ]}}}
    assert get_enum_options(plan, "Payment", "method") == [
        {"value": "ach", "label": "ACH Transfer"},
        {"value": "cash", "label": "Cash"},
    ]


def test_enum_options_mixed_shape():
    """Some entries as strings, some as objects — normalize each."""
    plan = {"entities": {"Payment": {"fields": [
        {"name": "method", "enum_values": [
            "cash",  # → {value:"cash", label:"Cash"}
            {"key": "ach", "label": "ACH Transfer"},
        ]},
    ]}}}
    assert get_enum_options(plan, "Payment", "method") == [
        {"value": "cash", "label": "Cash"},
        {"value": "ach", "label": "ACH Transfer"},
    ]


def test_enum_options_none_when_field_missing():
    plan = {"entities": {"Application": {"fields": []}}}
    assert get_enum_options(plan, "Application", "status") is None


def test_enum_options_none_when_empty():
    plan = {"entities": {"Application": {"fields": [
        {"name": "status", "enum_values": []},
    ]}}}
    assert get_enum_options(plan, "Application", "status") is None


def test_enum_options_drops_entries_missing_a_key():
    plan = {"entities": {"Payment": {"fields": [
        {"name": "method", "enum_values": [
            {"label": "orphan-with-no-key"},
            {"key": "ach", "label": "ACH"},
        ]},
    ]}}}
    assert get_enum_options(plan, "Payment", "method") == [
        {"value": "ach", "label": "ACH"},
    ]


# ────────────────────────────────────────────────────────────
# title_case_key — the fallback labeler
# ────────────────────────────────────────────────────────────

def test_title_case_key_underscores():
    assert title_case_key("in_progress") == "In Progress"
    assert title_case_key("credit_card") == "Credit Card"


def test_title_case_key_single_word():
    assert title_case_key("open") == "Open"


def test_title_case_key_camel_case():
    """camelCase source key like `inProgress` → `In Progress`."""
    assert title_case_key("inProgress") == "In Progress"


def test_title_case_key_hyphens():
    assert title_case_key("credit-card") == "Credit Card"


def test_title_case_key_empty():
    assert title_case_key("") == ""


# ────────────────────────────────────────────────────────────
# get_fk
# ────────────────────────────────────────────────────────────

def test_fk_returned_when_complete():
    plan = {"entities": {"Application": {"fields": [
        {"name": "candidateId", "type": "uuid",
         "fk": {"table": "users", "column": "id"}},
    ]}}}
    assert get_fk(plan, "Application", "candidateId") == {
        "table": "users", "column": "id"}


def test_fk_none_when_missing_pieces():
    plan = {"entities": {"Application": {"fields": [
        {"name": "candidateId", "fk": {"table": "users"}},   # no column
    ]}}}
    assert get_fk(plan, "Application", "candidateId") is None


def test_fk_none_when_not_declared():
    plan = {"entities": {"Application": {"fields": [
        {"name": "candidateId", "type": "uuid"},
    ]}}}
    assert get_fk(plan, "Application", "candidateId") is None


# ────────────────────────────────────────────────────────────
# get_semantic_type
# ────────────────────────────────────────────────────────────

def test_semantic_type_returned():
    plan = {"entities": {"Application": {"fields": [
        {"name": "basedAt", "semantic_type": "city"},
    ]}}}
    assert get_semantic_type(plan, "Application", "basedAt") == "city"


def test_semantic_type_none_when_missing():
    plan = {"entities": {"Application": {"fields": [
        {"name": "basedAt", "type": "varchar"},
    ]}}}
    assert get_semantic_type(plan, "Application", "basedAt") is None


# ────────────────────────────────────────────────────────────
# get_not_null
# ────────────────────────────────────────────────────────────

def test_not_null_explicit_true():
    plan = {"entities": {"App": {"fields": [
        {"name": "name", "not_null": True},
    ]}}}
    assert get_not_null(plan, "App", "name") is True


def test_not_null_explicit_false():
    plan = {"entities": {"App": {"fields": [
        {"name": "name", "not_null": False},
    ]}}}
    assert get_not_null(plan, "App", "name") is False


def test_not_null_via_nullable_alias():
    """When the plan says `nullable: true`, that means `not_null: false`."""
    plan = {"entities": {"App": {"fields": [
        {"name": "name", "nullable": True},
    ]}}}
    assert get_not_null(plan, "App", "name") is False


def test_not_null_none_when_unspecified():
    plan = {"entities": {"App": {"fields": [
        {"name": "name", "type": "varchar"},
    ]}}}
    assert get_not_null(plan, "App", "name") is None


# ────────────────────────────────────────────────────────────
# get_lifecycle_status + get_default_value — Spec B7
# ────────────────────────────────────────────────────────────

def test_lifecycle_status_true_when_flagged():
    plan = {"entities": {"Ticket": {"fields": [
        {"name": "status", "enum_values": ["open", "closed"],
         "lifecycle_status": True, "default_value": "open"},
    ]}}}
    assert get_lifecycle_status(plan, "Ticket", "status") is True
    assert get_default_value(plan, "Ticket", "status") == "open"


def test_lifecycle_status_false_when_absent():
    plan = {"entities": {"Card": {"fields": [
        {"name": "status", "enum_values": ["todo", "doing", "done"]},
    ]}}}
    # No flag → user-picked enum (kanban column). Create form should show it.
    assert get_lifecycle_status(plan, "Card", "status") is False


def test_lifecycle_status_never_infers_from_name():
    """A field called `status` is NOT automatically lifecycle_status.
    The planner decides per-domain — a kanban card's `status` is user-picked."""
    plan = {"entities": {"Card": {"fields": [{"name": "status"}]}}}
    assert get_lifecycle_status(plan, "Card", "status") is False


def test_default_value_from_default_alias():
    plan = {"entities": {"Ticket": {"fields": [
        {"name": "status", "default": "open"},
    ]}}}
    assert get_default_value(plan, "Ticket", "status") == "open"


def test_default_value_none_when_absent():
    plan = {"entities": {"Ticket": {"fields": [{"name": "status"}]}}}
    assert get_default_value(plan, "Ticket", "status") is None

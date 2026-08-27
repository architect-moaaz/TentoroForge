"""Tests for services.plan_column_semantics — the shared plan reader that
semantic_field_types + fk_semantics + their downstream callers check
BEFORE running their own regex/name heuristics (Spec D W2)."""
from __future__ import annotations

from services.plan_column_semantics import (
    get_enum_values,
    get_fk_role,
    get_semantic,
)


def _plan(fields: list[dict]) -> dict:
    """Build a minimal plan with a single `Task` entity."""
    return {"entities": {"Task": {"fields": fields}}}


# ── get_semantic ─────────────────────────────────────────────────────────

class TestGetSemantic:
    def test_reads_semantic_control_from_blob(self):
        plan = _plan([{"name": "colorNote", "semantic": {"control": "Textarea"}}])
        assert get_semantic(plan, "Task", "colorNote") == "Textarea"

    def test_reads_legacy_semantic_type_when_blob_missing(self):
        plan = _plan([{"name": "amount", "semantic_type": "currency"}])
        assert get_semantic(plan, "Task", "amount") == "currency"

    def test_blob_control_beats_legacy_semantic_type(self):
        plan = _plan([{
            "name": "note",
            "semantic": {"control": "Textarea"},
            "semantic_type": "currency",
        }])
        assert get_semantic(plan, "Task", "note") == "Textarea"

    def test_returns_none_when_plan_silent(self):
        assert get_semantic(_plan([{"name": "x"}]), "Task", "x") is None

    def test_returns_none_on_missing_entity(self):
        assert get_semantic(_plan([{"name": "x"}]), "Ghost", "x") is None

    def test_returns_none_on_missing_column(self):
        assert get_semantic(_plan([{"name": "x"}]), "Task", "y") is None

    def test_none_plan_returns_none(self):
        assert get_semantic(None, "Task", "x") is None

    def test_case_insensitive_camel_snake(self):
        # plan uses `based_at`; caller asks for `basedAt`.
        plan = _plan([{"name": "based_at", "semantic": {"control": "Input"}}])
        assert get_semantic(plan, "Task", "basedAt") == "Input"

    def test_non_dict_semantic_falls_through_to_legacy(self):
        plan = _plan([{
            "name": "x",
            "semantic": "widget",  # not a dict — ignored
            "semantic_type": "email",
        }])
        assert get_semantic(plan, "Task", "x") == "email"


# ── get_fk_role ──────────────────────────────────────────────────────────

class TestGetFkRole:
    def test_actor_role(self):
        assert get_fk_role(_plan([{"name": "c", "role": "actor"}]), "Task", "c") == "actor"

    def test_assignment_role(self):
        assert get_fk_role(_plan([{"name": "c", "role": "assignment"}]), "Task", "c") == "assignment"

    def test_tenancy_role(self):
        assert get_fk_role(_plan([{"name": "c", "role": "tenancy"}]), "Task", "c") == "tenancy"

    def test_domain_role(self):
        assert get_fk_role(_plan([{"name": "c", "role": "domain"}]), "Task", "c") == "domain"

    def test_invalid_role_returns_none(self):
        # `operator` isn't in the closed set — collapse to None.
        assert get_fk_role(_plan([{"name": "c", "role": "operator"}]), "Task", "c") is None

    def test_non_string_role_returns_none(self):
        assert get_fk_role(_plan([{"name": "c", "role": True}]), "Task", "c") is None

    def test_missing_role_returns_none(self):
        assert get_fk_role(_plan([{"name": "c"}]), "Task", "c") is None

    def test_missing_column_returns_none(self):
        assert get_fk_role(_plan([{"name": "c", "role": "actor"}]), "Task", "other") is None

    def test_none_plan_returns_none(self):
        assert get_fk_role(None, "Task", "c") is None


# ── get_enum_values ──────────────────────────────────────────────────────

class TestGetEnumValues:
    def test_reads_semantic_enum_values_from_blob(self):
        plan = _plan([{
            "name": "tier",
            "semantic": {"enum_values": ["Gold", "Silver", "Bronze"]},
        }])
        assert get_enum_values(plan, "Task", "tier") == ["Gold", "Silver", "Bronze"]

    def test_falls_back_to_top_level_enum_values(self):
        plan = _plan([{"name": "status", "enum_values": ["open", "closed"]}])
        assert get_enum_values(plan, "Task", "status") == ["open", "closed"]

    def test_blob_enum_values_beats_top_level(self):
        plan = _plan([{
            "name": "s",
            "enum_values": ["legacy"],
            "semantic": {"enum_values": ["new", "shape"]},
        }])
        assert get_enum_values(plan, "Task", "s") == ["new", "shape"]

    def test_empty_blob_list_falls_through_to_top_level(self):
        plan = _plan([{
            "name": "s",
            "enum_values": ["a", "b"],
            "semantic": {"enum_values": []},
        }])
        assert get_enum_values(plan, "Task", "s") == ["a", "b"]

    def test_empty_top_level_returns_none(self):
        assert get_enum_values(_plan([{"name": "s", "enum_values": []}]), "Task", "s") is None

    def test_missing_column_returns_none(self):
        assert get_enum_values(_plan([{"name": "x"}]), "Task", "y") is None

    def test_object_shape_via_top_level(self):
        # Spec B1 shape: [{key,label}] — plan_field_lookup normalizes to keys.
        plan = _plan([{
            "name": "status",
            "enum_values": [{"key": "open", "label": "Open"}, {"key": "closed"}],
        }])
        assert get_enum_values(plan, "Task", "status") == ["open", "closed"]

    def test_dedupes_blob_values(self):
        plan = _plan([{"name": "x", "semantic": {"enum_values": ["a", "a", "b"]}}])
        assert get_enum_values(plan, "Task", "x") == ["a", "b"]

    def test_none_plan_returns_none(self):
        assert get_enum_values(None, "Task", "x") is None

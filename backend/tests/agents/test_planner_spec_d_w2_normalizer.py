"""Tests for Spec D Wave 2 — planner emission normalizer.

Covers ``agents.planner._sanitize_column_semantics``, the sanitizer that
drops out-of-set values for the four fields Wave 2 classifiers consume:

  * ``entity.schedulable_by``       — scheduler_pass.detect_scheduler
  * ``column.user_fk_role``         — user_fk_types.reconcile_user_fk_types
  * ``column.role``                 — fk_semantics.classify_entity_fks
  * ``column.semantic.control``     — semantic_field_types.apply_semantic_field_types

Also verifies the sanitizer is wired into ``_annotate_page_types`` so
every LLM-emitted plan is scrubbed before downstream reads it.
"""
from __future__ import annotations

from agents.planner import _annotate_page_types, _sanitize_column_semantics


# ── entity.schedulable_by ────────────────────────────────────────────────

class TestSchedulableBy:
    def test_valid_resource_kept(self):
        plan = {"entities": {"Bay": {"schedulable_by": "resource", "fields": []}}}
        _sanitize_column_semantics(plan)
        assert plan["entities"]["Bay"]["schedulable_by"] == "resource"

    def test_valid_person_kept(self):
        plan = {"entities": {"Guest": {"schedulable_by": "person", "fields": []}}}
        _sanitize_column_semantics(plan)
        assert plan["entities"]["Guest"]["schedulable_by"] == "person"

    def test_valid_none_kept(self):
        plan = {"entities": {"Room": {"schedulable_by": "none", "fields": []}}}
        _sanitize_column_semantics(plan)
        assert plan["entities"]["Room"]["schedulable_by"] == "none"

    def test_literal_false_kept_verbatim(self):
        # False is the explicit opt-out — the scheduler_pass code checks
        # ``sb is False`` so we must preserve the type.
        plan = {"entities": {"Room": {"schedulable_by": False, "fields": []}}}
        _sanitize_column_semantics(plan)
        assert plan["entities"]["Room"]["schedulable_by"] is False

    def test_case_folded_to_lower(self):
        plan = {"entities": {"Bay": {"schedulable_by": "  RESOURCE  ", "fields": []}}}
        _sanitize_column_semantics(plan)
        assert plan["entities"]["Bay"]["schedulable_by"] == "resource"

    def test_invalid_string_dropped(self):
        plan = {"entities": {"Bay": {"schedulable_by": "maybe", "fields": []}}}
        _sanitize_column_semantics(plan)
        assert "schedulable_by" not in plan["entities"]["Bay"]

    def test_non_string_non_false_dropped(self):
        # int, None, dict etc. → not valid, remove.
        for v in (1, None, {}, [], True):
            plan = {"entities": {"Bay": {"schedulable_by": v, "fields": []}}}
            _sanitize_column_semantics(plan)
            assert "schedulable_by" not in plan["entities"]["Bay"], f"kept invalid {v!r}"

    def test_works_on_data_models_list_shape(self):
        # Full-mode plans emit `data_models: [{name, fields}]`.
        plan = {"data_models": [
            {"name": "Bay", "schedulable_by": "resource", "fields": []},
            {"name": "Bogus", "schedulable_by": "nope", "fields": []},
        ]}
        _sanitize_column_semantics(plan)
        assert plan["data_models"][0]["schedulable_by"] == "resource"
        assert "schedulable_by" not in plan["data_models"][1]


# ── column.user_fk_role ──────────────────────────────────────────────────

class TestUserFkRole:
    def test_all_valid_roles_kept(self):
        for role in ("actor", "assignment", "tenancy", "audit"):
            plan = {"entities": {"Task": {"fields": [
                {"name": "createdById", "user_fk_role": role},
            ]}}}
            _sanitize_column_semantics(plan)
            assert plan["entities"]["Task"]["fields"][0]["user_fk_role"] == role

    def test_case_folded(self):
        plan = {"entities": {"Task": {"fields": [
            {"name": "c", "user_fk_role": "  ACTOR "},
        ]}}}
        _sanitize_column_semantics(plan)
        assert plan["entities"]["Task"]["fields"][0]["user_fk_role"] == "actor"

    def test_invalid_string_dropped(self):
        plan = {"entities": {"Task": {"fields": [
            {"name": "c", "user_fk_role": "operator"},
        ]}}}
        _sanitize_column_semantics(plan)
        assert "user_fk_role" not in plan["entities"]["Task"]["fields"][0]

    def test_non_string_dropped(self):
        for v in (True, None, 1, {}, ["actor"]):
            plan = {"entities": {"Task": {"fields": [
                {"name": "c", "user_fk_role": v},
            ]}}}
            _sanitize_column_semantics(plan)
            assert "user_fk_role" not in plan["entities"]["Task"]["fields"][0], f"kept {v!r}"

    def test_works_on_fields_dict_shape(self):
        # Some plan flavours emit `fields: {name: {...}}`.
        plan = {"entities": {"Task": {"fields": {
            "createdById": {"user_fk_role": "actor"},
            "junkId":      {"user_fk_role": "bogus"},
        }}}}
        _sanitize_column_semantics(plan)
        assert plan["entities"]["Task"]["fields"]["createdById"]["user_fk_role"] == "actor"
        assert "user_fk_role" not in plan["entities"]["Task"]["fields"]["junkId"]


# ── column.role ──────────────────────────────────────────────────────────

class TestColumnRole:
    def test_all_valid_roles_kept(self):
        for role in ("actor", "assignment", "tenancy", "domain"):
            plan = {"entities": {"Task": {"fields": [
                {"name": "c", "role": role},
            ]}}}
            _sanitize_column_semantics(plan)
            assert plan["entities"]["Task"]["fields"][0]["role"] == role

    def test_invalid_role_dropped(self):
        # 'audit' is valid for user_fk_role but NOT for column.role.
        plan = {"entities": {"Task": {"fields": [
            {"name": "c", "role": "audit"},
        ]}}}
        _sanitize_column_semantics(plan)
        assert "role" not in plan["entities"]["Task"]["fields"][0]

    def test_non_string_dropped(self):
        for v in (True, None, 1, {}, ["actor"]):
            plan = {"entities": {"Task": {"fields": [
                {"name": "c", "role": v},
            ]}}}
            _sanitize_column_semantics(plan)
            assert "role" not in plan["entities"]["Task"]["fields"][0], f"kept {v!r}"


# ── column.semantic.control ──────────────────────────────────────────────

class TestSemanticControl:
    def test_all_valid_controls_kept(self):
        for ctrl in ("Input", "Textarea", "Select", "Combobox",
                     "NumberInput", "DatePicker", "Switch", "FileUpload"):
            plan = {"entities": {"Task": {"fields": [
                {"name": "c", "semantic": {"control": ctrl}},
            ]}}}
            _sanitize_column_semantics(plan)
            assert plan["entities"]["Task"]["fields"][0]["semantic"]["control"] == ctrl

    def test_invalid_control_dropped_from_blob(self):
        plan = {"entities": {"Task": {"fields": [
            {"name": "c", "semantic": {"control": "Unicorn", "format": "phone"}},
        ]}}}
        _sanitize_column_semantics(plan)
        blob = plan["entities"]["Task"]["fields"][0]["semantic"]
        assert "control" not in blob
        # sibling keys inside the blob are untouched
        assert blob.get("format") == "phone"

    def test_non_string_control_dropped(self):
        for v in (True, None, 1, {}, ["Input"]):
            plan = {"entities": {"Task": {"fields": [
                {"name": "c", "semantic": {"control": v}},
            ]}}}
            _sanitize_column_semantics(plan)
            assert "control" not in plan["entities"]["Task"]["fields"][0]["semantic"], (
                f"kept {v!r}"
            )

    def test_non_dict_semantic_ignored(self):
        # `semantic` isn't a dict — nothing to drop; leave field alone.
        plan = {"entities": {"Task": {"fields": [
            {"name": "c", "semantic": "widget"},
        ]}}}
        _sanitize_column_semantics(plan)
        assert plan["entities"]["Task"]["fields"][0]["semantic"] == "widget"


# ── shape tolerance ─────────────────────────────────────────────────────

class TestShapeTolerance:
    def test_non_dict_plan_returned_unchanged(self):
        assert _sanitize_column_semantics(None) is None  # type: ignore[arg-type]
        assert _sanitize_column_semantics("string") == "string"  # type: ignore[arg-type]
        assert _sanitize_column_semantics([]) == []  # type: ignore[arg-type]

    def test_no_entities_key_no_op(self):
        plan = {"pages": []}
        assert _sanitize_column_semantics(plan) is plan

    def test_idempotent(self):
        plan = {"entities": {
            "Bay": {"schedulable_by": "resource", "fields": [
                {"name": "ownerId", "role": "domain",
                 "user_fk_role": "actor",
                 "semantic": {"control": "Select"}}
            ]},
        }}
        import copy
        once = _sanitize_column_semantics(copy.deepcopy(plan))
        twice = _sanitize_column_semantics(copy.deepcopy(once))
        assert once == twice


# ── wiring: sanitizer runs inside _annotate_page_types ────────────────

class TestAnnotationWiring:
    def test_annotate_scrubs_out_of_set_values(self):
        # A plan with an invalid schedulable_by should have it stripped
        # once _annotate_page_types runs — the sanitizer is chained in.
        plan = {
            "pages": [],
            "entities": {"Bay": {
                "schedulable_by": "totally-made-up",
                "fields": [
                    {"name": "operatorId", "user_fk_role": "captain"},
                    {"name": "ownerId",    "role": "adjudicator"},
                    {"name": "note",       "semantic": {"control": "Unicorn"}},
                ]
            }},
        }
        out = _annotate_page_types(plan)
        bay = out["entities"]["Bay"]
        assert "schedulable_by" not in bay
        assert "user_fk_role" not in bay["fields"][0]
        assert "role" not in bay["fields"][1]
        assert "control" not in bay["fields"][2]["semantic"]

    def test_annotate_preserves_valid_emissions(self):
        plan = {
            "pages": [],
            "entities": {"Bay": {
                "schedulable_by": "resource",
                "fields": [
                    {"name": "operatorId", "user_fk_role": "actor"},
                    {"name": "projectId",  "role": "domain"},
                    {"name": "tier",       "semantic": {"control": "Select",
                                                        "enum_values": ["a", "b"]}},
                ]
            }},
        }
        out = _annotate_page_types(plan)
        bay = out["entities"]["Bay"]
        assert bay["schedulable_by"] == "resource"
        assert bay["fields"][0]["user_fk_role"] == "actor"
        assert bay["fields"][1]["role"] == "domain"
        assert bay["fields"][2]["semantic"]["control"] == "Select"
        # sibling blob key preserved
        assert bay["fields"][2]["semantic"]["enum_values"] == ["a", "b"]

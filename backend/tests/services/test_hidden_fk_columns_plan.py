"""Integration test — `hidden_fk_columns` (via _entity_roles →
classify_registry) now loads plan.json from output_dir and honours
planner-authored `column.role` even when the registry projection didn't
carry the field forward.

Spec D W2 caller migration — this proves every downstream consumer of
`hidden_fk_columns` (form_scaffold, form_field_align, deterministic_pages,
crud_page_coverage, context_assembler, binding_contract) reads the plan
without needing to be individually modified.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.fk_semantics import hidden_fk_columns


def _write_registry(tmp: Path, entities: dict) -> None:
    (tmp / "registry.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8"
    )


def _write_plan(tmp: Path, entities: dict) -> None:
    p = tmp / "src" / "contracts" / "plan.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"entities": entities}), encoding="utf-8")


class TestPlanAuthoredHiddenFk:
    def test_plan_actor_hides_column_registry_left_plain(self, tmp_path):
        # Registry says `ownerRefId` is a plain field (no fk, no role,
        # name-regex misses it) → default 'plain' → would NOT be hidden.
        # But plan says it's an actor column → auto-filled server-side,
        # must be hidden from the form.
        _write_registry(tmp_path, {"Task": {"fields": {"ownerRefId": {}}}})
        _write_plan(tmp_path, {"Task": {"fields": [
            {"name": "ownerRefId", "role": "actor"},
        ]}})
        hidden = hidden_fk_columns("Task", {"entities": {"Task": {"fields": {"ownerRefId": {}}}}},
                                   output_dir=str(tmp_path))
        assert "ownerrefid" in hidden

    def test_plan_domain_keeps_column_visible_even_if_name_looks_actor(self, tmp_path):
        # `createdById` name → legacy classifier marks it 'actor' (hidden).
        # Plan says it's a domain FK → must stay visible (needs a Select).
        _write_registry(tmp_path, {"Task": {"fields": {"createdById": {}}}})
        _write_plan(tmp_path, {"Task": {"fields": [
            {"name": "createdById", "role": "domain"},
        ]}})
        hidden = hidden_fk_columns("Task", {"entities": {"Task": {"fields": {"createdById": {}}}}},
                                   output_dir=str(tmp_path))
        assert "createdbyid" not in hidden

    def test_no_plan_falls_back_to_regex(self, tmp_path):
        # No plan file → legacy name-regex classifier still fires.
        _write_registry(tmp_path, {"Task": {"fields": {"createdById": {}}}})
        hidden = hidden_fk_columns("Task", {"entities": {"Task": {"fields": {"createdById": {}}}}},
                                   output_dir=str(tmp_path))
        # createdBy name → actor → hidden.
        assert "createdbyid" in hidden

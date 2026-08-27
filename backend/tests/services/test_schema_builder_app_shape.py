"""Tests for M3-T6: schema_builder reads plan.app_shape.data.denormalization.

The substrate's data.denormalization primitive drives whether Drizzle FK columns
get a sibling `*Name` varchar snapshot column.

  none        → no denorm columns (current behavior — default when no shape)
  moderate    → denorm ONLY for FK→User (highest-value display case)
  aggressive  → denorm for every FK
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.schema_builder import (
    _denorm_column_name,
    _denorm_mode_from_plan,
    _should_emit_denorm,
    build_schema_files,
)


# ══════════════════════════════════════════════════════════════════
# _denorm_mode_from_plan — the pure reader
# ══════════════════════════════════════════════════════════════════


class TestDenormModeFromPlan:
    def test_returns_none_when_plan_missing(self):
        assert _denorm_mode_from_plan(None) == "none"
        assert _denorm_mode_from_plan({}) == "none"
        assert _denorm_mode_from_plan("plan?") == "none"

    def test_returns_none_when_shape_missing(self):
        assert _denorm_mode_from_plan({"industry": "x"}) == "none"

    def test_returns_none_when_data_missing(self):
        assert _denorm_mode_from_plan({"app_shape": {"auth": {}}}) == "none"

    def test_translates_all_three_modes(self):
        for mode in ("none", "moderate", "aggressive"):
            plan = {"app_shape": {"data": {"denormalization": mode}}}
            assert _denorm_mode_from_plan(plan) == mode

    def test_unknown_mode_defaults_to_none(self):
        # LLM emits a value not in the vocabulary → don't crash, don't denorm.
        plan = {"app_shape": {"data": {"denormalization": "extreme"}}}
        assert _denorm_mode_from_plan(plan) == "none"


# ══════════════════════════════════════════════════════════════════
# _denorm_column_name — sibling naming
# ══════════════════════════════════════════════════════════════════


class TestDenormColumnName:
    def test_strips_id_suffix_and_adds_name(self):
        assert _denorm_column_name("assigneeId") == "assigneeName"
        assert _denorm_column_name("projectId") == "projectName"
        assert _denorm_column_name("ownerId") == "ownerName"

    def test_strips_snake_id_suffix(self):
        assert _denorm_column_name("user_id") == "user_name"

    def test_appends_name_when_no_id_suffix(self):
        assert _denorm_column_name("owner") == "ownerName"
        assert _denorm_column_name("author") == "authorName"

    def test_short_names_dont_lose_letters(self):
        # 2-char string "Id" doesn't get stripped to empty
        assert _denorm_column_name("Id") == "IdName"


# ══════════════════════════════════════════════════════════════════
# _should_emit_denorm — mode + target policy
# ══════════════════════════════════════════════════════════════════


class TestShouldEmitDenorm:
    def test_none_mode_never_emits(self):
        assert _should_emit_denorm("none", "User") is False
        assert _should_emit_denorm("none", "Order") is False

    def test_moderate_mode_only_user(self):
        assert _should_emit_denorm("moderate", "User") is True
        assert _should_emit_denorm("moderate", "Order") is False
        assert _should_emit_denorm("moderate", "Project") is False

    def test_aggressive_mode_all_entities(self):
        assert _should_emit_denorm("aggressive", "User") is True
        assert _should_emit_denorm("aggressive", "Order") is True
        assert _should_emit_denorm("aggressive", "AnythingElse") is True


# ══════════════════════════════════════════════════════════════════
# build_schema_files — end-to-end file emission with FKs
# ══════════════════════════════════════════════════════════════════


def _plan_with_project_and_task(mode: str | None):
    """Two entities: Project (name) + Task (title, assignee→User, project→Project).

    Task has TWO FKs — one to User, one to Project — so we can prove the
    moderate policy (User only) vs aggressive (both).
    """
    plan = {
        "data_models": [
            {
                "name": "Project",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "name", "type": "varchar", "notNull": True},
                ],
            },
            {
                "name": "Task",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "title", "type": "varchar", "notNull": True},
                    {"name": "assigneeId", "type": "uuid"},
                    {"name": "projectId", "type": "uuid"},
                ],
            },
        ],
        "relations": [
            {"from": "Task", "to": "Project", "foreignKey": "projectId", "type": "many-to-one"},
            # User is auth-reserved so we register the FK via registry columns below,
            # but the moderate/aggressive logic only needs the FK map, which
            # build_schema_files fills from the registry.
        ],
    }
    if mode is not None:
        plan["app_shape"] = {"data": {"denormalization": mode}}
    return plan


def _plan_with_user_fk(mode: str | None):
    """Task with assigneeId FK to User — the moderate-mode denorm case."""
    plan = {
        "data_models": [
            {
                "name": "Task",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "title", "type": "varchar", "notNull": True},
                    {"name": "assigneeId", "type": "uuid"},
                ],
            },
        ],
        "relations": [],
    }
    # Registry-column path for User FK (User is a reserved auth entity).
    # We craft a synthetic registry that pins assigneeId → User.
    if mode is not None:
        plan["app_shape"] = {"data": {"denormalization": mode}}
    return plan


def _read(tmp_path, slug):
    return (tmp_path / "src" / "db" / "schema" / f"{slug}.ts").read_text(encoding="utf-8")


class TestBuildSchemaFilesDenorm:
    def test_no_shape_no_denorm_columns(self, tmp_path):
        # Backwards compatibility: apps without app_shape emit exactly what they
        # emitted before this task.
        result = build_schema_files(_plan_with_project_and_task(None), str(tmp_path))
        assert result["errors"] == []
        content = _read(tmp_path, "tasks")
        assert "projectName" not in content
        assert "assigneeName" not in content

    def test_none_mode_no_denorm_columns(self, tmp_path):
        result = build_schema_files(_plan_with_project_and_task("none"), str(tmp_path))
        assert result["errors"] == []
        content = _read(tmp_path, "tasks")
        assert "projectName" not in content
        assert "assigneeName" not in content

    def test_aggressive_mode_emits_denorm_for_every_fk(self, tmp_path):
        result = build_schema_files(_plan_with_project_and_task("aggressive"), str(tmp_path))
        assert result["errors"] == []
        content = _read(tmp_path, "tasks")
        # projectId FK → projectName denorm sibling
        assert 'projectName: varchar("project_name", { length: 255 })' in content
        # Order in file: FK column first, then denorm sibling right after
        proj_id_pos = content.find("projectId:")
        proj_name_pos = content.find("projectName:")
        assert proj_id_pos < proj_name_pos < content.find("createdAt:")

    def test_aggressive_mode_imports_varchar(self, tmp_path):
        result = build_schema_files(_plan_with_project_and_task("aggressive"), str(tmp_path))
        assert result["errors"] == []
        content = _read(tmp_path, "tasks")
        # varchar builder must be imported for the sibling column
        assert '"drizzle-orm/pg-core"' in content
        # Grab the import line
        import_line = next(l for l in content.splitlines() if l.startswith("import {") and "pg-core" in l)
        assert "varchar" in import_line

    def test_moderate_mode_skips_non_user_fks(self, tmp_path):
        # Task→Project FK: with moderate mode, we do NOT emit projectName
        # because Project is not User.
        result = build_schema_files(_plan_with_project_and_task("moderate"), str(tmp_path))
        assert result["errors"] == []
        content = _read(tmp_path, "tasks")
        assert "projectName" not in content

    def test_declared_denorm_column_not_duplicated(self, tmp_path):
        # If the entity already declared projectName, don't emit a second one.
        plan = _plan_with_project_and_task("aggressive")
        plan["data_models"][1]["fields"].append(
            {"name": "projectName", "type": "varchar"}
        )
        result = build_schema_files(plan, str(tmp_path))
        assert result["errors"] == []
        content = _read(tmp_path, "tasks")
        # projectName appears exactly once
        assert content.count("projectName:") == 1


# ══════════════════════════════════════════════════════════════════
# End-to-end: Snap2App-shape (aggressive) vs enterprise (none)
# ══════════════════════════════════════════════════════════════════


class TestShapeEndToEnd:
    def test_snap2app_aggressive_denorms(self, tmp_path):
        snap2app_plan = {
            "app_shape": {
                "layout": {"shell": "none", "hero": "full-bleed-gradient",
                           "primaryInteraction": "capture", "density": "spacious"},
                "auth": {"surface": "modal", "gating": "on-action"},
                "nav": {"menu": "none", "back": "history"},
                "workflows": {"executionMode": "fire-and-forget"},
                "data": {"readShape": "list", "denormalization": "aggressive"},
                "identity": {"usageMode": "single-session"},
            },
            "data_models": [
                {
                    "name": "ScanSession",
                    "fields": [
                        {"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "label", "type": "varchar"},
                    ],
                },
                {
                    "name": "PriceResult",
                    "fields": [
                        {"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "value", "type": "decimal"},
                        {"name": "scanSessionId", "type": "uuid"},
                    ],
                },
            ],
            "relations": [
                {"from": "PriceResult", "to": "ScanSession",
                 "foreignKey": "scanSessionId", "type": "many-to-one"},
            ],
        }
        result = build_schema_files(snap2app_plan, str(tmp_path))
        assert result["errors"] == []
        content = _read(tmp_path, "price-results")
        # aggressive denorm — PriceResult.scanSessionId → scanSessionName
        assert 'scanSessionName: varchar("scan_session_name"' in content

    def test_enterprise_none_no_denorms(self, tmp_path):
        # Workspace-shape enterprise app: denormalization=none, no siblings.
        workspace_plan = {
            "app_shape": {
                "layout": {"shell": "sidebar", "hero": "none",
                           "primaryInteraction": "data-grid", "density": "comfortable"},
                "auth": {"surface": "route", "gating": "on-load"},
                "nav": {"menu": "sidebar-links", "back": "crumb"},
                "workflows": {"executionMode": "await-with-progress"},
                "data": {"readShape": "list", "denormalization": "none"},
                "identity": {"usageMode": "multi-user-team"},
            },
            "data_models": [
                {
                    "name": "Project",
                    "fields": [
                        {"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "name", "type": "varchar"},
                    ],
                },
                {
                    "name": "Task",
                    "fields": [
                        {"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "title", "type": "varchar"},
                        {"name": "projectId", "type": "uuid"},
                    ],
                },
            ],
            "relations": [
                {"from": "Task", "to": "Project",
                 "foreignKey": "projectId", "type": "many-to-one"},
            ],
        }
        result = build_schema_files(workspace_plan, str(tmp_path))
        assert result["errors"] == []
        content = _read(tmp_path, "tasks")
        assert "projectName" not in content

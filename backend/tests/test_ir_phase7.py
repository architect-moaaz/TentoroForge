"""Phase 7 tests — new patterns, themes, export, migration."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ir_adapter import plan_to_app_spec
from services.ir_compiler import generate_and_compile, save_ir, load_ir, write_compiled_files
from services.ir_export import eject_from_ir, export_ir
from services.ir_migrate import migrate_to_ir


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

KANBAN_PLAN = {
    "module_name": "TaskBoard",
    "data_models": [{
        "name": "Task",
        "fields": [
            {"name": "id", "type": "String", "primaryKey": True},
            {"name": "title", "type": "String", "nullable": False},
            {"name": "description", "type": "Text"},
            {"name": "status", "type": "Enum", "enum_values": ["todo", "in_progress", "review", "done"]},
            {"name": "priority", "type": "Enum", "enum_values": ["low", "medium", "high"]},
            {"name": "dueDate", "type": "Date"},
        ],
    }],
    "api_routes": [
        {"method": "GET", "path": "/api/tasks", "entity": "Task"},
        {"method": "POST", "path": "/api/tasks", "entity": "Task"},
        {"method": "GET", "path": "/api/tasks/{id}", "entity": "Task"},
        {"method": "DELETE", "path": "/api/tasks/{id}", "entity": "Task"},
    ],
    "pages": [],
    "relations": [],
}

ACTIVITY_LOG_PLAN = {
    "module_name": "AuditTrail",
    "data_models": [{
        "name": "ActivityLog",
        "fields": [
            {"name": "id", "type": "String", "primaryKey": True},
            {"name": "action", "type": "String", "nullable": False},
            {"name": "actor", "type": "String"},
            {"name": "timestamp", "type": "DateTime"},
            {"name": "details", "type": "Text"},
        ],
    }],
    "api_routes": [
        {"method": "GET", "path": "/api/activity-logs", "entity": "ActivityLog"},
    ],
    "pages": [],
    "relations": [],
}


# ---------------------------------------------------------------------------
# New pattern tests
# ---------------------------------------------------------------------------

class TestNewPatterns:
    """Test new patterns compile successfully."""

    @pytest.mark.asyncio
    async def test_kanban_entity_compiles(self):
        """Task with kanban capability should compile."""
        spec = plan_to_app_spec(KANBAN_PLAN)
        # Add kanban capability
        for entity in spec["entities"]:
            if entity["name"] == "Task":
                entity["capabilities"].append("kanban")

        result = await generate_and_compile(spec)
        assert len(result["errors"]) == 0
        assert len(result["files"]) > 0

    @pytest.mark.asyncio
    async def test_timeline_entity_compiles(self):
        """Temporal entity (ActivityLog) should compile."""
        spec = plan_to_app_spec(ACTIVITY_LOG_PLAN)
        result = await generate_and_compile(spec)
        assert len(result["errors"]) == 0
        assert len(result["files"]) > 0

    @pytest.mark.asyncio
    async def test_multi_entity_app_compiles(self):
        """App with multiple entities including kanban should compile."""
        plan = {
            **KANBAN_PLAN,
            "data_models": [
                *KANBAN_PLAN["data_models"],
                {
                    "name": "User",
                    "fields": [
                        {"name": "id", "type": "String", "primaryKey": True},
                        {"name": "name", "type": "String", "nullable": False},
                        {"name": "email", "type": "String"},
                        {"name": "avatar", "type": "String"},
                        {"name": "role", "type": "Enum", "enum_values": ["admin", "member"]},
                    ],
                },
            ],
            "api_routes": [
                *KANBAN_PLAN["api_routes"],
                {"method": "GET", "path": "/api/users", "entity": "User"},
                {"method": "POST", "path": "/api/users", "entity": "User"},
            ],
        }
        spec = plan_to_app_spec(plan)
        result = await generate_and_compile(spec)
        assert len(result["errors"]) == 0
        # Should have many pages: dashboard + task views + user views + auth
        assert len(result["ir"]["pages"]) >= 6


# ---------------------------------------------------------------------------
# Export/Eject tests
# ---------------------------------------------------------------------------

class TestExportEject:

    @pytest.mark.asyncio
    async def test_export_ir(self, tmp_path):
        """IR can be exported as JSON."""
        spec = plan_to_app_spec(KANBAN_PLAN)
        result = await generate_and_compile(spec)
        await save_ir(str(tmp_path), result["ir"])

        exported = export_ir(str(tmp_path))
        assert exported is not None
        assert exported["$schema"] == "tentoroforge/ir/1.0"
        assert "_export" in exported

    @pytest.mark.asyncio
    async def test_eject_removes_ir(self, tmp_path):
        """Eject strips boundaries and removes .ir directory."""
        spec = plan_to_app_spec(KANBAN_PLAN)
        result = await generate_and_compile(spec)

        # Write files with boundary markers
        await write_compiled_files(str(tmp_path), result["files"])
        await save_ir(str(tmp_path), result["ir"])

        # Inject boundary markers into a file for testing
        test_file = tmp_path / "src" / "test.tsx"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(
            '{/* @ir-node: 0 */}\n<div>Content</div>\n{/* @ir-end: 0 */}'
        )

        # Eject
        eject_result = await eject_from_ir(str(tmp_path))
        assert eject_result["ejected"] is True
        assert eject_result["ir_deleted"] is True
        assert eject_result["files_stripped"] >= 1

        # Verify .ir is gone
        assert not (tmp_path / ".ir").exists()

        # Verify boundaries are stripped
        content = test_file.read_text(encoding="utf-8")
        assert "@ir-node" not in content
        assert "@ir-end" not in content
        assert "Content" in content  # code preserved

    @pytest.mark.asyncio
    async def test_eject_on_non_ir_project(self, tmp_path):
        """Eject on project without IR should be a no-op."""
        result = await eject_from_ir(str(tmp_path))
        assert result["ejected"] is False


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------

class TestMigration:

    @pytest.mark.asyncio
    async def test_migrate_from_registry(self, tmp_path):
        """Migrate from an existing registry.json."""
        # Create a fake registry
        registry = {
            "entities": {
                "Task": {
                    "fields": {
                        "id": {"type": "String", "primaryKey": True},
                        "title": {"type": "String", "nullable": False},
                        "status": {"type": "Enum", "enum_values": ["todo", "done"]},
                    },
                },
            },
            "api_routes": {
                "GET /api/tasks": {"entity": "Task"},
                "POST /api/tasks": {"entity": "Task"},
            },
            "pages": {
                "/tasks": {"file": "src/app/tasks/page.tsx"},
            },
            "relations": [],
            "components": {},
        }
        (tmp_path / "registry.json").write_text(json.dumps(registry), encoding="utf-8")

        result = await migrate_to_ir(str(tmp_path))
        assert result["success"] is True
        assert result["entities_found"] >= 1
        assert result["pages_created"] >= 1

        # Verify IR was saved
        ir = load_ir(str(tmp_path))
        assert ir is not None

    @pytest.mark.asyncio
    async def test_migrate_no_registry(self, tmp_path):
        """Migration fails gracefully when no registry exists."""
        result = await migrate_to_ir(str(tmp_path))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Feature flag default
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    def test_ir_default_enabled(self):
        """IR frontend should be enabled by default."""
        from services.ir_pipeline import IR_FRONTEND_ENABLED
        assert IR_FRONTEND_ENABLED is True

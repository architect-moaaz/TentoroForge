"""End-to-end test for the IR pipeline: plan → AppSpec → IR → compiled files.

Tests the full flow that will run in the generate.py pipeline.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ir_adapter import plan_to_app_spec
from services.ir_compiler import (
    generate_and_compile,
    write_compiled_files,
    save_ir,
    load_ir,
)


# ---------------------------------------------------------------------------
# Realistic plan (what the planner agent would output)
# ---------------------------------------------------------------------------

TASK_MANAGER_PLAN = {
    "module_name": "TaskFlow",
    "description": "A project management tool for engineering teams",
    "data_models": [
        {
            "name": "Task",
            "fields": [
                {"name": "id", "type": "String", "primaryKey": True},
                {"name": "title", "type": "String", "nullable": False},
                {"name": "description", "type": "Text"},
                {"name": "status", "type": "Enum", "enum_values": ["todo", "in_progress", "review", "done"]},
                {"name": "priority", "type": "Enum", "enum_values": ["low", "medium", "high", "urgent"]},
                {"name": "assigneeId", "type": "String"},
                {"name": "dueDate", "type": "Date"},
                {"name": "tags", "type": "String"},
                {"name": "createdAt", "type": "DateTime"},
                {"name": "updatedAt", "type": "DateTime"},
            ],
            "indexes": ["title", "status"],
        },
        {
            "name": "Project",
            "fields": [
                {"name": "id", "type": "String", "primaryKey": True},
                {"name": "name", "type": "String", "nullable": False},
                {"name": "description", "type": "Text"},
                {"name": "thumbnail", "type": "Image"},
                {"name": "status", "type": "Enum", "enum_values": ["active", "completed", "archived"]},
                {"name": "createdAt", "type": "DateTime"},
            ],
        },
    ],
    "relations": [
        {"from": "Task", "to": "Project", "type": "many-to-one", "foreignKey": "projectId"},
    ],
    "api_routes": [
        {"method": "GET", "path": "/api/tasks", "entity": "Task"},
        {"method": "POST", "path": "/api/tasks", "entity": "Task"},
        {"method": "GET", "path": "/api/tasks/{id}", "entity": "Task"},
        {"method": "PUT", "path": "/api/tasks/{id}", "entity": "Task"},
        {"method": "DELETE", "path": "/api/tasks/{id}", "entity": "Task"},
        {"method": "GET", "path": "/api/projects", "entity": "Project"},
        {"method": "POST", "path": "/api/projects", "entity": "Project"},
        {"method": "GET", "path": "/api/projects/{id}", "entity": "Project"},
        {"method": "DELETE", "path": "/api/projects/{id}", "entity": "Project"},
    ],
    "pages": [
        {"route": "/tasks", "name": "Tasks", "description": "Browse tasks"},
        {"route": "/tasks/new", "name": "New Task", "description": "Create a task"},
        {"route": "/projects", "name": "Projects", "description": "Browse projects"},
    ],
    "workflows": [],
}


@pytest.fixture
def output_dir():
    """Create a temporary output directory for tests."""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


class TestIREndToEnd:
    """End-to-end integration tests."""

    def test_plan_to_spec_conversion(self):
        """Plan JSON converts to valid AppSpec."""
        spec = plan_to_app_spec(TASK_MANAGER_PLAN)

        assert spec["name"] == "TaskFlow"
        assert len(spec["entities"]) == 2

        task = next(e for e in spec["entities"] if e["name"] == "Task")
        assert "list" in task["capabilities"]
        assert "create" in task["capabilities"]
        assert any(f["name"] == "title" for f in task["fields"])
        assert any(f["type"] == "enum" for f in task["fields"])

    @pytest.mark.asyncio
    async def test_full_pipeline(self, output_dir):
        """Full pipeline: plan → spec → IR → compile → write files."""
        # Step 1: Convert plan
        spec = plan_to_app_spec(TASK_MANAGER_PLAN)

        # Step 2+3: Generate IR and compile
        result = await generate_and_compile(spec)

        assert "ir" in result
        assert "files" in result
        assert len(result["errors"]) == 0

        ir = result["ir"]
        files = result["files"]

        # Verify IR structure
        assert ir["$schema"] == "tentoroforge/ir/1.0"
        assert ir["app"]["name"] == "TaskFlow"
        assert len(ir["pages"]) >= 5  # dashboard + entity pages + auth
        assert len(ir["dataSources"]) >= 5  # CRUD sources + dashboard + auth

        # Verify files generated
        assert len(files) >= 5
        # Should have page files
        page_files = [p for p in files if p.endswith("page.tsx")]
        assert len(page_files) >= 4

        # Step 4: Write files
        written = await write_compiled_files(output_dir, files)
        assert len(written) > 0

        # Verify files on disk
        for rel_path in written:
            full_path = os.path.join(output_dir, rel_path)
            assert os.path.exists(full_path), f"Expected file: {full_path}"
            content = Path(full_path).read_text()
            assert len(content) > 50

        # Step 5: Save IR
        ir_path = await save_ir(output_dir, ir)
        assert os.path.exists(ir_path)

        # Verify IR can be loaded back
        loaded = load_ir(output_dir)
        assert loaded is not None
        assert loaded["$schema"] == ir["$schema"]
        assert len(loaded["pages"]) == len(ir["pages"])

    @pytest.mark.asyncio
    async def test_compiled_code_quality(self, output_dir):
        """Verify the compiled code has expected patterns."""
        spec = plan_to_app_spec(TASK_MANAGER_PLAN)
        result = await generate_and_compile(spec)
        files = result["files"]

        # Check dashboard
        dash = next((c for p, c in files.items() if "dashboard" in p), None)
        assert dash is not None
        assert '"use client"' in dash
        assert "useState" in dash or "useQuery" in dash

        # Check login page
        login = next((c for p, c in files.items() if "login" in p), None)
        assert login is not None
        assert "email" in login.lower()
        assert "password" in login.lower()

    @pytest.mark.asyncio
    async def test_ir_persistence(self, output_dir):
        """IR files persist and can be reloaded."""
        spec = plan_to_app_spec(TASK_MANAGER_PLAN)
        result = await generate_and_compile(spec)
        ir = result["ir"]

        await save_ir(output_dir, ir)

        # Check manifest
        manifest_path = os.path.join(output_dir, ".ir", "manifest.json")
        assert os.path.exists(manifest_path)

        # Check per-page files
        pages_dir = os.path.join(output_dir, ".ir", "pages")
        assert os.path.exists(pages_dir)
        page_files = os.listdir(pages_dir)
        assert len(page_files) == len(ir["pages"])

        # Reload and verify
        loaded = load_ir(output_dir)
        assert loaded["app"]["name"] == "TaskFlow"

    @pytest.mark.asyncio
    async def test_minimal_plan(self, output_dir):
        """Handles minimal plan with single entity."""
        minimal_plan = {
            "module_name": "Tags",
            "description": "Tag manager",
            "data_models": [
                {
                    "name": "Tag",
                    "fields": [
                        {"name": "id", "type": "String", "primaryKey": True},
                        {"name": "name", "type": "String", "nullable": False},
                        {"name": "color", "type": "String"},
                    ],
                }
            ],
            "api_routes": [
                {"method": "GET", "path": "/api/tags", "entity": "Tag"},
                {"method": "POST", "path": "/api/tags", "entity": "Tag"},
            ],
            "pages": [],
            "relations": [],
        }

        spec = plan_to_app_spec(minimal_plan)
        result = await generate_and_compile(spec)

        assert len(result["errors"]) == 0
        assert len(result["files"]) >= 3  # dashboard + tag list + auth pages

        written = await write_compiled_files(output_dir, result["files"])
        assert len(written) > 0

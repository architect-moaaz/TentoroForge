"""Tests for IR agent components — router, edit operations, QA, Figma extraction."""

import json
import os
import sys
import asyncio
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.ir_router import should_use_ir_edit, _apply_operation, _get_node, _infer_target_page
from agents.ir_edit_agent import extract_ir_operations
from agents.ir_qa_agent import run_ir_qa, _validate_ir_structure, _auto_fix_ir
from agents.figma_ir_agent import extract_page_ir


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_IR = {
    "$schema": "tentoroforge/ir/1.0",
    "app": {"name": "Test App"},
    "tokens": {},
    "dataSources": {
        "tasks": {"type": "rest", "method": "GET", "path": "/api/tasks"},
        "createTask": {"type": "rest", "method": "POST", "path": "/api/tasks"},
    },
    "pages": [
        {
            "$id": "task-list",
            "route": "/tasks",
            "title": "Tasks",
            "state": {"search": ""},
            "root": {
                "node": "Stack",
                "gap": "lg",
                "padding": "lg",
                "children": [
                    {
                        "node": "Row",
                        "justify": "between",
                        "children": [
                            {"node": "Text", "content": "Tasks", "typography": "heading-2"},
                            {"node": "Button", "label": "New Task", "variant": "primary"},
                        ],
                    },
                    {
                        "node": "DataTable",
                        "data": "source:tasks",
                        "columns": [
                            {"field": "title", "header": "Title"},
                            {"field": "status", "header": "Status", "render": "badge"},
                        ],
                    },
                ],
            },
        },
        {
            "$id": "dashboard",
            "route": "/dashboard",
            "title": "Dashboard",
            "state": {},
            "root": {
                "node": "Stack",
                "children": [
                    {"node": "Text", "content": "Dashboard", "typography": "heading-1"},
                ],
            },
        },
        {
            "$id": "login",
            "route": "/login",
            "title": "Sign In",
            "state": {},
            "root": {
                "node": "Stack",
                "children": [
                    {"node": "Text", "content": "Welcome back", "typography": "heading-1"},
                ],
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# IR Router tests
# ---------------------------------------------------------------------------

class TestShouldUseIREdit:
    """Test the routing decision logic."""

    def _make_ir_dir(self, tmpdir):
        """Create a temp dir with IR manifest."""
        ir_dir = Path(tmpdir) / ".ir"
        ir_dir.mkdir()
        (ir_dir / "manifest.json").write_text(json.dumps(SAMPLE_IR))
        return tmpdir

    def test_ui_change_routes_to_ir(self, tmp_path):
        """UI-focused changes should use IR edit."""
        d = self._make_ir_dir(str(tmp_path))
        assert should_use_ir_edit("Change the heading text to My Tasks", d, "REFINE") is True
        assert should_use_ir_edit("Make the button bigger", d, "REFINE") is True
        assert should_use_ir_edit("Add a search input above the table", d, "REFINE") is True
        assert should_use_ir_edit("Change the color to red", d, "REFINE") is True

    def test_code_change_bypasses_ir(self, tmp_path):
        """Code-focused changes should bypass IR."""
        d = self._make_ir_dir(str(tmp_path))
        assert should_use_ir_edit("Add a new API endpoint for user preferences", d, "REFINE") is False
        assert should_use_ir_edit("Refactor the auth middleware to support OAuth", d, "REFINE") is False

    def test_non_refine_bypasses_ir(self, tmp_path):
        """Non-REFINE intents should not use IR."""
        d = self._make_ir_dir(str(tmp_path))
        assert should_use_ir_edit("Build a task manager", d, "PLAN") is False
        assert should_use_ir_edit("How does auth work?", d, "EXPLAIN") is False

    def test_no_ir_bypasses(self, tmp_path):
        """Projects without IR should not use IR edit."""
        assert should_use_ir_edit("Change the heading", str(tmp_path), "REFINE") is False


class TestApplyOperation:
    """Test in-place IR operation application."""

    def test_set_prop(self):
        import copy
        root = copy.deepcopy(SAMPLE_IR["pages"][0]["root"])
        _apply_operation(root, {"type": "setProp", "path": [0, 0], "prop": "content", "value": "My Tasks"})
        assert root["children"][0]["children"][0]["content"] == "My Tasks"

    def test_add_child(self):
        import copy
        root = copy.deepcopy(SAMPLE_IR["pages"][0]["root"])
        _apply_operation(root, {
            "type": "addChild", "path": [0], "index": 2,
            "node": {"node": "Badge", "content": "New"},
        })
        assert len(root["children"][0]["children"]) == 3
        assert root["children"][0]["children"][2]["node"] == "Badge"

    def test_remove_child(self):
        import copy
        root = copy.deepcopy(SAMPLE_IR["pages"][0]["root"])
        _apply_operation(root, {"type": "removeChild", "path": [0], "index": 1})
        assert len(root["children"][0]["children"]) == 1

    def test_duplicate(self):
        import copy
        root = copy.deepcopy(SAMPLE_IR["pages"][0]["root"])
        original_count = len(root["children"])
        _apply_operation(root, {"type": "duplicate", "path": [0]})
        assert len(root["children"]) == original_count + 1

    def test_wrap_with(self):
        import copy
        root = copy.deepcopy(SAMPLE_IR["pages"][0]["root"])
        _apply_operation(root, {
            "type": "wrapWith", "path": [1],
            "wrapper": {"node": "Card", "padding": "md"},
        })
        assert root["children"][1]["node"] == "Card"
        assert root["children"][1]["children"][0]["node"] == "DataTable"

    def test_unwrap(self):
        import copy
        root = copy.deepcopy(SAMPLE_IR["pages"][0]["root"])
        # First wrap, then unwrap — should be back to original
        original_node = root["children"][1]["node"]
        _apply_operation(root, {
            "type": "wrapWith", "path": [1],
            "wrapper": {"node": "Card"},
        })
        assert root["children"][1]["node"] == "Card"
        _apply_operation(root, {"type": "unwrap", "path": [1]})
        assert root["children"][1]["node"] == original_node


class TestInferTargetPage:
    """Test page inference from user messages."""

    def test_infer_by_title(self):
        page = _infer_target_page(SAMPLE_IR, "Change the Tasks heading")
        assert page is not None
        assert page["$id"] == "task-list"

    def test_infer_by_route_keyword(self):
        page = _infer_target_page(SAMPLE_IR, "Update the dashboard")
        assert page is not None
        assert page["$id"] == "dashboard"

    def test_infer_login(self):
        page = _infer_target_page(SAMPLE_IR, "Fix the login page")
        assert page is not None
        assert page["$id"] == "login"

    def test_no_match_returns_none(self):
        page = _infer_target_page(SAMPLE_IR, "Do something generic")
        assert page is None


# ---------------------------------------------------------------------------
# IR Edit Agent — operation extraction
# ---------------------------------------------------------------------------

class TestExtractIROperations:
    """Test parsing IR operations from agent text output."""

    def test_extract_from_ir_ops_block(self):
        text = """Here are the operations:

```ir-ops
[
  { "type": "setProp", "path": [0, 0], "prop": "content", "value": "Updated" }
]
```
"""
        ops = extract_ir_operations(text)
        assert ops is not None
        assert len(ops) == 1
        assert ops[0]["type"] == "setProp"
        assert ops[0]["value"] == "Updated"

    def test_extract_multiple_operations(self):
        text = """```ir-ops
[
  { "type": "setProp", "path": [0, 0], "prop": "content", "value": "New Title" },
  { "type": "addChild", "path": [0], "index": 2, "node": { "node": "Badge", "content": "New" } }
]
```"""
        ops = extract_ir_operations(text)
        assert ops is not None
        assert len(ops) == 2

    def test_extract_from_bare_json(self):
        text = '[{ "type": "setProp", "path": [0], "prop": "gap", "value": "xl" }]'
        ops = extract_ir_operations(text)
        assert ops is not None
        assert len(ops) == 1

    def test_returns_none_for_no_ops(self):
        text = "I'm not sure how to help with that."
        ops = extract_ir_operations(text)
        assert ops is None

    def test_returns_none_for_invalid_json(self):
        text = "```ir-ops\n{invalid json}\n```"
        ops = extract_ir_operations(text)
        assert ops is None


# ---------------------------------------------------------------------------
# Figma IR extraction
# ---------------------------------------------------------------------------

class TestExtractPageIR:
    """Test parsing page IR from Figma agent output."""

    def test_extract_from_ir_page_block(self):
        text = """Here's the IR for your design:

```ir-page
{
  "$id": "landing",
  "route": "/",
  "title": "Landing Page",
  "state": {},
  "root": {
    "node": "Stack",
    "gap": "xl",
    "children": [
      { "node": "Text", "content": "Welcome", "typography": "heading-1" }
    ]
  }
}
```
"""
        ir = extract_page_ir(text)
        assert ir is not None
        assert ir["$id"] == "landing"
        assert ir["root"]["node"] == "Stack"

    def test_returns_none_for_no_ir(self):
        ir = extract_page_ir("Here's some general text without IR.")
        assert ir is None


# ---------------------------------------------------------------------------
# IR QA Agent
# ---------------------------------------------------------------------------

class TestIRQA:
    """Test IR-aware QA validation and auto-fix."""

    def test_valid_ir_passes(self):
        errors = _validate_ir_structure(SAMPLE_IR)
        critical = [e for e in errors if e["severity"] == "error"]
        assert len(critical) == 0

    def test_missing_schema_detected(self):
        ir = {**SAMPLE_IR, "$schema": None}
        errors = _validate_ir_structure(ir)
        assert any("$schema" in e["message"] for e in errors)

    def test_duplicate_page_id_detected(self):
        ir = {
            **SAMPLE_IR,
            "pages": [
                {"$id": "same", "route": "/a", "root": {"node": "Stack", "children": []}},
                {"$id": "same", "route": "/b", "root": {"node": "Stack", "children": []}},
            ],
        }
        errors = _validate_ir_structure(ir)
        assert any("Duplicate page ID" in e["message"] for e in errors)

    def test_missing_root_detected(self):
        ir = {
            **SAMPLE_IR,
            "pages": [{"$id": "broken", "route": "/broken"}],
        }
        errors = _validate_ir_structure(ir)
        assert any("missing root" in e["message"] for e in errors)

    def test_auto_fix_missing_schema(self):
        ir = {"app": {"name": "Test"}, "pages": [], "dataSources": {}, "tokens": {}}
        fixes = _auto_fix_ir(ir)
        assert "$schema" in ir
        assert len(fixes) > 0

    def test_auto_fix_missing_children(self):
        ir = {
            "$schema": "tentoroforge/ir/1.0",
            "app": {"name": "Test"},
            "tokens": {},
            "dataSources": {},
            "pages": [{
                "$id": "test",
                "route": "/test",
                "root": {"node": "Stack"},  # missing children
            }],
        }
        fixes = _auto_fix_ir(ir)
        assert "children" in ir["pages"][0]["root"]
        assert any("children" in f for f in fixes)

    @pytest.mark.asyncio
    async def test_full_qa_pipeline(self):
        """Full QA with compilation (needs Node.js packages built)."""
        import copy
        ir = copy.deepcopy(SAMPLE_IR)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = await run_ir_qa(tmpdir, ir)
            assert result["valid"] is True
            assert len(result["errors"]) == 0

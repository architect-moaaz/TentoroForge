"""IR-aware QA Agent — validates IR and compiled output.

Replaces the build-and-fix loop with structured validation:
1. Validate IR schema (instant, no LLM)
2. Compile IR (instant, no LLM)
3. If errors exist, classify and fix structurally
4. Only use LLM for fixes that require intelligence (Custom node repairs)
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_ir_qa(
    output_dir: str,
    ir: dict[str, Any],
) -> dict[str, Any]:
    """Run IR-aware quality assurance.

    Returns:
        Dict with:
        - "valid": bool — whether the IR is valid and compiles
        - "errors": list of error descriptions
        - "warnings": list of warning descriptions
        - "fixes_applied": list of auto-fixes that were applied
        - "ir": the (potentially fixed) IR
    """
    from services.ir_compiler import compile_ir, save_ir, write_compiled_files

    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "fixes_applied": [],
        "ir": ir,
    }

    # ── Step 1: Structural validation ──
    validation_errors = _validate_ir_structure(ir)
    for err in validation_errors:
        if err["severity"] == "error":
            result["errors"].append(err["message"])
            result["valid"] = False
        else:
            result["warnings"].append(err["message"])

    # ── Step 2: Report issues (no auto-fix — agents are responsible) ──
    if not result["valid"]:
        result["fixes_applied"] = []
        if True:
            remaining_errors = [e for e in errors if e["severity"] == "error"]
            if not remaining_errors:
                result["valid"] = True
                result["errors"] = []
                logger.info("IR auto-fixed: %s", ", ".join(fixes))

    # ── Step 3: Compile ──
    if result["valid"]:
        try:
            compile_result = await compile_ir(ir)
            if compile_result.get("errors"):
                result["errors"].extend(compile_result["errors"])
                result["valid"] = False
            else:
                result["warnings"].extend(compile_result.get("warnings", []))

                # Write files
                files = compile_result.get("files", {})
                if files:
                    await write_compiled_files(output_dir, files, src_prefix="src")
                    await save_ir(output_dir, ir)

        except Exception as e:
            result["errors"].append(f"Compilation failed: {str(e)}")
            result["valid"] = False

    return result


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------

def _validate_ir_structure(ir: dict) -> list[dict]:
    """Validate IR structure without calling the Node.js validator.

    Catches common issues that the Python side can detect.
    """
    errors = []

    if not ir.get("$schema"):
        errors.append({"severity": "error", "message": "Missing $schema"})

    if not ir.get("app", {}).get("name"):
        errors.append({"severity": "error", "message": "Missing app.name"})

    pages = ir.get("pages", [])
    if not pages:
        errors.append({"severity": "warning", "message": "No pages defined"})

    page_ids = set()
    routes = set()
    for i, page in enumerate(pages):
        pid = page.get("$id")
        if not pid:
            errors.append({"severity": "error", "message": f"Page {i} missing $id"})
        elif pid in page_ids:
            errors.append({"severity": "error", "message": f"Duplicate page ID: {pid}"})
        page_ids.add(pid)

        route = page.get("route")
        if not route:
            errors.append({"severity": "error", "message": f"Page {pid or i} missing route"})
        elif route in routes:
            errors.append({"severity": "error", "message": f"Duplicate route: {route}"})
        routes.add(route)

        root = page.get("root")
        if not root:
            errors.append({"severity": "error", "message": f"Page {pid or i} missing root node"})
        elif not root.get("node"):
            errors.append({"severity": "error", "message": f"Page {pid or i} root missing node type"})
        else:
            _validate_node_tree(root, f"pages[{i}].root", errors)

    # Validate data sources
    for name, ds in ir.get("dataSources", {}).items():
        if not ds.get("type"):
            errors.append({"severity": "error", "message": f"Data source '{name}' missing type"})
        if not ds.get("method"):
            errors.append({"severity": "error", "message": f"Data source '{name}' missing method"})
        if not ds.get("path"):
            errors.append({"severity": "error", "message": f"Data source '{name}' missing path"})

    return errors


def _validate_node_tree(node: dict, path: str, errors: list, depth: int = 0):
    """Recursively validate a node tree."""
    if depth > 30:
        errors.append({"severity": "warning", "message": f"{path}: tree depth exceeds 30"})
        return

    node_type = node.get("node")
    if not node_type:
        errors.append({"severity": "error", "message": f"{path}: missing node type"})
        return

    # Check required props
    required_map = {
        "Text": ["content"],
        "Button": ["label"],
        "TextInput": ["bind"],
        "TextArea": ["bind"],
        "Select": ["bind"],
        "Checkbox": ["bind"],
        "Toggle": ["bind"],
        "DataTable": ["data", "columns"],
        "Form": ["bind", "onSubmit"],
        "Image": ["src", "alt"],
        "EmptyState": ["message"],
        "Repeater": ["data", "template"],
        "Slider": ["min", "max"],
    }

    if node_type in required_map:
        for prop in required_map[node_type]:
            if prop not in node or node[prop] is None or node[prop] == "":
                errors.append({
                    "severity": "warning",
                    "message": f"{path}: {node_type} missing required prop '{prop}'",
                })

    # Recurse into children
    children = node.get("children")
    if isinstance(children, list):
        for i, child in enumerate(children):
            if isinstance(child, dict):
                _validate_node_tree(child, f"{path}.children[{i}]", errors, depth + 1)

    # Recurse into named slots
    for slot in ["template", "emptyState", "header", "footer", "loading", "error", "then", "else"]:
        slot_node = node.get(slot)
        if isinstance(slot_node, dict) and "node" in slot_node:
            _validate_node_tree(slot_node, f"{path}.{slot}", errors, depth + 1)

    # Recurse into cases
    cases = node.get("cases")
    if isinstance(cases, dict):
        for key, case_node in cases.items():
            if isinstance(case_node, dict) and "node" in case_node:
                _validate_node_tree(case_node, f"{path}.cases.{key}", errors, depth + 1)


# ---------------------------------------------------------------------------
# Auto-fix common issues
# ---------------------------------------------------------------------------

def _auto_fix_ir(ir: dict) -> list[str]:
    """Auto-fix deterministic IR issues. Returns list of fix descriptions."""
    fixes = []

    # Fix missing $schema
    if not ir.get("$schema"):
        ir["$schema"] = "tentoroforge/ir/1.0"
        fixes.append("Added missing $schema")

    # Fix missing app.name
    if not ir.get("app", {}).get("name"):
        if "app" not in ir:
            ir["app"] = {}
        ir["app"]["name"] = "My App"
        fixes.append("Added default app.name")

    # Fix pages
    for page in ir.get("pages", []):
        # Fix missing root
        if not page.get("root"):
            page["root"] = {"node": "Stack", "children": [{"node": "Text", "content": "Empty page"}]}
            fixes.append(f"Added default root to page '{page.get('$id', '?')}'")

        # Fix root missing node type
        elif not page["root"].get("node"):
            page["root"]["node"] = "Stack"
            if "children" not in page["root"]:
                page["root"]["children"] = []
            fixes.append(f"Fixed root node type for page '{page.get('$id', '?')}'")

        # Fix missing children on container nodes
        _fix_missing_children(page["root"], fixes)

    return fixes


def _fix_missing_children(node: dict, fixes: list):
    """Ensure container nodes have children arrays."""
    container_types = {"Stack", "Row", "Grid", "Card", "AsyncSlot", "ModalTrigger", "Form"}
    if node.get("node") in container_types and "children" not in node:
        node["children"] = []
        fixes.append(f"Added missing children array to {node['node']}")

    for child in node.get("children", []):
        if isinstance(child, dict):
            _fix_missing_children(child, fixes)

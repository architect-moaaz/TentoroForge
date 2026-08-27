"""IR Router — decides whether a user instruction should use IR edit or LLM code edit.

Sits between the orchestrator and the edit agents. When a project has IR
and the request is a UI change, routes to the IR edit agent instead of
the code refiner.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from services.ir_compiler import load_ir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# UI-related keywords that suggest an IR edit
# ---------------------------------------------------------------------------

UI_KEYWORDS = {
    # Direct component references
    "button", "text", "heading", "title", "label", "input", "form",
    "table", "card", "badge", "icon", "image", "avatar", "select",
    "checkbox", "toggle", "tabs", "modal", "chart", "divider",
    # Layout references
    "sidebar", "header", "footer", "grid", "column", "row", "stack",
    "layout", "spacing", "gap", "padding", "margin", "align", "center",
    # Style references
    "color", "font", "size", "bold", "italic", "style", "theme",
    "bigger", "smaller", "larger", "wider", "narrower",
    # Action references
    "move", "add", "remove", "delete", "change", "rename", "replace",
    "hide", "show", "reorder", "swap", "duplicate",
    # Page references
    "page", "screen", "view", "dashboard", "list", "detail", "form",
}

# Keywords that suggest code-level changes (NOT IR)
CODE_KEYWORDS = {
    "api", "endpoint", "route", "middleware", "auth", "database", "schema",
    "migration", "hook", "custom component", "animation", "transition",
    "performance", "optimization", "refactor", "import", "dependency",
    "package", "library", "server", "client-side", "ssr", "ssg",
}


def should_use_ir_edit(
    user_message: str,
    output_dir: str,
    intent: str,
) -> bool:
    """Determine if a request should use the IR edit path.

    Conditions:
    1. Project has IR (was generated via IR pipeline)
    2. Intent is REFINE (not PLAN, SCAFFOLD, etc.)
    3. Message is about UI changes (not backend/API/logic)

    Returns True if IR edit should be used.
    """
    # Only intercept REFINE intents
    if intent != "REFINE":
        return False

    # Check if project has IR
    ir = load_ir(output_dir)
    if ir is None:
        return False

    msg_lower = user_message.lower()

    # Check for code-level keywords that bypass IR
    code_score = sum(1 for kw in CODE_KEYWORDS if kw in msg_lower)
    if code_score >= 2:
        return False

    # Check for UI keywords that suggest IR edit
    ui_score = sum(1 for kw in UI_KEYWORDS if kw in msg_lower)

    # If strong UI signal, use IR
    if ui_score >= 2:
        return True

    # If weak signal, still use IR as default for projects with IR
    # (IR edit is faster and cheaper; falls back to code edit if needed)
    if ui_score >= 1:
        return True

    # Default: use IR for REFINE on IR projects unless clearly code-focused
    return code_score == 0


async def route_to_ir_edit(
    output_dir: str,
    user_message: str,
    page_id: str | None = None,
) -> dict[str, Any]:
    """Route a user instruction through the IR edit agent.

    Returns:
        Dict with:
        - "operations": list of IR operations to apply
        - "page_id": which page was edited
        - "success": whether operations were extracted
        - "response_text": the agent's response text (for chat display)
    """
    from agents.ir_edit_agent import run_ir_edit_agent, extract_ir_operations
    from services.ir_compiler import load_ir, save_ir, compile_ir, write_compiled_files
    from services.agent_messages import AssistantMessage, ResultMessage, TextBlock

    ir = load_ir(output_dir)
    if ir is None:
        return {"success": False, "response_text": "No IR found for this project."}

    # Determine which page to edit
    if page_id:
        page = next((p for p in ir["pages"] if p["$id"] == page_id), None)
    else:
        # Try to infer from the message
        page = _infer_target_page(ir, user_message)

    if page is None:
        page = ir["pages"][0] if ir["pages"] else None

    if page is None:
        return {"success": False, "response_text": "No pages in the IR to edit."}

    # Run the IR edit agent
    response_text = ""
    async for message in run_ir_edit_agent(
        page_ir=page,
        user_instruction=user_message,
        data_sources=ir.get("dataSources"),
    ):
        if isinstance(message, (AssistantMessage, ResultMessage)):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    response_text += block.text

    # Extract operations from response
    operations = extract_ir_operations(response_text)
    if not operations:
        return {
            "success": False,
            "page_id": page["$id"],
            "response_text": response_text,
            "operations": [],
        }

    # Apply operations to the IR
    for op in operations:
        _apply_operation(page["root"], op)

    # Save updated IR
    await save_ir(output_dir, ir)

    # Recompile
    try:
        result = await compile_ir(ir)
        if not result.get("errors"):
            await write_compiled_files(output_dir, result["files"], src_prefix="src")
    except Exception as e:
        logger.warning("IR recompile failed after edit: %s", e)

    return {
        "success": True,
        "page_id": page["$id"],
        "operations": operations,
        "response_text": f"Applied {len(operations)} IR operation(s) to page '{page['$id']}'.",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_target_page(ir: dict, message: str) -> dict | None:
    """Try to guess which page the user is referring to."""
    msg_lower = message.lower()

    for page in ir.get("pages", []):
        page_id = page.get("$id", "").lower()
        page_title = (page.get("title") or "").lower()
        page_route = (page.get("route") or "").lower()

        # Check if any page identifier appears in the message
        if page_id.replace("-", " ") in msg_lower:
            return page
        if page_title and page_title in msg_lower:
            return page
        if page_route.strip("/") in msg_lower:
            return page

    # Check for common keywords
    keyword_map = {
        "dashboard": "dashboard",
        "login": "login",
        "signup": "signup",
        "settings": "settings",
        "home": "dashboard",
    }
    for keyword, page_id_prefix in keyword_map.items():
        if keyword in msg_lower:
            match = next(
                (p for p in ir["pages"] if p["$id"].startswith(page_id_prefix)),
                None,
            )
            if match:
                return match

    return None


def _apply_operation(root: dict, op: dict) -> None:
    """Apply a single IR operation to a node tree (in-place)."""
    path = op.get("path", [])
    op_type = op["type"]

    if op_type == "setProp":
        node = _get_node(root, path)
        if node:
            node[op["prop"]] = op["value"]

    elif op_type == "addChild":
        parent = _get_node(root, path)
        if parent and "children" in parent:
            parent["children"].insert(op["index"], op["node"])

    elif op_type == "removeChild":
        parent = _get_node(root, path)
        if parent and "children" in parent:
            idx = op["index"]
            if 0 <= idx < len(parent["children"]):
                parent["children"].pop(idx)

    elif op_type == "replace":
        if not path:
            return
        parent = _get_node(root, path[:-1])
        if parent and "children" in parent:
            idx = path[-1]
            if 0 <= idx < len(parent["children"]):
                parent["children"][idx] = op["node"]

    elif op_type == "duplicate":
        if not path:
            return
        parent = _get_node(root, path[:-1])
        if parent and "children" in parent:
            idx = path[-1]
            if 0 <= idx < len(parent["children"]):
                import copy
                parent["children"].insert(idx + 1, copy.deepcopy(parent["children"][idx]))

    elif op_type == "wrapWith":
        if not path:
            return
        parent = _get_node(root, path[:-1])
        if parent and "children" in parent:
            idx = path[-1]
            child = parent["children"][idx]
            wrapper = dict(op["wrapper"])
            wrapper["children"] = [child]
            parent["children"][idx] = wrapper

    elif op_type == "unwrap":
        if not path:
            return
        parent = _get_node(root, path[:-1])
        if parent and "children" in parent:
            idx = path[-1]
            wrapper = parent["children"][idx]
            if "children" in wrapper:
                parent["children"][idx:idx+1] = wrapper["children"]


def _get_node(root: dict, path: list) -> dict | None:
    """Navigate to a node by path."""
    node = root
    for idx in path:
        children = node.get("children")
        if not isinstance(children, list) or idx >= len(children):
            return None
        node = children[idx]
    return node

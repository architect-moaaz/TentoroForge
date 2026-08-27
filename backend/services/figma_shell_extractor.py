"""Extract a recurring shell (top nav, sidebar) from a multi-page Figma
project and rewrite per-page schemas to use <PageOutlet/>.

Heuristic:
- Walk each page schema's root tree
- Identify the topmost subtree whose className or data-name suggests
  navigation (top bar / nav row containing nav-tab Buttons with
  navigate props in different routes)
- If the SAME subtree (structurally / by _figmaNodeId pattern) appears
  on multiple authenticated pages → it's the shell.
- Extract it as shell.json with a PageOutlet inserted where the page
  content was. Each page schema gets only its non-shell remainder.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Heuristic helpers
# ---------------------------------------------------------------------------

def _collect_nav_routes(n: Any, depth: int = 0, max_depth: int = 12) -> set[str]:
    """Collect all navigate routes from Button nodes up to max_depth hops."""
    routes: set[str] = set()
    if not isinstance(n, dict) or depth > max_depth:
        return routes
    if n.get("type") == "Button":
        nav = (n.get("props") or {}).get("navigate")
        if nav:
            routes.add(nav)
    for c in n.get("children") or []:
        routes.update(_collect_nav_routes(c, depth + 1, max_depth))
    return routes


def _is_nav_node(node: dict) -> bool:
    """Detect a nav bar: a Row/Stack/Container containing 2+ Buttons with
    distinct navigate props anywhere in its subtree."""
    if not isinstance(node, dict):
        return False
    if node.get("type") not in ("Row", "Stack", "Container"):
        return False
    return len(_collect_nav_routes(node)) >= 2


def _find_nav_subtree(schema: dict) -> tuple[list[int], dict] | None:
    """Find the nav bar as a direct child of the main page layout stack.

    Strategy: walk the tree looking for a node whose CHILDREN have one child
    that transitively contains ≥2 nav routes AND the other children don't.
    This identifies the "nav bar" as a sibling of the "page content" rather
    than returning the full-page wrapper.

    Fallback: if no such split is found, use the deepest node whose direct
    children contain ≥2 nav-bearing siblings (classic nav bar layout).

    Returns (path, nav_child_node) or None.
    """
    root_children = schema.get("children")
    if not root_children:
        return None
    root = root_children[0] if root_children else None
    if root is None:
        return None

    # Candidate: (path_to_nav_child, nav_child_node, nav_child_route_count)
    # path_to_nav_child is the path from schema root to the nav child node.
    best: tuple[list[int], dict] | None = None
    best_depth = -1

    def walk(n: Any, path: list[int]) -> None:
        nonlocal best, best_depth
        if not isinstance(n, dict):
            return

        children = n.get("children") or []
        if len(children) >= 2:
            # Check if exactly one child carries nav routes and others don't.
            child_routes = [
                (i, c, _collect_nav_routes(c))
                for i, c in enumerate(children)
            ]
            nav_children = [(i, c, r) for i, c, r in child_routes if len(r) >= 2]
            non_nav_children = [(i, c, r) for i, c, r in child_routes if len(r) < 2]

            if len(nav_children) == 1 and len(non_nav_children) >= 1:
                nav_idx, nav_child, nav_routes = nav_children[0]
                nav_path = path + [nav_idx]
                # Prefer the SHALLOWEST match with the MOST nav routes.
                # This picks the top-level nav bar rather than a nav item
                # row deep inside the nav bar.
                if best is None or len(nav_path) < best_depth or (
                    len(nav_path) == best_depth
                    and len(nav_routes) > len(_collect_nav_routes(best[1]))
                ):
                    best = (nav_path, nav_child)
                    best_depth = len(nav_path)

        for i, c in enumerate(children):
            walk(c, path + [i])

    # Start from the root node itself.
    walk(root, [0])

    return best


def _node_at_path(root: dict, path: list[int]) -> dict | None:
    """Navigate to a node at the given child-index path from root."""
    current: Any = root
    for idx in path:
        children = current.get("children") or []
        if idx >= len(children):
            return None
        current = children[idx]
    return current


def _parent_and_nav_idx(
    root: dict, path: list[int]
) -> tuple[dict | None, int]:
    """Return (parent_node, nav_child_index).

    The nav_child_index is the last element of the path; the parent
    is the node reached by the path without the last element.
    """
    if not path:
        return None, 0
    parent_path = path[1:-1]  # path[0] is always the root (schema's first child)
    parent = _node_at_path(root, [0] + parent_path) if parent_path else root.get("children", [None])[0]
    nav_idx = path[-1]
    return parent, nav_idx


# ---------------------------------------------------------------------------
# Structural-diff heuristic — for Figma-driven apps where nav buttons may
# not carry `navigate` props. Looks at root-level children across pages
# and hoists any subtree that appears at the same position in 60%+ of
# pages. This catches the typical "sidebar + main" pattern where the
# sidebar is identical across every page.
# ---------------------------------------------------------------------------

def _structural_signature(node: Any, max_depth: int = 4) -> str:
    """Build a stable fingerprint for a subtree: nested (type, child-types)
    down to max_depth. Ignores text content and class names so structurally-
    identical chrome with different per-page tweaks still matches.
    """
    if not isinstance(node, dict) or max_depth <= 0:
        return ""
    t = node.get("type") or "?"
    kids = node.get("children") or []
    if not kids or max_depth == 1:
        return t
    child_sigs = ",".join(_structural_signature(c, max_depth - 1) for c in kids)
    return f"{t}({child_sigs})"


def extract_shell_by_structural_diff(
    project_dir: Path,
    nav_flow: dict,
    min_share_ratio: float = 0.6,
) -> dict | None:
    """Detect chrome subtrees that repeat at the same root-index in 60%+
    of pages. Hoist them to shell.json with a PageOutlet where the unique
    body sits; rewrite each page to keep only its non-chrome children.

    Returns the shell schema dict, or None when no recurring chrome found
    (in which case the caller falls back to the nav-button heuristic).
    """
    schemas_dir = project_dir / "src" / "schemas"
    if not schemas_dir.exists():
        return None

    auth_routes: set[str] = set(nav_flow.get("auth_routes") or [])
    shell_pages = [
        p for p in (nav_flow.get("pages") or [])
        if p.get("shell") and p.get("route") not in auth_routes
    ]
    if len(shell_pages) < 2:
        return None  # need at least 2 pages to compare

    # Load every shell-page schema and gather their root-level children.
    page_data: list[tuple[Path, dict, dict, list[dict]]] = []
    for page_entry in shell_pages:
        schema_file = page_entry.get("schemaFile", "")
        if not schema_file:
            continue
        schema_path = project_dir / schema_file
        if not schema_path.exists():
            continue
        try:
            schema = json.loads(schema_path.read_text())
        except Exception:
            continue
        root_children = schema.get("children") or []
        if not root_children:
            continue
        root = root_children[0]
        kids = root.get("children") or []
        page_data.append((schema_path, schema, root, kids))

    if len(page_data) < 2:
        return None

    n_pages = len(page_data)
    threshold = max(2, int(round(n_pages * min_share_ratio)))

    # For each root-child index, count which structural signatures appear.
    # A signature that hits the threshold at the same index → chrome.
    max_kids = max(len(kids) for _, _, _, kids in page_data)
    chrome_at_index: dict[int, dict] = {}  # idx → representative chrome node

    for i in range(max_kids):
        sig_to_nodes: dict[str, list[dict]] = {}
        for _path, _sch, _root, kids in page_data:
            if i >= len(kids):
                continue
            sig = _structural_signature(kids[i])
            sig_to_nodes.setdefault(sig, []).append(kids[i])
        # Pick the dominant signature if it crosses the threshold.
        for sig, nodes in sig_to_nodes.items():
            if not sig:
                continue
            if len(nodes) >= threshold:
                chrome_at_index[i] = nodes[0]
                break

    if not chrome_at_index:
        return None

    # Build the shell schema: clone the first page's root, replace its
    # children with [chrome[i] OR PageOutlet at non-chrome slots].
    first_path, first_schema, first_root, first_kids = page_data[0]
    shell_root = copy.deepcopy(first_root)

    new_root_kids: list[dict] = []
    outlet_inserted = False
    for i in range(max_kids):
        if i in chrome_at_index:
            new_root_kids.append(copy.deepcopy(chrome_at_index[i]))
        elif not outlet_inserted:
            new_root_kids.append({"id": "page-outlet", "type": "PageOutlet", "props": {}})
            outlet_inserted = True
    if not outlet_inserted:
        # Pure-chrome layout — outlet at end so unique body still has a slot.
        new_root_kids.append({"id": "page-outlet", "type": "PageOutlet", "props": {}})

    shell_root["children"] = new_root_kids
    shell_schema: dict = {
        "schemaVersion": "2",
        "id": "shell",
        "children": [shell_root],
    }

    (schemas_dir / "shell.json").write_text(json.dumps(shell_schema, indent=2))

    # Rewrite each page to keep only non-chrome children.
    chrome_indices = set(chrome_at_index.keys())
    for schema_path, schema, root, kids in page_data:
        new_kids = [k for i, k in enumerate(kids) if i not in chrome_indices]
        new_root = {**root, "children": new_kids}
        new_schema = {**schema, "children": [new_root]}
        schema_path.write_text(json.dumps(new_schema, indent=2))

    return shell_schema


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

def extract_shell_from_pages(
    project_dir: Path,
    nav_flow: dict,
) -> dict | None:
    """Examine every shell:true page, find the recurring top-nav, emit
    shell.json with <PageOutlet/> in its place, and rewrite each page
    schema to remove the nav subtree (the shell now provides it).

    Returns the shell schema dict, or None if no recurring nav found.
    """
    schemas_dir = project_dir / "src" / "schemas"
    if not schemas_dir.exists():
        return None

    # Collect pages that should use the shell (shell=true and not auth-only).
    auth_routes: set[str] = set(nav_flow.get("auth_routes") or [])
    shell_pages = [
        p
        for p in (nav_flow.get("pages") or [])
        if p.get("shell") and p.get("route") not in auth_routes
    ]
    if not shell_pages:
        return None

    # Locate nav in each shell page's schema.
    nav_candidates: list[tuple[dict, Path, dict, tuple[list[int], dict]]] = []
    for page_entry in shell_pages:
        schema_file = page_entry.get("schemaFile", "")
        if not schema_file:
            continue
        schema_path = project_dir / schema_file
        if not schema_path.exists():
            continue
        try:
            schema = json.loads(schema_path.read_text())
        except Exception:
            continue
        found = _find_nav_subtree(schema)
        if found:
            nav_candidates.append((page_entry, schema_path, schema, found))

    if not nav_candidates:
        return None

    # MVP: take the nav from the FIRST shell page as the canonical shell.
    # Future: check structural similarity across all candidates.
    _first_page, first_path, first_schema, (first_nav_path, _first_nav_node) = nav_candidates[0]

    # -----------------------------------------------------------------
    # Build shell schema: deep-copy the first page, then replace the
    # siblings AFTER the nav with a single PageOutlet placeholder.
    # -----------------------------------------------------------------
    shell_schema = copy.deepcopy(first_schema)
    shell_root = (shell_schema.get("children") or [None])[0]
    if shell_root is None:
        return None

    # Navigate to the nav's parent node within the shell copy.
    # first_nav_path: [0, ...parent_indices..., nav_child_index]
    # path[0]=0 always refers to the schema root's first child.
    nav_idx_in_parent = first_nav_path[-1]
    parent_path_indices = first_nav_path[1:-1]  # skip the root index

    shell_parent = shell_root
    for idx in parent_path_indices:
        children = shell_parent.get("children") or []
        if idx >= len(children):
            shell_parent = None
            break
        shell_parent = children[idx]

    if shell_parent and "children" in shell_parent:
        nav_node = shell_parent["children"][nav_idx_in_parent]
        page_outlet: dict = {"type": "PageOutlet", "id": "page-outlet"}
        # Keep everything up to and including the nav, then append PageOutlet.
        shell_parent["children"] = (
            shell_parent["children"][: nav_idx_in_parent + 1] + [page_outlet]
        )
        # Ensure the nav node is preserved (already in-place above).
        _ = nav_node

    # Save shell.json.
    shell_out = schemas_dir / "shell.json"
    shell_out.write_text(json.dumps(shell_schema, indent=2))

    # -----------------------------------------------------------------
    # Rewrite each shell page: strip the nav subtree (the shell provides it).
    # -----------------------------------------------------------------
    for _page_entry, schema_path, schema, (nav_path, _nav_node) in nav_candidates:
        page_root = (schema.get("children") or [None])[0]
        if page_root is None:
            continue

        nav_idx = nav_path[-1]
        parent_indices = nav_path[1:-1]

        page_parent = page_root
        for idx in parent_indices:
            children = page_parent.get("children") or []
            if idx >= len(children):
                page_parent = None
                break
            page_parent = children[idx]

        if page_parent and "children" in page_parent:
            # Remove the nav from this page's schema (shell provides it).
            page_parent["children"] = (
                page_parent["children"][:nav_idx]
                + page_parent["children"][nav_idx + 1 :]
            )

        schema_path.write_text(json.dumps(schema, indent=2))

    return shell_schema

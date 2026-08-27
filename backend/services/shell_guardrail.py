"""Renderability guardrail for the LLM-generated app shell.

Validates ONLY what the renderer requires (exactly one PageOutlet, registered node
types, at least one nav Button, valid envelope). Does NOT constrain the design or
data-shell-region values (editor metadata). Repairs cheap deterministic faults
(duplicate PageOutlet); returns None when unrepairable so the caller can fall back.
"""
from __future__ import annotations

from services.schema_prompt import _registered_components

# Shell-only renderer nodes that are NOT in the page-component registry but ARE valid
# in a shell (verified: packages/renderer/src/nodes/shell/ contains only PageOutlet).
_SHELL_NODES = {"PageOutlet"}


def _iter_nodes(node):
    """Yield every dict node in the schema tree (descends children + root)."""
    if isinstance(node, dict):
        yield node
        root = node.get("root")
        if isinstance(root, dict):
            yield from _iter_nodes(root)
        for child in node.get("children") or []:
            yield from _iter_nodes(child)


def validate_shell(shell: dict) -> list[str]:
    """Return a list of renderability issues; empty list means renderable."""
    if not isinstance(shell, dict):
        return ["shell is not a dict"]
    nodes = list(_iter_nodes(shell))
    issues: list[str] = []

    outlets = [n for n in nodes if n.get("type") == "PageOutlet"]
    if len(outlets) != 1:
        issues.append(f"expected exactly 1 PageOutlet, found {len(outlets)}")

    allowed = set(_registered_components()) | _SHELL_NODES
    unknown = sorted({n.get("type") for n in nodes
                      if n.get("type") and n.get("type") not in allowed})
    if unknown:
        issues.append(f"unregistered node types: {unknown}")

    _NAV_TYPES = {"Button", "SideNav", "NavLink"}
    if not any(n.get("type") in _NAV_TYPES for n in nodes):
        issues.append("no navigation node in shell")
    return issues


def is_renderable_shell(shell: dict) -> bool:
    return not validate_shell(shell)


def _strip_extra_outlets(node, seen: list[int]) -> None:
    """Recursively drop PageOutlet children beyond the first encountered."""
    if not isinstance(node, dict):
        return
    kids = node.get("children")
    if isinstance(kids, list):
        new_kids = []
        for c in kids:
            if isinstance(c, dict) and c.get("type") == "PageOutlet":
                if seen:
                    continue  # already kept one — drop this duplicate
                seen.append(1)
            new_kids.append(c)
        node["children"] = new_kids
        for c in new_kids:
            _strip_extra_outlets(c, seen)
    if isinstance(node.get("root"), dict):
        _strip_extra_outlets(node["root"], seen)


def repair_shell(shell: dict) -> dict | None:
    """Fix cheap deterministic faults. Returns the repaired shell, or None when
    the shell cannot be made renderable by deterministic means."""
    if not isinstance(shell, dict):
        return None
    import copy
    fixed = copy.deepcopy(shell)
    outlets = [n for n in _iter_nodes(fixed) if n.get("type") == "PageOutlet"]
    if len(outlets) > 1:
        _strip_extra_outlets(fixed, [])
    return fixed if is_renderable_shell(fixed) else None

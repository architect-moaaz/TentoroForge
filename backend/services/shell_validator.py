"""Validator for shell.json schemas.

A shell.json is a regular PageV2 tree with constraints:
- Exactly one <PageOutlet /> somewhere in the tree
- No PlaceholderSlot nodes (shell is static chrome)
- Every Button.navigate references a known route in nav-flow.pages
"""
from __future__ import annotations
from typing import Any


class ShellValidationError(Exception):
    pass


def validate_shell(shell: dict, nav_flow: dict | None = None) -> list[str]:
    """Validate a shell.json schema. Returns a list of error messages
    (empty when valid)."""
    errors: list[str] = []

    if not isinstance(shell, dict):
        errors.append("shell.json must be an object")
        return errors

    if "children" not in shell or not isinstance(shell.get("children"), list):
        errors.append("shell.json missing 'children' array")

    page_outlets = _collect_by_type(shell, "PageOutlet")
    if len(page_outlets) == 0:
        errors.append("shell.json must contain exactly one PageOutlet node — found 0")
    elif len(page_outlets) > 1:
        errors.append(f"shell.json must contain exactly one PageOutlet node — found {len(page_outlets)}")

    placeholder_slots = _collect_by_type(shell, "PlaceholderSlot")
    if placeholder_slots:
        errors.append(
            f"shell.json must not contain PlaceholderSlot nodes — found {len(placeholder_slots)}. "
            "The shell is static chrome; data-bound content belongs in per-page schemas."
        )

    if nav_flow is not None:
        known_routes = {p.get("route") for p in (nav_flow.get("pages") or []) if isinstance(p, dict)}
        bad_navs = _collect_button_navigates_outside(shell, known_routes)
        for label, nav in bad_navs:
            errors.append(
                f"Button {label!r} navigates to {nav!r} but that route is not declared in nav-flow.pages"
            )

    return errors


def _collect_by_type(node: Any, type_name: str) -> list[dict]:
    out: list[dict] = []
    if isinstance(node, dict):
        if node.get("type") == type_name:
            out.append(node)
        for c in (node.get("children") or []):
            out.extend(_collect_by_type(c, type_name))
    return out


def _collect_button_navigates_outside(node: Any, known_routes: set[str]) -> list[tuple[str, str]]:
    """Return list of (label, navigate) for Buttons whose navigate is not in known_routes."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        if node.get("type") == "Button":
            props = node.get("props") or {}
            nav = props.get("navigate")
            if isinstance(nav, str) and nav and nav not in known_routes:
                # Allow root '/' to match any route ending with '/'
                if not (nav == "/" and any(r == "/" for r in known_routes)):
                    out.append((props.get("label") or "(no label)", nav))
        for c in (node.get("children") or []):
            out.extend(_collect_button_navigates_outside(c, known_routes))
    return out

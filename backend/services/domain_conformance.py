"""Domain-conformance check (M5-T7).

For a rendered page schema, verify it respects the effective shape
profile of its owning route. Purely deterministic — reads the
schema tree, checks for specific structural violations:

- ``layout.shell == "none"`` → no `<Sidebar>` / `<Shell>` / `<AppNav>`
  wrapper in the schema.
- ``auth.surface == "modal"`` → the auth barrier is a `<LoginModal>`,
  not a full-page `<LoginForm>` at `/login`.
- ``nav.menu == "none"`` → no sidebar-menu / header-menu components
  in the page tree.
- ``workflows.executionMode == "fire-and-forget"`` → forms declare
  ``submit.mode: fire-and-forget`` (or equivalent).

Findings feed into the verify_stack's ``domain_conformance`` slot.
Callable from any stage that produces a page schema; also runnable
as a post-gen guard.
"""
from __future__ import annotations

from typing import Any, Iterator

from services.shape_profile import Finding
from services.shape_profile_derived import resolve_shape


# ══════════════════════════════════════════════════════════════════
# Public entry
# ══════════════════════════════════════════════════════════════════


def check_page(
    plan: dict[str, Any],
    route: str,
    page_schema: dict[str, Any],
) -> list[Finding]:
    """Check one page's schema against its effective shape."""
    shape = resolve_shape(plan, route)
    if not shape:
        return []
    findings: list[Finding] = []
    findings.extend(_check_shell(shape, page_schema, route))
    findings.extend(_check_auth(shape, page_schema, route))
    findings.extend(_check_menu(shape, page_schema, route))
    findings.extend(_check_workflow_submit(shape, page_schema, route))
    return findings


def check_all_pages(plan: dict[str, Any], pages: dict[str, dict[str, Any]]) -> list[Finding]:
    """Check every page in a `{route: schema}` mapping. Convenience."""
    findings: list[Finding] = []
    for route, schema in pages.items():
        findings.extend(check_page(plan, route, schema))
    return findings


# ══════════════════════════════════════════════════════════════════
# Individual rules
# ══════════════════════════════════════════════════════════════════


_SHELL_COMPONENT_NAMES = frozenset({
    "Sidebar", "SideNav", "AppShell", "Shell", "DashboardShell",
    "AppSidebar", "NavigationRail", "TopBar", "HeaderNav",
})

_MENU_COMPONENT_NAMES = frozenset({
    "SidebarMenu", "SideNav", "HeaderMenu", "NavMenu", "MainMenu",
})

_LOGIN_ROUTE_COMPONENT_NAMES = frozenset({
    "LoginForm", "LoginPage", "SignInForm", "SignInPage",
})


def _check_shell(shape: dict, schema: dict, route: str) -> list[Finding]:
    layout = shape.get("layout") or {}
    if layout.get("shell") != "none":
        return []
    hits = [n for n in _iter_nodes(schema) if _node_type(n) in _SHELL_COMPONENT_NAMES]
    if not hits:
        return []
    return [Finding(
        rule="domain_conformance.shell_present_on_none",
        message=(
            f"route {route!r}: layout.shell=none but page schema contains "
            f"shell components ({[_node_type(h) for h in hits]}). Shape "
            "says no chrome; remove these or fix the shape."
        ),
        severity="error",
        axis="app_shape",
    )]


def _check_auth(shape: dict, schema: dict, route: str) -> list[Finding]:
    auth = shape.get("auth") or {}
    if auth.get("surface") != "modal":
        return []
    if route in ("/login", "/signup", "/signin"):
        return [Finding(
            rule="domain_conformance.login_route_on_modal_auth",
            message=(
                f"route {route!r} exists but auth.surface=modal — the "
                "modal login flow does not need a dedicated route. Either "
                "remove this page or change auth.surface to 'route'."
            ),
            severity="warning",
            axis="app_shape",
        )]
    return []


def _check_menu(shape: dict, schema: dict, route: str) -> list[Finding]:
    nav = shape.get("nav") or {}
    if nav.get("menu") != "none":
        return []
    hits = [n for n in _iter_nodes(schema) if _node_type(n) in _MENU_COMPONENT_NAMES]
    if not hits:
        return []
    return [Finding(
        rule="domain_conformance.menu_component_on_none",
        message=(
            f"route {route!r}: nav.menu=none but page schema contains "
            f"menu components ({[_node_type(h) for h in hits]}). Remove "
            "them or change nav.menu."
        ),
        severity="error",
        axis="app_shape",
    )]


def _check_workflow_submit(shape: dict, schema: dict, route: str) -> list[Finding]:
    workflows = shape.get("workflows") or {}
    mode = workflows.get("executionMode")
    if mode != "fire-and-forget":
        return []
    findings: list[Finding] = []
    for node in _iter_nodes(schema):
        if _node_type(node) != "Form":
            continue
        props = node.get("props") if isinstance(node, dict) else None
        if not isinstance(props, dict):
            continue
        submit = props.get("submit") or {}
        # If a form declares a workflow submit but no explicit mode,
        # emit a warning — the runtime default is await-with-spinner,
        # not fire-and-forget.
        if submit.get("kind") == "workflow" and not submit.get("mode"):
            findings.append(Finding(
                rule="domain_conformance.form_submit_mode_missing",
                message=(
                    f"route {route!r}: workflows.executionMode="
                    "fire-and-forget but a Form with submit.kind=workflow "
                    "does not declare submit.mode. The form will silently "
                    "await instead of fire-and-forgetting."
                ),
                severity="warning",
                axis="app_shape",
            ))
    return findings


# ══════════════════════════════════════════════════════════════════
# Schema tree walker
# ══════════════════════════════════════════════════════════════════


def _iter_nodes(schema: Any) -> Iterator[dict[str, Any]]:
    """Depth-first walk over a page schema tree. Yields every dict
    with a ``type`` key (the shape of a schema node in this codebase).
    Tolerant of unexpected shapes — empty iteration on non-dict input."""
    if isinstance(schema, dict):
        if "type" in schema:
            yield schema
        for value in schema.values():
            yield from _iter_nodes(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _iter_nodes(item)


def _node_type(node: Any) -> str | None:
    if isinstance(node, dict):
        t = node.get("type")
        return str(t) if isinstance(t, str) else None
    return None

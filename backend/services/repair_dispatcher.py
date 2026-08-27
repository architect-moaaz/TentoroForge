"""Slice 2 of the validate→repair loop: route crawl findings to fixers.

Deterministic findings (dead nav, dead buttons, unresolved workflow dispatch) are
repaired by re-running the deterministic guards over the app's schemas — cheap,
safe, no LLM. Render errors and other runtime failures that need judgement go to a
scoped fix agent (injected; skipped when none is provided, so this degrades to
deterministic-only repair).
"""
from __future__ import annotations

# Finding types a deterministic schema sweep can repair.
_DETERMINISTIC = {"route_404", "dead_button", "dispatch_failed", "workflow_unresolved"}
# Finding types that need a scoped fix agent (route + error → schema edit).
_AGENT = {"render_error", "route_error", "data_failed"}


def reguard_schemas(app_dir) -> int:
    """Re-run the FULL deterministic guard suite over the app; return #changes.

    Not just nav/buttons — a Validate & Repair pass applies the same deterministic
    fixes the generation pipeline does: schema-crash rewrite, create/edit-route
    coverage, detail Edit/Delete wiring, FK-dropdown repair, form scaffolding,
    semantic field types, and reference resolution. Every guard is idempotent, so on
    a clean app nothing changes and the loop converges."""
    changed = 0

    def _run(fn, *keys):
        nonlocal changed
        try:
            res = fn(app_dir) or {}
            changed += sum(int(res.get(k, 0) or 0) for k in keys)
        except Exception:  # noqa: BLE001 — a guard must never break the loop
            pass

    from services.nav_guard import guard_nav_targets
    from services.button_audit import audit_app_buttons
    from services.drizzle_column_guard import guard_drizzle_columns
    from services.ensure_edit_routes import ensure_create_routes, ensure_edit_routes
    from services.detail_action_guard import wire_detail_actions
    from services.form_scaffold import scaffold_forms, repair_fk_dropdowns
    from services.semantic_field_types import apply_semantic_field_types
    from services.schema_references import resolve_schema_references
    from services.fk_label_columns import relabel_fk_columns
    from services.filter_field_guard import guard_filter_fields
    from services.surface_border_guard import harmonize_surface_borders
    from services.next_config_guard import normalize_next_config
    from services.drizzle_check_guard import guard_check_constraints
    from services.table_row_nav_guard import guard_table_row_nav

    _run(guard_drizzle_columns, "fixed")
    _run(guard_check_constraints, "fixed")
    _run(normalize_next_config, "normalized")
    _run(relabel_fk_columns, "relabeled")
    _run(guard_filter_fields, "remapped")
    _run(harmonize_surface_borders, "stripped")
    _run(guard_table_row_nav, "wired")
    _run(ensure_create_routes, "created", "buttons")
    _run(ensure_edit_routes, "created", "buttons")
    _run(wire_detail_actions, "edits", "deletes")
    _run(repair_fk_dropdowns, "repaired")
    _run(scaffold_forms, "added")
    _run(apply_semantic_field_types, "retyped")
    _run(guard_nav_targets, "repointed", "neutralized")
    _run(audit_app_buttons, "wired")
    _run(resolve_schema_references, "resolved")
    return changed


def dispatch_repairs(app_dir, findings: list[dict], *, sweep=None, fix_agent=None) -> dict:
    """Route findings to fixers and apply them. Returns a disposition summary.

    `sweep(app_dir) -> int` runs the deterministic guards (default: reguard_schemas).
    `fix_agent(app_dir, route, errors) -> bool` handles a route's render errors
    (default: None → those findings are reported as unhandled)."""
    findings = findings or []
    sweep = sweep or reguard_schemas

    agent_findings = [f for f in findings if f.get("type") in _AGENT]
    unknown = [f for f in findings if f.get("type") not in _DETERMINISTIC | _AGENT]

    # Always try the deterministic sweep when there's ANYTHING to fix — the guards
    # are idempotent and frequently resolve the schema cause behind a render_error /
    # data_failed (a malformed form, a dead binding, a mis-wired detail action), not
    # just the classic dead-button/404 cases. Whatever the sweep doesn't fix is then
    # routed to the agent, and the loop re-validates to confirm real progress.
    deterministic_fixed = sweep(app_dir) if findings else 0

    agent_routes: list[str] = []
    unhandled: list[dict] = list(unknown)
    if agent_findings:
        by_route: dict[str, list[dict]] = {}
        for f in agent_findings:
            by_route.setdefault(f.get("route", "/"), []).append(f)
        for route, errs in by_route.items():
            if fix_agent is not None and fix_agent(app_dir, route, errs):
                agent_routes.append(route)
            else:
                unhandled.extend(errs)

    fixed = deterministic_fixed + len(agent_routes)
    return {
        "fixed": fixed,
        "deterministic_fixed": deterministic_fixed,
        "agent_routes": agent_routes,
        "unhandled": unhandled,
        "made_progress": fixed > 0,
    }

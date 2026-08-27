"""Unit tests for services.fault_classifier — SV-2.

One test per named FaultSignature + a fallback test + coverage of the
priority/tool metadata lookup. Fixtures live inline (small dicts) so
adding a new signature = adding one fixture pair (evidence + expected sig).
"""
from __future__ import annotations

import pytest

from services.fault_classifier import (
    Evidence,
    FaultSignature,
    LogEntry,
    NetworkEntry,
    _META,
    classify,
)
from services.interaction_extractor import (
    ButtonAction,
    ButtonInteraction,
    DetailInteraction,
    FieldSpec,
    FormInteraction,
    FormSubmit,
    ListInteraction,
    RouteInteraction,
)


# ── Interaction builders ────────────────────────────────────────────────


def _route(route="/dashboard", requires_auth=True) -> RouteInteraction:
    return RouteInteraction(
        id=f"route:{route}", kind="route",
        route=route, requires_auth=requires_auth,
    )


def _button(kind="workflow", **kwargs) -> ButtonInteraction:
    action_defaults = {
        "workflow": ButtonAction(kind="workflow", workflow_target="W"),
        "navigate": ButtonAction(kind="navigate", navigate_target="/x"),
        "compute": ButtonAction(kind="compute", compute_target="t", compute_formula="1+1"),
        "submit": ButtonAction(kind="submit"),
        "none": ButtonAction(kind="none"),
    }
    return ButtonInteraction(
        id="button:/x:root", kind="button",
        route=kwargs.get("route", "/x"),
        selector="button",
        label=kwargs.get("label", "Go"),
        action=action_defaults[kind],
    )


def _form(kind="workflow") -> FormInteraction:
    submit_defaults = {
        "workflow": FormSubmit(kind="workflow", workflow_target="W"),
        "dataSource": FormSubmit(kind="dataSource", dataSource_target="items"),
        "none": FormSubmit(kind="none"),
    }
    return FormInteraction(
        id="form:/x:root", kind="form",
        route="/x", selector="form", fields=(), submit=submit_defaults[kind],
    )


def _list() -> ListInteraction:
    return ListInteraction(
        id="list:/x:root", kind="list",
        route="/x", selector="table",
        dataSource="items", entity="Item", seed_min_rows=1,
    )


def _detail() -> DetailInteraction:
    return DetailInteraction(
        id="detail:/x/[id]", kind="detail",
        route="/x/[id]", entity="Item", param_name="id",
    )


# ── 500-shape signatures ────────────────────────────────────────────────


def test_ssr_500_enoent_json() -> None:
    ev = Evidence(
        status=500,
        stack_trace="Error: ENOENT: no such file or directory, open '/var/task/src/schemas/home.json'",
    )
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.SSR_500_ENOENT_JSON
    assert r.priority == "BLOCKER"
    assert "outputFileTracingIncludes" in r.hypothesis or "includeFiles" in r.hypothesis


def test_ssr_500_unknown_table() -> None:
    ev = Evidence(status=500, stack_trace='PostgresError: relation "candidates" does not exist')
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.SSR_500_UNKNOWN_TABLE


def test_ssr_500_module_not_found() -> None:
    ev = Evidence(status=500, stack_trace="Module not found: Can't resolve '@tentoroforge/xxx'")
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.SSR_500_MODULE_NOT_FOUND


def test_ssr_500_generic_when_no_stack_pattern() -> None:
    ev = Evidence(status=500, stack_trace="TypeError: Cannot read properties of undefined")
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.SSR_500_GENERIC


def test_ssr_500_reads_body_when_stack_missing() -> None:
    """Some Vercel error pages ship the message in the body, not stack."""
    ev = Evidence(status=500, body_excerpt="Error: ENOENT src/schemas/home.json")
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.SSR_500_ENOENT_JSON


# ── 404 / 401 ───────────────────────────────────────────────────────────


def test_route_404_missing_schema() -> None:
    ev = Evidence(status=404)
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.ROUTE_404_MISSING_SCHEMA


def test_route_401_unexpected() -> None:
    """401 on a non-auth-gated route is a wiring bug."""
    ev = Evidence(status=401)
    r = classify(_route(requires_auth=False), ev)
    assert r.signature == FaultSignature.ROUTE_401_UNEXPECTED


def test_route_401_on_gated_route_is_not_classified_as_wiring_bug() -> None:
    """A gated route returning 401 is expected before login."""
    ev = Evidence(status=401)
    r = classify(_route(requires_auth=True), ev)
    assert r.signature != FaultSignature.ROUTE_401_UNEXPECTED


# ── Button signatures ───────────────────────────────────────────────────


def test_button_no_action_declared() -> None:
    r = classify(_button(kind="none"), Evidence())
    assert r.signature == FaultSignature.BUTTON_NO_ACTION_DECLARED
    assert r.priority == "BROKEN"


def test_button_workflow_missing_when_no_post_fired() -> None:
    """Workflow button clicked but no POST /api/workflows/... in network log."""
    ev = Evidence(network_log=[])
    r = classify(_button(kind="workflow"), ev)
    assert r.signature == FaultSignature.BUTTON_WORKFLOW_MISSING


def test_button_workflow_passes_when_post_fired() -> None:
    ev = Evidence(network_log=[
        NetworkEntry(method="POST", url="/api/workflows/W/start", status=200),
    ])
    r = classify(_button(kind="workflow"), ev)
    assert r.signature != FaultSignature.BUTTON_WORKFLOW_MISSING


def test_button_nav_target_missing_on_404() -> None:
    ev = Evidence(status=404)
    r = classify(_button(kind="navigate"), ev)
    assert r.signature == FaultSignature.BUTTON_NAV_TARGET_MISSING


def test_button_compute_wrong_value() -> None:
    ev = Evidence(computed_value_actual="12", computed_value_expected="14")
    r = classify(_button(kind="compute"), ev)
    assert r.signature == FaultSignature.BUTTON_COMPUTE_WRONG_VALUE


def test_button_compute_correct_value_is_not_a_fault() -> None:
    ev = Evidence(computed_value_actual="14", computed_value_expected="14")
    r = classify(_button(kind="compute"), ev)
    assert r.signature != FaultSignature.BUTTON_COMPUTE_WRONG_VALUE


# ── Form signatures ─────────────────────────────────────────────────────


def test_form_submit_400() -> None:
    ev = Evidence(status=400, network_log=[
        NetworkEntry(method="POST", url="/api/workflows/W/start", status=400),
    ])
    r = classify(_form(), ev)
    assert r.signature == FaultSignature.FORM_SUBMIT_400


def test_form_submit_500_fk() -> None:
    ev = Evidence(
        status=500,
        stack_trace='error: insert or update on table "applications" violates foreign key constraint',
        network_log=[NetworkEntry(method="POST", url="/api/data/apps", status=500)],
    )
    r = classify(_form(), ev)
    assert r.signature == FaultSignature.FORM_SUBMIT_500_FK


def test_form_submit_500_generic_when_no_fk_pattern() -> None:
    ev = Evidence(
        status=500,
        stack_trace="TypeError: undefined is not a function",
        network_log=[NetworkEntry(method="POST", url="/api/data/x", status=500)],
    )
    r = classify(_form(), ev)
    assert r.signature == FaultSignature.FORM_SUBMIT_500_GENERIC


def test_form_no_submit_action() -> None:
    r = classify(_form(kind="none"), Evidence())
    assert r.signature == FaultSignature.FORM_NO_SUBMIT_ACTION


def test_form_500_unknown_table_becomes_form_500_generic() -> None:
    """A 500 with unknown-table on a form POST is a form issue, not SSR."""
    ev = Evidence(
        status=500,
        stack_trace='relation "items" does not exist',
        network_log=[NetworkEntry(method="POST", url="/api/data/items", status=500)],
    )
    r = classify(_form(), ev)
    assert r.signature == FaultSignature.FORM_SUBMIT_500_GENERIC


# ── List / dashboard / detail content signatures ────────────────────────


def test_list_empty() -> None:
    ev = Evidence(rows_returned=0)
    r = classify(_list(), ev)
    assert r.signature == FaultSignature.LIST_EMPTY
    assert r.priority == "CONTENT"


def test_list_non_empty_is_not_a_fault() -> None:
    ev = Evidence(rows_returned=5)
    r = classify(_list(), ev)
    assert r.signature != FaultSignature.LIST_EMPTY


def test_list_datasource_unresolved_on_404() -> None:
    ev = Evidence(status=404)
    r = classify(_list(), ev)
    assert r.signature == FaultSignature.LIST_DATASOURCE_UNRESOLVED


def test_dashboard_blank_when_widget_count_low() -> None:
    ev = Evidence(rendered_widget_count=1)
    r = classify(_route(route="/dashboard"), ev)
    assert r.signature == FaultSignature.DASHBOARD_BLANK


def test_dashboard_blank_only_on_dashboard_routes() -> None:
    """A low widget count on /candidates isn't a dashboard fault."""
    ev = Evidence(rendered_widget_count=1)
    r = classify(_route(route="/candidates"), ev)
    assert r.signature != FaultSignature.DASHBOARD_BLANK


def test_detail_binding_unresolved_when_dom_has_raw_binding() -> None:
    ev = Evidence(dom_snapshot="<dd>{{candidate.fullName}}</dd>")
    r = classify(_detail(), ev)
    assert r.signature == FaultSignature.DETAIL_BINDING_UNRESOLVED


def test_detail_resolved_binding_is_not_a_fault() -> None:
    ev = Evidence(dom_snapshot="<dd>Alice Chen</dd>")
    r = classify(_detail(), ev)
    assert r.signature == FaultSignature.UNCLASSIFIED


# ── Console signatures ─────────────────────────────────────────────────


def test_console_react_31() -> None:
    ev = Evidence(console=[
        LogEntry(level="error", text="Uncaught Error: Minified React error #31; visit ..."),
    ])
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.CONSOLE_REACT_31


def test_console_hydration_mismatch() -> None:
    ev = Evidence(console=[
        LogEntry(level="error", text="Warning: Text content did not match. Server: 'a' Client: 'b'"),
    ])
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.CONSOLE_HYDRATION_MISMATCH


# ── Infra ──────────────────────────────────────────────────────────────


def test_timeout_overrides_everything() -> None:
    """Runner timeout is a runner problem, not an app fault."""
    ev = Evidence(status=500, timed_out=True)
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.TIMEOUT
    assert r.priority == "FLAKY"
    assert r.suggested_tools == ()  # no auto-fix; escalate


def test_unclassified_fallback() -> None:
    """A green-looking evidence blob on a route with no other signal → UNCLASSIFIED."""
    ev = Evidence(status=200)  # no other markers
    r = classify(_route(), ev)
    assert r.signature == FaultSignature.UNCLASSIFIED


# ── Metadata table integrity ────────────────────────────────────────────


def test_every_signature_has_metadata() -> None:
    """Every FaultSignature.* enum value must have a _META entry."""
    all_sigs = {
        v for k, v in vars(FaultSignature).items()
        if isinstance(v, str) and not k.startswith("_") and k.isupper()
    }
    assert all_sigs == set(_META.keys())


def test_metadata_shape_is_consistent() -> None:
    """Every _META row must have (priority, layer, hypothesis, tools) shape."""
    for sig, (priority, layer, hypothesis, tools) in _META.items():
        assert priority in ("BLOCKER", "BROKEN", "CONTENT", "FLAKY"), sig
        assert layer in ("http", "dom", "console", "network", "timeout", "value"), sig
        assert isinstance(hypothesis, str) and len(hypothesis) > 20, sig
        assert isinstance(tools, tuple), sig


def test_metadata_tools_are_sensible_names() -> None:
    """suggested_tools should reference real Smith / guard names — snake_case."""
    for sig, (_, _, _, tools) in _META.items():
        for tool in tools:
            assert tool.replace("_", "").isalnum(), (sig, tool)

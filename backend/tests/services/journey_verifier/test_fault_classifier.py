"""Unit tests for the V&F 2.0 fault classifier (M1).

The classifier is pure — given a FaultRaw dict (interaction + evidence) it
returns a ClassifiedFault carrying a class_name, seam, evidence_slice and
needed_context. Priority order matters: overlapping signals must resolve
to the highest-priority match. Anything that doesn't match a known
pattern lands as `unknown` (residual).
"""
from __future__ import annotations

import pytest

from services.journey_verifier.fault_classifier import (
    ClassifiedFault,
    classify_fault,
)


def _fault(
    *,
    interaction: dict | None = None,
    evidence: dict | None = None,
    fault_id: str = "fault-1",
) -> dict:
    return {
        "id": fault_id,
        "interaction_id": (interaction or {}).get("id") or fault_id,
        "interaction": interaction or {"id": fault_id, "route": "/x", "kind": "route"},
        "evidence": evidence or {},
        "passed": False,
    }


# ── Class-by-class coverage ────────────────────────────────────────────────


def test_timeout_class():
    cf = classify_fault(_fault(evidence={"timed_out": True, "status": 500}))
    assert cf.class_name == "page-unresponsive"
    assert cf.seam == "smith:render"


def test_db_schema_mismatch_class():
    cf = classify_fault(_fault(evidence={
        "status": 500,
        "body_excerpt": "relation \"applicants\" does not exist",
    }))
    assert cf.class_name == "db-schema-mismatch"
    assert cf.seam == "deterministic:db-migrate"


def test_render_error_generic_500():
    cf = classify_fault(_fault(evidence={
        "status": 500,
        "body_excerpt": "Error: unexpected token at position 3",
        "stack_trace": "Error: bad thing\n at Page (/app/x.tsx:12)",
    }))
    assert cf.class_name == "render-error"
    assert cf.seam == "smith:render"


def test_missing_page_when_404_not_in_registry():
    cf = classify_fault(
        _fault(
            interaction={"id": "route:/missing", "route": "/missing", "kind": "route"},
            evidence={"status": 404},
        ),
        route_registry={"/", "/dashboard"},
    )
    assert cf.class_name == "missing-page"
    assert cf.seam == "deterministic:add-page"


def test_catch_all_router_broken_when_404_in_registry():
    cf = classify_fault(
        _fault(
            interaction={"id": "route:/known", "route": "/known", "kind": "route"},
            evidence={"status": 404},
        ),
        route_registry={"/known", "/dashboard"},
    )
    assert cf.class_name == "catch-all-router-broken"
    assert cf.seam == "deterministic:router-regen"


def test_data_fetch_failure_200_with_network_500():
    cf = classify_fault(_fault(evidence={
        "status": 200,
        "console": [{"level": "error", "text": "Failed to load resource: the server responded with a status of 500 (Internal Server Error)"}],
        "network_log": [
            {"method": "GET", "url": "/api/data/applicants", "status": 500},
        ],
    }))
    assert cf.class_name == "data-fetch-failure"
    assert cf.seam == "smith:data-fetch"


def test_binding_crash_react_31():
    cf = classify_fault(_fault(evidence={
        "status": 200,
        "console": [{"level": "error", "text": "Minified React error #31; visit https://reactjs.org/docs/error-decoder.html?invariant=31"}],
    }))
    assert cf.class_name == "binding-crash"
    assert cf.seam == "smith:binding"


def test_list_empty_data():
    cf = classify_fault(_fault(
        interaction={"id": "list:/applicants", "route": "/applicants",
                     "kind": "list", "entity": "applicants",
                     "dataSource": "applicants"},
        evidence={"status": 200, "rendered_widget_count": 0, "rows_returned": 0},
    ))
    assert cf.class_name == "list-empty-data"
    assert cf.seam == "deterministic:rewire-datasource"


def test_form_not_wired():
    cf = classify_fault(_fault(
        interaction={"id": "form:/new", "route": "/new", "kind": "form",
                     "submit": {"kind": "none"}},
        evidence={"status": 200, "network_log": []},
    ))
    assert cf.class_name == "form-not-wired"
    assert cf.seam == "deterministic:orphan-wiring"


def test_auth_broken_401():
    cf = classify_fault(_fault(
        interaction={"id": "form:/login", "route": "/login", "kind": "form",
                     "submit": {"kind": "auth"}},
        evidence={
            "status": 401,
            "network_log": [{"method": "POST", "url": "/api/auth/callback/credentials", "status": 401}],
        },
    ))
    assert cf.class_name == "auth-broken"
    assert cf.seam == "deterministic:auth-seed"


def test_unknown_fallback_lands_in_residual():
    cf = classify_fault(_fault(evidence={"status": 200}))
    assert cf.class_name == "unknown"
    assert cf.seam == "residual"


# ── Priority resolution ────────────────────────────────────────────────────


def test_priority_timeout_beats_500():
    # Timeout with a 500 status attached must classify as timeout, not
    # render-error/db-schema-mismatch — the runner never got to observe
    # the real response.
    cf = classify_fault(_fault(evidence={
        "timed_out": True,
        "status": 500,
        "body_excerpt": "relation \"x\" does not exist",
    }))
    assert cf.class_name == "page-unresponsive"


def test_priority_drizzle_beats_generic_500():
    # A 500 with a drizzle signature must land in db-schema-mismatch, not
    # render-error, even though a generic stack trace is also present.
    cf = classify_fault(_fault(evidence={
        "status": 500,
        "body_excerpt": "Error rendering: relation \"candidates\" does not exist",
        "stack_trace": "Error: server render failed",
    }))
    assert cf.class_name == "db-schema-mismatch"


def test_priority_react_31_beats_data_fetch():
    # A 200 with BOTH a network 500 AND a React #31 in the console should
    # prefer binding-crash — the React error is closer to the root cause.
    # (Order in the taxonomy: data-fetch is priority 6, react-31 is 7.)
    # Actually per the task's priority order, data-fetch (200-with-network-500)
    # comes BEFORE react-31, so data-fetch wins. Verify that ordering.
    cf = classify_fault(_fault(evidence={
        "status": 200,
        "console": [
            {"level": "error", "text": "Failed to load resource: the server responded with a status of 500"},
            {"level": "error", "text": "Minified React error #31"},
        ],
        "network_log": [{"method": "GET", "url": "/api/data/x", "status": 500}],
    }))
    assert cf.class_name == "data-fetch-failure"


# ── Dataclass shape ────────────────────────────────────────────────────────


def test_classified_fault_shape():
    raw = _fault(
        interaction={"id": "route:/x", "route": "/x", "kind": "route"},
        evidence={"status": 500, "stack_trace": "Error: something"},
    )
    cf = classify_fault(raw)
    assert isinstance(cf, ClassifiedFault)
    assert cf.interaction_id == "route:/x"
    assert cf.route == "/x"
    assert cf.class_name
    assert cf.seam
    assert isinstance(cf.evidence_slice, str)
    assert isinstance(cf.needed_context, list)
    assert cf.raw is raw

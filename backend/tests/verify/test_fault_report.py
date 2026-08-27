"""Unit tests for services.fault_report — SV-6 renderer."""
from __future__ import annotations

from services.fault_report import (
    Fault,
    FaultReport,
    build_report_from_runner,
    render_for_smith,
)
from services.interaction_extractor import (
    ButtonAction,
    ButtonInteraction,
    FormInteraction,
    FormSubmit,
    ListInteraction,
    RouteInteraction,
)


# ── Runner-report hydration ─────────────────────────────────────────────


def _mk_runner_report(faults: list[dict]) -> dict:
    return {
        "run_id": "r_1", "project_id": "p", "target": "preview",
        "base_url": "http://x", "started_at": "", "finished_at": "",
        "interactions_run": 10, "interactions_passed": 7, "interactions_flaky": 0,
        "faults": faults,
    }


def _button_route_fault_500_enoent() -> dict:
    return {
        "interaction_id": "route:/",
        "interaction": {
            "id": "route:/", "kind": "route",
            "route": "/", "requires_auth": True,
        },
        "evidence": {
            "status": 500,
            "stack_trace": "ENOENT: no such file /var/task/src/schemas/home.json",
        },
        "passed": False, "flaky": False,
    }


def _button_no_action_fault() -> dict:
    return {
        "interaction_id": "button:/x:root",
        "interaction": {
            "id": "button:/x:root", "kind": "button",
            "route": "/x", "selector": "role=button[name=Go]",
            "label": "Dead", "action": {"kind": "none"},
        },
        "evidence": {},
        "passed": False, "flaky": False,
    }


def _list_empty_fault() -> dict:
    return {
        "interaction_id": "list:/candidates:root",
        "interaction": {
            "id": "list:/candidates:root", "kind": "list",
            "route": "/candidates", "selector": "table",
            "dataSource": "candidates", "entity": "Candidate",
            "seed_min_rows": 1,
        },
        "evidence": {"rows_returned": 0},
        "passed": False, "flaky": False,
    }


def test_build_report_hydrates_faults_and_classifies() -> None:
    r = build_report_from_runner(_mk_runner_report([_button_route_fault_500_enoent()]))
    assert len(r.faults) == 1
    f = r.faults[0]
    assert isinstance(f.interaction, RouteInteraction)
    assert f.signature == "SSR_500_ENOENT_JSON"
    assert f.priority == "BLOCKER"
    assert "next_config_guard" in " ".join(f.suggested_tools)


def test_report_faults_sorted_by_priority() -> None:
    """BLOCKER before BROKEN before CONTENT."""
    r = build_report_from_runner(_mk_runner_report([
        _list_empty_fault(),
        _button_route_fault_500_enoent(),
        _button_no_action_fault(),
    ]))
    priorities = [f.priority for f in r.faults]
    assert priorities == ["BLOCKER", "BROKEN", "CONTENT"]


def test_render_empty_report() -> None:
    r = build_report_from_runner(_mk_runner_report([]))
    out = render_for_smith(r)
    assert "No faults found" in out


def test_render_includes_signature_priority_and_tools() -> None:
    r = build_report_from_runner(_mk_runner_report([_button_route_fault_500_enoent()]))
    out = render_for_smith(r)
    assert "SSR_500_ENOENT_JSON" in out
    assert "BLOCKER" in out
    assert "next_config_guard" in out
    # Fault id makes it into the prompt so Smith can reference it back.
    assert "route:/" in out


def test_render_includes_interaction_context_per_kind() -> None:
    r = build_report_from_runner(_mk_runner_report([
        _button_route_fault_500_enoent(),
        _list_empty_fault(),
    ]))
    out = render_for_smith(r)
    # Route context
    assert "Route: `/`" in out
    # List context
    assert "Table dataSource: `candidates`" in out


def test_render_includes_evidence_summary() -> None:
    r = build_report_from_runner(_mk_runner_report([_button_route_fault_500_enoent()]))
    out = render_for_smith(r)
    assert "HTTP 500" in out
    assert "ENOENT" in out


def test_form_interaction_context_shows_fields_and_target() -> None:
    raw = {
        "interaction_id": "form:/x:root",
        "interaction": {
            "id": "form:/x:root", "kind": "form",
            "route": "/x", "selector": "form",
            "fields": [
                {"name": "email", "type": "email", "required": True},
                {"name": "name", "type": "text"},
            ],
            "submit": {
                "kind": "workflow", "workflow_target": "CreateThing",
                "workflow_inputs": [{"name": "email", "type": "email"}],
            },
        },
        "evidence": {"status": 400, "network_log": [
            {"method": "POST", "url": "/api/workflows/CreateThing/start", "status": 400},
        ]},
        "passed": False, "flaky": False,
    }
    r = build_report_from_runner(_mk_runner_report([raw]))
    f = r.faults[0]
    assert isinstance(f.interaction, FormInteraction)
    assert f.signature == "FORM_SUBMIT_400"
    out = render_for_smith(r)
    assert "workflow`:`CreateThing" in out
    assert "email" in out and "name" in out


def test_render_authoritative_disclaimer_present() -> None:
    """Smith's prompt must tell it NOT to re-verify by reading files."""
    r = build_report_from_runner(_mk_runner_report([_button_no_action_fault()]))
    out = render_for_smith(r)
    assert "authoritative" in out.lower()
    assert "not re-verify" in out.lower() or "not re-verify" in out.lower() or \
           "do not re-verify" in out.lower() or "not verify" in out.lower()

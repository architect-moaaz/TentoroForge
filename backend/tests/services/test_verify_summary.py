"""Tests for the verify summary formatter (prose + JSON views).

Focus: rich payloads land verbatim in the summary text so Smith can
quote specifics on later turns. Covers empty runs, all-green runs,
runs with journey failures + autofix + re-verify, and runner faults.
"""
from __future__ import annotations

from services.verify_summary import (
    format_verify_report_json,
    format_verify_summary,
)


def _base_row(**overrides):
    row = {
        "id": "abc-123",
        "status": "done",
        "error": None,
        "interactions_run": 12,
        "interactions_passed": 12,
        "faults_count": 0,
        "rounds_run": 1,
        "report": {},
    }
    row.update(overrides)
    return row


def test_all_green_summary():
    text = format_verify_summary(_base_row())
    assert "12/12" in text
    assert "no faults" in text


def test_failed_status_short_circuits():
    text = format_verify_summary(_base_row(status="failed", error="runner unreachable"))
    assert "failed to complete" in text.lower()
    assert "runner unreachable" in text


def test_faults_are_listed_with_route_and_classification():
    row = _base_row(faults_count=2, report={
        "faults": [
            {"route": "/scan", "classification": "workflow_hang",
             "summary": "Scan & compare never left pending"},
            {"route": "/admin/retailers/new", "classification": "form_null_fk",
             "summary": "retailerId NOT NULL"},
        ],
    })
    text = format_verify_summary(row)
    assert "/scan" in text
    assert "workflow_hang" in text
    assert "form_null_fk" in text


def test_journey_hints_are_quoted_verbatim():
    row = _base_row(report={
        "journey": {
            "first_run": {
                "gate_summary": {"passed": 0, "total": 2, "failed": 2,
                                 "duration_ms": 40_000, "ok": False, "mode": "warn"},
                "hints": [
                    {"journey_slug": "primary-scan",
                     "target_seam": "workflow-definition",
                     "failing_step": "Workflow runs to terminal",
                     "likely_cause": "Workflow never reached terminal"},
                    {"journey_slug": "admin-approve",
                     "target_seam": "workflow-output-mapping",
                     "failing_step": "A price row inserted",
                     "likely_cause": "Insert mapping missing"},
                ],
                "results": [],
            },
            "autofix": {
                "dispatched": [{"seam": "workflow-definition", "ok": True, "ran": True,
                                "summary": "orphan_wiring_pass wired 2, unresolved 3"}],
                "skipped_seams": [],
                "residual_hints": [],
            },
            "second_run": {
                "gate_summary": {"passed": 1, "total": 2, "failed": 1,
                                 "duration_ms": 42_000, "ok": False, "mode": "warn"},
                "hints": [], "results": [],
            },
        },
    })
    text = format_verify_summary(row)
    assert "primary-scan" in text
    assert "workflow-definition" in text
    assert "Workflow never reached terminal" in text
    assert "orphan_wiring_pass" in text
    # Second-run verdict landed.
    assert "still failing" in text or "clean" in text


def test_journey_second_run_clean_verdict():
    row = _base_row(report={
        "journey": {
            "first_run": {"gate_summary": {"passed": 0, "total": 1, "failed": 1,
                                           "ok": False, "mode": "warn", "duration_ms": 0},
                          "hints": [], "results": []},
            "autofix": {"dispatched": [], "skipped_seams": [], "residual_hints": []},
            "second_run": {"gate_summary": {"passed": 1, "total": 1, "failed": 0,
                                            "ok": True, "mode": "warn", "duration_ms": 0},
                            "hints": [], "results": []},
        },
    })
    text = format_verify_summary(row)
    assert "clean" in text


def test_json_view_preserves_structure():
    row = _base_row(report={
        "faults": [{"route": "/x", "classification": "y", "summary": "z"}],
        "journey": {
            "first_run": {"gate_summary": {"passed": 0, "total": 1, "failed": 1,
                                           "ok": False, "mode": "warn", "duration_ms": 0},
                          "hints": [{"journey_slug": "a", "target_seam": "b"}],
                          "results": [{"slug": "a", "status": "failed"}]},
            "autofix": {"dispatched": [], "skipped_seams": [], "residual_hints": []},
            "second_run": None,
        },
    })
    j = format_verify_report_json(row)
    assert j["interactions"]["passed"] == 12
    assert j["faults"][0]["route"] == "/x"
    assert j["journey"]["first_run"]["hints"][0]["journey_slug"] == "a"
    assert j["journey"]["second_run"] is None


def test_empty_report_still_renders():
    text = format_verify_summary(_base_row(report=None))
    assert "12/12" in text
    assert "no faults" in text


def test_journey_summary_includes_artifact_paths_when_present():
    row = _base_row(report={
        "journey": {
            "first_run": {
                "gate_summary": {"passed": 0, "total": 1, "failed": 1,
                                 "ok": False, "mode": "warn", "duration_ms": 30_000},
                "hints": [{"journey_slug": "primary-scan",
                           "target_seam": "workflow-definition",
                           "failing_step": "step-x",
                           "likely_cause": "y"}],
                "results": [{"slug": "primary-scan", "status": "failed",
                             "artifacts": [
                                 "/tmp/journeys/test-results/scan/trace.zip",
                                 "/tmp/journeys/test-results/scan/screenshot.png",
                             ]}],
            },
            "autofix": {"dispatched": [], "skipped_seams": [], "residual_hints": []},
            "second_run": None,
        },
    })
    text = format_verify_summary(row)
    assert "trace.zip" in text
    assert "screenshot.png" in text


def test_json_view_caps_and_flags_has_more():
    row = _base_row(report={
        "faults": [{"route": f"/r{i}", "classification": "c", "summary": "s"}
                   for i in range(15)],
    })
    j = format_verify_report_json(row, top_n=5)
    assert len(j["faults"]) == 5
    assert j["faults_has_more"] is True
    assert j["_pagination"]["top_n"] == 5


def test_accepts_object_like_row():
    """SQLAlchemy models — attr access not dict access."""
    class FakeRow:
        id = "x"; status = "done"; error = None
        interactions_run = 3; interactions_passed = 3
        faults_count = 0; rounds_run = 1
        report = {}
    text = format_verify_summary(FakeRow())
    assert "3/3" in text

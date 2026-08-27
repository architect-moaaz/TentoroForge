"""Unit tests for the journey-verifier remediation classifier."""
from __future__ import annotations

from services.journey_verifier.remediation import (
    build_hints,
    classify_failure,
)


def test_login_failure_maps_to_auth_seed():
    h = classify_failure(
        journey_slug="primary-scan",
        failing_step="Sign in",
        failure="Invalid email or password",
        step_kind="login_as",
    )
    assert h.target_seam == "auth-seed"
    assert "admin@example.com" in h.hint


def test_upload_failure_maps_to_component_wiring():
    h = classify_failure(
        journey_slug="primary-scan",
        failing_step="Upload product image",
        failure="upload never completed within 30000ms",
        step_kind="upload",
    )
    assert h.target_seam == "component-wiring"
    assert "FileUpload" in h.hint or "CameraCapture" in h.hint


def test_workflow_timeout_maps_to_workflow_definition():
    h = classify_failure(
        journey_slug="primary-scan",
        failing_step="Workflow runs to terminal",
        failure="wait_for_workflow timed out: scan-product-workflow not terminal",
        step_kind="wait_for_workflow",
    )
    assert h.target_seam == "workflow-definition"


def test_missing_row_maps_to_output_mapping():
    h = classify_failure(
        journey_slug="primary-scan",
        failing_step="At least one price row inserted",
        failure="no rows found in price_results",
        step_kind="assert_entity",
    )
    assert h.target_seam == "workflow-output-mapping"


def test_click_failure_maps_to_page_schema():
    h = classify_failure(
        journey_slug="primary-scan",
        failing_step="Submit scan",
        failure="button not found",
        step_kind="click",
    )
    assert h.target_seam == "page-schema"


def test_console_failure_maps_to_runtime_binding():
    h = classify_failure(
        journey_slug="smoke-home",
        failing_step="No console errors",
        failure="Warning: React error #31 at /",
        step_kind="assert_no_console_errors",
    )
    assert h.target_seam == "runtime-binding"


def test_unknown_kind_returns_unknown_bucket():
    h = classify_failure(
        journey_slug="x",
        failing_step="something obscure",
        failure="who knows",
        step_kind="unheard_of",
    )
    assert h.target_seam == "unknown"


def test_infer_kind_from_step_name_alone():
    # No step_kind — classifier must infer from the step_name.
    h = classify_failure(
        journey_slug="x",
        failing_step="Sign in as admin",
        failure="",
        step_kind=None,
    )
    assert h.target_seam == "auth-seed"


def test_build_hints_skips_passed_journeys():
    hints = build_hints([
        {"slug": "a", "status": "passed",
         "failing_step": None, "failure": None},
        {"slug": "b", "status": "failed",
         "failing_step": "Upload product image",
         "failure": "timed out"},
    ])
    assert len(hints) == 1
    assert hints[0].journey_slug == "b"


def test_build_hints_handles_empty_and_missing_fields():
    # Robust to sparse dicts (some Playwright versions omit failing_step).
    hints = build_hints([{"slug": "x", "status": "failed"}])
    assert len(hints) == 1
    assert hints[0].target_seam == "unknown"


def test_hint_to_dict_is_serializable():
    import json
    h = classify_failure("s", "Sign in", "err", "login_as")
    payload = h.to_dict()
    # Round-trip through JSON — pipeline persists this to disk + SSE.
    assert json.loads(json.dumps(payload)) == payload

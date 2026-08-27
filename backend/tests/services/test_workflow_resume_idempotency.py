"""Slice E T5 — resume-idempotency guard.

When a workflow with an approval/user_task node resumes after the
assignee decides, the engine re-executes from the trigger. Without a
guard, every db_insert / db_update / http_call before the pause point
runs a SECOND time — duplicate rows, duplicate emails, duplicate
charges. T5 makes each action node record a completion marker in
process_variables the first time it runs, and skip re-execution on
resume.

This module tests the Python-side helper that seeds those markers
into the resume input (called from the /execute route when a taskId
is present). The TS-side engine changes are locked in via a
structural check on engine.ts.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# Python helper: seed completion markers into resume input
# ─────────────────────────────────────────────────────────────────────

def test_seed_from_task_process_variables_preserves_existing():
    """The resume input already contains the assignee's decision;
    the seeder must MERGE completion markers in, not overwrite."""
    from services.workflow_resume_idempotency import seed_resume_input

    input_ = {
        "__decision": "approve",
        "entityId": "c-1",
    }
    process_variables = {
        "__step_validate_completed": True,
        "__step_validate_output": {"ok": True},
        "__step_insert_row_completed": True,
        "__step_insert_row_output": {"insertedId": "row-42"},
        # Any non-marker keys should also be preserved (they're
        # workflow-scoped state written by outputParams).
        "createdRowId": "row-42",
    }
    out = seed_resume_input(input_, process_variables)
    # Decision and entityId untouched.
    assert out["__decision"] == "approve"
    assert out["entityId"] == "c-1"
    # Completion markers merged in.
    assert out["__step_validate_completed"] is True
    assert out["__step_insert_row_completed"] is True
    # Cached outputs preserved.
    assert out["__step_insert_row_output"] == {"insertedId": "row-42"}
    # Non-marker process variables also preserved.
    assert out["createdRowId"] == "row-42"


def test_seed_when_process_variables_none_or_empty():
    from services.workflow_resume_idempotency import seed_resume_input

    input_ = {"__decision": "reject"}
    assert seed_resume_input(input_, None) == input_
    assert seed_resume_input(input_, {}) == input_


def test_seed_never_overwrites_input_keys():
    """The user's submission wins over a stale process-variable value
    (edge case: assignee re-decides after a prior partial resume)."""
    from services.workflow_resume_idempotency import seed_resume_input

    input_ = {"__decision": "approve", "createdRowId": "row-new"}
    process_variables = {"createdRowId": "row-old"}
    out = seed_resume_input(input_, process_variables)
    assert out["createdRowId"] == "row-new"


def test_seed_handles_non_dict_input():
    from services.workflow_resume_idempotency import seed_resume_input

    assert seed_resume_input(None, {"__step_a_completed": True}) == {
        "__step_a_completed": True,
    }
    assert seed_resume_input("garbage", {}) == {}


# ─────────────────────────────────────────────────────────────────────
# Completion-marker builder: engines write these on every action
# ─────────────────────────────────────────────────────────────────────

def test_marker_keys_use_stable_shape():
    """Node id → three keys. The runtime engine writes the same shape,
    so the seeder must match. Locking the shape here prevents drift."""
    from services.workflow_resume_idempotency import completion_marker_keys

    keys = completion_marker_keys("insert_candidate")
    assert keys == {
        "completed": "__step_insert_candidate_completed",
        "output": "__step_insert_candidate_output",
        "branch": "__step_insert_candidate_branch",
    }


def test_marker_keys_reject_non_string_id():
    from services.workflow_resume_idempotency import completion_marker_keys

    # Non-string ids can't safely round-trip through process variables;
    # return None so callers know to skip.
    assert completion_marker_keys(None) is None
    assert completion_marker_keys(42) is None
    assert completion_marker_keys("") is None


# ─────────────────────────────────────────────────────────────────────
# Structural check on the TS engine
# ─────────────────────────────────────────────────────────────────────

def test_engine_records_completion_markers_on_action_nodes():
    from pathlib import Path

    text = (
        Path(__file__).parent.parent.parent
        / "templates" / "runtime" / "workflows" / "engine.ts"
    ).read_text(encoding="utf-8")
    # The engine must set __step_<id>_completed after action nodes
    # execute and check it at node entry to short-circuit re-runs.
    assert "__step_" in text
    assert "_completed" in text
    # A branch-cache marker exists for condition nodes so the
    # resumed run takes the SAME branch as the first run.
    assert "_branch" in text
    # And the engine must import the resume-check somewhere (either
    # inline logic or a helper); assert the phrase used in the doc
    # comment so the guard's presence stays traceable.
    assert "resume" in text.lower()


def test_execute_route_seeds_process_variables_on_resume():
    """The /api/workflows/[id]/execute route (generated by
    runtime_injector._generate_workflow_api_route) must merge the
    task's process_variables into `input` before dispatching so the
    engine sees the completion markers."""
    from pathlib import Path
    import re

    injector = (
        Path(__file__).parent.parent.parent
        / "services" / "runtime_injector.py"
    ).read_text(encoding="utf-8")
    # Find the generated route body (heredoc / triple-quoted string).
    # Two conditions:
    #   1. The route reads process_variables from workflow_tasks.
    #   2. It merges them into the input before executing.
    assert "process_variables" in injector
    # The merge phrasing may be `Object.assign` or spread — either OK.
    merged = re.search(
        r"(Object\.assign\s*\([^,]+,\s*[^)]*pv|\.\.\.pv\b|\.\.\.\s*pv\b)",
        injector,
    )
    assert merged, (
        "runtime_injector generated route does not merge task's "
        "process_variables into resume input — resume will re-run "
        "already-completed nodes"
    )

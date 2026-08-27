"""IRF-M5-T4 wire-up — SSE event + EditRecord bookkeeping for StagePlan.

The three ``stage_plan.plan_for_*`` free functions describe what a stage
intends to do. This module bridges that description to two live
side-effects the pipeline actually surfaces:

1. An SSE ``stage_plan`` event so the frontend can render a
   ``StagePlanChip`` (analogous to ``progress`` / ``self_heal`` chips)
   right before the stage runs — the user sees "About to emit 8 page
   schemas + wire 5 workflows" one turn before the LLM output.
2. An ``EditRecord`` on the ambient ``SessionContext`` so Smith turns
   see the just-completed stages in ``session_history.edit_history``
   (M5-T9 already surfaces this to Smith).

Both effects are best-effort — a helper failure never blocks the
pipeline. Callers use ``preview()`` to build the SSE event dict and
``record_after()`` after the stage finishes.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Callable

from services.session_context import EditRecord, current as _current_ctx
from services.stage_plan import (
    StagePlan,
    plan_for_page_schema_agent,
    plan_for_planner,
    plan_for_workflow_author,
)

logger = logging.getLogger(__name__)


AuthorFn = Callable[[Any], StagePlan]


# Public alias — keeps callers from importing three names.
AUTHORS: dict[str, AuthorFn] = {
    "planner": plan_for_planner,
    "page_schema_agent": plan_for_page_schema_agent,
    "workflow_author": plan_for_workflow_author,
}


def preview(stage_name: str, ctx: Any = None) -> dict[str, Any]:
    """Return an SSE-shaped dict describing what ``stage_name`` intends
    to do next. Uses the ambient SessionContext when ``ctx`` is None.

    Returns a payload matching the shape sse_helpers.sse_event expects
    (``{"type": "stage_plan", "data": {…}}`` after wrapping). The
    caller wraps this via ``sse_event("stage_plan", preview(...))`` —
    kept split so unit tests don't import the SSE helper.
    """
    author = AUTHORS.get(stage_name)
    if author is None:
        return {
            "stage": stage_name,
            "intent": "",
            "files_to_touch": [],
            "files_to_read": [],
            "expected_bindings": [],
            "expected_workflows": [],
            "error": f"unknown stage {stage_name!r}",
        }
    session_ctx = ctx if ctx is not None else _current_ctx()
    if session_ctx is None:
        return {
            "stage": stage_name,
            "intent": "",
            "files_to_touch": [],
            "files_to_read": [],
            "expected_bindings": [],
            "expected_workflows": [],
        }
    try:
        sp = author(session_ctx)
    except Exception as exc:  # noqa: BLE001
        logger.debug("stage_plan preview(%s) failed: %s", stage_name, exc)
        return {"stage": stage_name, "intent": "", "error": str(exc),
                "files_to_touch": [], "files_to_read": [],
                "expected_bindings": [], "expected_workflows": []}
    return {
        "stage": sp.stage_name,
        "intent": sp.intent,
        "files_to_touch": list(sp.files_to_touch),
        "files_to_read": list(sp.files_to_read),
        "expected_bindings": list(sp.expected_bindings),
        "expected_workflows": list(sp.expected_workflows),
    }


def record_after(stage_name: str, ctx: Any = None, *,
                 reason: str = "") -> EditRecord | None:
    """After a stage finishes, append an EditRecord to the ambient
    SessionContext. Deterministic — the file list comes from the same
    StagePlan.files_to_touch the SSE preview used.

    Returns the record (for tests) or None when nothing happened
    (unknown stage, no context, or duck-typed failure)."""
    author = AUTHORS.get(stage_name)
    if author is None:
        return None
    session_ctx = ctx if ctx is not None else _current_ctx()
    if session_ctx is None:
        return None
    try:
        sp = author(session_ctx)
    except Exception as exc:  # noqa: BLE001
        logger.debug("stage_plan record_after(%s) failed: %s", stage_name, exc)
        return None
    record = EditRecord(
        stage=sp.stage_name,
        intent=sp.intent,
        files_touched=list(sp.files_to_touch),
        reason=reason,
    )
    try:
        session_ctx.record_edit(record)
    except AttributeError:
        # SessionContext-shape mismatch (unexpected). Skip silently.
        return None
    return record


__all__ = ["preview", "record_after", "AUTHORS"]

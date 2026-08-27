"""Slice E T5 — helpers for resume-idempotency.

The runtime engine re-executes a workflow from the trigger on every
``executeWorkflow`` call. When a workflow resumes after an approval /
user_task, without a guard every ``db_insert`` / ``db_update`` /
``http_call`` upstream of the pause runs a second time — duplicate
rows, duplicate emails, duplicate charges.

Guard shape: each action / condition / wait node writes a per-node
completion marker into process variables when it finishes:

    __step_<nodeId>_completed  → true
    __step_<nodeId>_output     → the node's returned output
    __step_<nodeId>_branch     → (conditions only) which edges were taken

On resume, the same variables are re-seeded into the workflow input
(via the /execute route reading ``workflow_tasks.process_variables``).
The engine checks the ``_completed`` marker at node entry and
short-circuits — returning the cached output and following the same
edges.

This module is the Python side: it names the marker keys so the
seeder + the engine agree, and merges markers into the resume input.
The actual engine short-circuit is in
``backend/templates/runtime/workflows/engine.ts``.
"""
from __future__ import annotations

from typing import Any


def completion_marker_keys(node_id: Any) -> dict[str, str] | None:
    """Return the three process-variable keys used by node ``node_id``
    for completion tracking. Non-string ids return ``None`` — process
    variables round-trip through JSON, so anything non-string can't
    be trusted."""
    if not isinstance(node_id, str) or not node_id:
        return None
    return {
        "completed": f"__step_{node_id}_completed",
        "output": f"__step_{node_id}_output",
        "branch": f"__step_{node_id}_branch",
    }


def seed_resume_input(
    input_: Any,
    process_variables: Any,
) -> dict[str, Any]:
    """Merge a paused workflow's ``process_variables`` into the resume
    ``input_`` so the engine sees the per-node completion markers.

    Rules:
      - Existing keys on ``input_`` win (the user's fresh submission
        beats stale process state).
      - ``process_variables`` is optional — a resume from a workflow
        that never wrote markers just returns ``input_`` unchanged.
      - Non-dict ``input_`` is treated as an empty dict.
    """
    merged: dict[str, Any] = {}
    if isinstance(process_variables, dict):
        for k, v in process_variables.items():
            if isinstance(k, str):
                merged[k] = v
    if isinstance(input_, dict):
        for k, v in input_.items():
            merged[k] = v  # input wins over process_variables
    return merged

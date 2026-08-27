"""Slice E T4 — inject a ``send_notification`` step immediately before
every ``user_task`` / ``approval`` step that isn't already preceded by
one.

Rationale: a human task without a notification is dead — the assignee
never learns the queue has grown. The planner is prompted to emit
notifications but often forgets on complex flows, and even when it
remembers it may place the notification at the wrong point (after the
task, where no one will ever see it). This pass makes the
"assignee-notified-when-task-created" invariant structural.

Opt-out: a task node with ``notification: {"kind": "none"}`` is skipped
so an authored plan can deliberately silence a task (e.g. a
system-only step).

The pass is pure — takes a plan dict, returns a modified copy. The
post_generate_fixes wrapper calls it against ``plan.json`` and rewrites
the file if anything changed.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


HUMAN_TASK_TYPES: frozenset[str] = frozenset({"user_task", "approval"})


def _humanize(name: str) -> str:
    """Convert ``snake_or_camelCase`` step name to a human phrase."""
    if not isinstance(name, str):
        return "task"
    # Split snake_case + camelCase; keep it dumb.
    tokens: list[str] = []
    buf = ""
    for ch in name:
        if ch == "_":
            if buf:
                tokens.append(buf)
                buf = ""
        elif ch.isupper() and buf and buf[-1].islower():
            tokens.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return " ".join(tokens).strip() or "task"


def _default_notification_for(step: dict[str, Any], bank: Any = None) -> dict[str, Any]:
    """Build the send_notification step to insert before ``step``.

    Spec C3 — when ``bank`` (brief.content_bank) is provided, prefer
    the bank's ``notifications.task_assigned`` template (with
    {task_kind} substitution) over the generic "Action required: X"
    fallback. Falls back silently to the generic strings when the bank
    is absent or missing the key.
    """
    step_name = step.get("name") or "task"
    human = _humanize(str(step_name))
    role = (step.get("assignment") or {}).get("role") \
        or (step.get("config") or {}).get("assigneeRole") \
        or (step.get("config") or {}).get("recipientRole") \
        or "admin"
    subject_fallback = f"Action required: {human}"
    message_fallback = f"A {human} task is waiting for you."
    subject = subject_fallback
    message = message_fallback
    if bank is not None:
        try:
            from services.content_bank_reader import notification as _bank_notif
            subject = _bank_notif(bank, "task_assigned", subject_fallback, task_kind=human)
            # message is derived from approval_needed as a secondary hook;
            # if absent, use the same template as the subject with a body prefix.
            message = _bank_notif(bank, "approval_needed", message_fallback,
                                  task_kind=human, entity_singular=human)
        except Exception:
            subject, message = subject_fallback, message_fallback
    return {
        "name": f"notify_{step_name}",
        "node_type": "send_notification",
        "config": {
            "actionType": "send_notification",
            "recipientRole": role,
            "subject": subject,
            "message": message,
        },
        # Marker so the idempotency check knows this was auto-inserted.
        "_forge_generated": "task_notification_defaults",
    }


def _already_notified(steps: list[dict[str, Any]], idx: int) -> bool:
    """True when the immediately preceding step is a send_notification."""
    if idx == 0:
        return False
    prev = steps[idx - 1] or {}
    if prev.get("node_type") == "send_notification":
        return True
    prev_action = (prev.get("config") or {}).get("actionType")
    return prev_action == "send_notification"


def inject_missing_notifications(
    plan: dict[str, Any],
    return_stats: bool = False,
    bank: Any = None,
) -> Any:
    """Walk every workflow's steps and insert a default
    send_notification before any human-task step that lacks one.

    ``return_stats=True`` returns ``(plan, stats)`` where stats has
    ``inserted`` (total steps added) and ``workflows_touched``.
    """
    if not isinstance(plan, dict):
        return (plan, {"inserted": 0, "workflows_touched": 0}) if return_stats else plan

    workflows = plan.get("workflows")
    if not isinstance(workflows, list):
        return (plan, {"inserted": 0, "workflows_touched": 0}) if return_stats else plan

    inserted = 0
    touched = 0
    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        steps = wf.get("steps")
        if not isinstance(steps, list):
            continue

        wf_inserted_before = inserted
        new_steps: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                new_steps.append(step)
                continue
            nt = step.get("node_type") or step.get("type")
            if nt not in HUMAN_TASK_TYPES:
                new_steps.append(step)
                continue
            if (step.get("notification") or {}).get("kind") == "none":
                new_steps.append(step)
                continue
            if _already_notified(new_steps, len(new_steps)):
                new_steps.append(step)
                continue
            new_steps.append(_default_notification_for(step, bank=bank))
            new_steps.append(step)
            inserted += 1

        if inserted > wf_inserted_before:
            wf["steps"] = new_steps
            touched += 1

    if return_stats:
        return plan, {"inserted": inserted, "workflows_touched": touched}
    return plan


def inject_missing_notifications_in_file(plan_path: str) -> dict[str, Any]:
    """File-mode entry point used by post_generate_fixes. Reads the
    plan.json, runs the pass, rewrites only if changed."""
    import json
    from pathlib import Path

    p = Path(plan_path)
    if not p.is_file():
        return {"ok": False, "reason": "no_plan", "inserted": 0}
    try:
        original_text = p.read_text(encoding="utf-8")
        plan = json.loads(original_text)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"unreadable: {e}", "inserted": 0}

    # Spec C3 — load brief.content_bank from <output_dir>/contracts/brief.json.
    # plan.json lives at <output_dir>/src/contracts/plan.json → output_dir is
    # two parents up. Failure is silent; the generic subject/message fallback
    # still fires.
    bank = None
    try:
        output_dir = p.parent.parent.parent
        from services.design_brief_editor import read_brief
        _brief = read_brief(output_dir)
        bank = getattr(_brief, "content_bank", None) if _brief is not None else None
    except Exception:
        bank = None

    _plan, stats = inject_missing_notifications(deepcopy(plan), return_stats=True, bank=bank)
    if stats["inserted"] == 0:
        return {"ok": True, "inserted": 0, "workflows_touched": 0}

    p.write_text(json.dumps(_plan, indent=2), encoding="utf-8")
    return {"ok": True, **stats}

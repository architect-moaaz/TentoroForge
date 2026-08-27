"""Slice E T4 — auto-emit ``send_notification`` before every ``user_task`` /
``approval`` step so the assignee learns about the task.

Semantics: pending human tasks are useless without someone being told
they have work to do. Not every planner run remembers to emit a
notification — this post-generate pass ensures every human-task node
gets a notification injected immediately before it, so when the
workflow reaches the pause point the assignee (identified via the
node's ``assignment`` block) has already been pinged.

Opt-out: a node with ``notification: {"kind": "none"}`` is skipped.

The pass is idempotent — running twice does not duplicate.
"""
from __future__ import annotations

from copy import deepcopy


# ─────────────────────────────────────────────────────────────────────
# Basic behaviour
# ─────────────────────────────────────────────────────────────────────

def test_inserts_notification_before_lone_approval():
    from services.task_notification_defaults import inject_missing_notifications

    plan = {
        "workflows": [
            {
                "name": "RefundApproval",
                "steps": [
                    {"name": "prep", "node_type": "db_query"},
                    {
                        "name": "manager_review",
                        "node_type": "approval",
                        "assignment": {"strategy": "role", "role": "manager"},
                    },
                    {"name": "process", "node_type": "db_query"},
                ],
            }
        ]
    }
    out = inject_missing_notifications(deepcopy(plan))
    steps = out["workflows"][0]["steps"]
    names = [s["name"] for s in steps]
    idx = names.index("manager_review")
    # New notification inserted just before manager_review.
    assert steps[idx - 1]["node_type"] == "send_notification"
    # Preserves original manager_review + downstream.
    assert names[idx + 1] == "process"


def test_derived_notification_names_the_task_and_role():
    from services.task_notification_defaults import inject_missing_notifications

    plan = {
        "workflows": [
            {
                "name": "RefundApproval",
                "steps": [
                    {
                        "name": "manager_review",
                        "node_type": "approval",
                        "assignment": {"strategy": "role", "role": "Manager"},
                    }
                ],
            }
        ]
    }
    out = inject_missing_notifications(plan)
    notify = out["workflows"][0]["steps"][0]
    assert notify["node_type"] == "send_notification"
    cfg = notify.get("config") or {}
    # Recipient comes from the assignment.role.
    assert cfg.get("recipientRole") == "Manager"
    # Human-readable subject/message mentions the task.
    subject = (cfg.get("subject") or cfg.get("message") or "").lower()
    assert "manager review" in subject or "review" in subject


def test_user_task_gets_notification_too():
    """Not just `approval` — `user_task` type also earns one."""
    from services.task_notification_defaults import inject_missing_notifications

    plan = {
        "workflows": [
            {
                "name": "OnboardCandidate",
                "steps": [
                    {
                        "name": "collect_docs",
                        "node_type": "user_task",
                        "assignment": {"strategy": "role", "role": "hr"},
                    }
                ],
            }
        ]
    }
    out = inject_missing_notifications(plan)
    types = [s["node_type"] for s in out["workflows"][0]["steps"]]
    assert types == ["send_notification", "user_task"]


# ─────────────────────────────────────────────────────────────────────
# Skip conditions
# ─────────────────────────────────────────────────────────────────────

def test_skips_when_preceded_by_existing_notification():
    from services.task_notification_defaults import inject_missing_notifications

    plan = {
        "workflows": [
            {
                "name": "W",
                "steps": [
                    {
                        "name": "notify_reviewer",
                        "node_type": "send_notification",
                        "config": {"recipientRole": "manager", "message": "please review"},
                    },
                    {
                        "name": "review",
                        "node_type": "approval",
                        "assignment": {"strategy": "role", "role": "manager"},
                    },
                ],
            }
        ]
    }
    out = inject_missing_notifications(deepcopy(plan))
    # Unchanged — planner already put one there.
    assert out == plan


def test_skips_when_explicit_opt_out():
    from services.task_notification_defaults import inject_missing_notifications

    plan = {
        "workflows": [
            {
                "name": "W",
                "steps": [
                    {
                        "name": "silent_task",
                        "node_type": "user_task",
                        "notification": {"kind": "none"},
                        "assignment": {"strategy": "role", "role": "admin"},
                    }
                ],
            }
        ]
    }
    out = inject_missing_notifications(deepcopy(plan))
    assert out == plan


def test_idempotent_after_previous_pass_inserted_one():
    """Running the pass twice produces the same result as running once."""
    from services.task_notification_defaults import inject_missing_notifications

    plan = {
        "workflows": [
            {
                "name": "W",
                "steps": [
                    {
                        "name": "review",
                        "node_type": "approval",
                        "assignment": {"strategy": "role", "role": "manager"},
                    }
                ],
            }
        ]
    }
    once = inject_missing_notifications(deepcopy(plan))
    twice = inject_missing_notifications(deepcopy(once))
    assert once == twice
    # Exactly one notification, not two.
    types = [s["node_type"] for s in twice["workflows"][0]["steps"]]
    assert types.count("send_notification") == 1


# ─────────────────────────────────────────────────────────────────────
# Multiple approvals in one workflow
# ─────────────────────────────────────────────────────────────────────

def test_handles_multiple_approvals_independently():
    from services.task_notification_defaults import inject_missing_notifications

    plan = {
        "workflows": [
            {
                "name": "TwoStep",
                "steps": [
                    {
                        "name": "first_approval",
                        "node_type": "approval",
                        "assignment": {"strategy": "role", "role": "manager"},
                    },
                    {"name": "sync", "node_type": "db_query"},
                    {
                        "name": "second_approval",
                        "node_type": "approval",
                        "assignment": {"strategy": "role", "role": "director"},
                    },
                ],
            }
        ]
    }
    out = inject_missing_notifications(plan)
    types = [s["node_type"] for s in out["workflows"][0]["steps"]]
    # Two notifications, one before each approval.
    assert types == [
        "send_notification",
        "approval",
        "db_query",
        "send_notification",
        "approval",
    ]


# ─────────────────────────────────────────────────────────────────────
# Pass returns count of insertions so the pipeline can log
# ─────────────────────────────────────────────────────────────────────

def test_pass_reports_insert_count():
    from services.task_notification_defaults import inject_missing_notifications

    plan = {
        "workflows": [
            {"name": "A", "steps": [{"name": "a", "node_type": "approval"}]},
            {"name": "B", "steps": [{"name": "b", "node_type": "user_task"}]},
        ]
    }
    out = inject_missing_notifications(plan, return_stats=True)
    # Old shape (plan) + new stats dict as tuple.
    plan_out, stats = out
    assert stats["inserted"] == 2
    assert stats["workflows_touched"] == 2


def test_pass_no_op_on_plan_without_workflows():
    from services.task_notification_defaults import inject_missing_notifications

    assert inject_missing_notifications({"workflows": []}) == {"workflows": []}
    assert inject_missing_notifications({}) == {}

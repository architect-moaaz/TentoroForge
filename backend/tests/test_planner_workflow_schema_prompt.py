"""Guard: both planner prompts must document the EXPLICIT connected workflow-step
graph (mandatory `next`/`branches`, gateways, and the connectivity heading), so the
upstream fix that makes the model emit connected workflows can't silently regress.
"""
import re

from agents.planner import (
    PLANNER_SYSTEM_PROMPT,
    _ONESHOT_SYSTEM_PROMPT,
    _sanitize_page_actions,
)


def _markers(prompt: str) -> None:
    # Mandatory connectivity keys are documented.
    assert '"next"' in prompt
    assert '"branches"' in prompt
    # The gateway node type is documented.
    assert "exclusive_gateway" in prompt
    # A branches example wiring true/false to step ids appears.
    assert re.search(r'"branches"\s*:\s*\{\s*"true"\s*:', prompt), (
        "expected a branches example mapping 'true' to a step id"
    )
    # The mandatory-connectivity heading is present.
    assert "CONNECTIVITY IS MANDATORY" in prompt


def test_planner_system_prompt_documents_connected_graph():
    _markers(PLANNER_SYSTEM_PROMPT)


def test_oneshot_system_prompt_documents_connected_graph():
    _markers(_ONESHOT_SYSTEM_PROMPT)


def test_no_legacy_node_type_action_step_example():
    # The old `{"name":..., "node_type":..., "action":...}` step shape must be gone
    # from the workflow-step examples in both prompts.
    for prompt in (PLANNER_SYSTEM_PROMPT, _ONESHOT_SYSTEM_PROMPT):
        assert '"node_type": "condition"' not in prompt
        assert '"node_type": "send_notification"' not in prompt


# ── Slice 3: action intent is additive + backward-compatible ────────────────

def test_prompts_document_optional_action_contract_keys():
    for prompt in (PLANNER_SYSTEM_PROMPT, _ONESHOT_SYSTEM_PROMPT):
        assert "input_map" in prompt
        assert "requires_record" in prompt


def test_sanitize_actions_backward_compatible_without_new_keys():
    # An action WITHOUT input_map/requires_record must be emitted exactly as before.
    plan = {
        "workflows": [{"name": "ApprovalWorkflow"}],
        "pages": [{
            "route": "/r", "actions": [
                {"label": "Approve", "workflow": "ApprovalWorkflow", "kind": "row_action"},
            ],
        }],
    }
    out = _sanitize_page_actions(plan)
    assert out["pages"][0]["actions"] == [
        {"label": "Approve", "workflow": "ApprovalWorkflow", "kind": "row_action"},
    ]


def test_sanitize_actions_preserves_valid_new_keys():
    plan = {
        "workflows": [{"name": "ApprovalWorkflow"}],
        "pages": [{
            "route": "/r", "actions": [
                {"label": "Approve", "workflow": "ApprovalWorkflow", "kind": "row_action",
                 "input_map": {"status": "status"}, "requires_record": True},
            ],
        }],
    }
    out = _sanitize_page_actions(plan)
    action = out["pages"][0]["actions"][0]
    assert action["input_map"] == {"status": "status"}
    assert action["requires_record"] is True


def test_sanitize_actions_tolerates_malformed_new_keys():
    # Non-dict input_map / non-bool requires_record are simply dropped, not kept
    # and not fatal — the action still emits its {label, workflow, kind}.
    plan = {
        "workflows": [{"name": "ApprovalWorkflow"}],
        "pages": [{
            "route": "/r", "actions": [
                {"label": "Approve", "workflow": "ApprovalWorkflow", "kind": "page_action",
                 "input_map": "not-a-dict", "requires_record": "yes"},
            ],
        }],
    }
    out = _sanitize_page_actions(plan)
    action = out["pages"][0]["actions"][0]
    assert action == {"label": "Approve", "workflow": "ApprovalWorkflow", "kind": "page_action"}

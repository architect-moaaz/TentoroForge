"""Integration test — plan_completeness_validator surfaces
action-authority errors as Violations so the planner's REVISE loop
picks them up.
"""
from __future__ import annotations

from services.plan_completeness_validator import (
    format_revise_gaps,
    validate_plan_completeness,
)


def _plan_with_actions(actions):
    return {
        # Minimal-but-valid rest of the plan so no OTHER rules fire.
        "data_models": [
            {"name": "Applicant", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True,
                 "not_null": True},
            ]},
        ],
        "workflows": [
            {"name": "ApproveRequest", "trigger": "automatic", "inputs": []},
        ],
        "pages": [
            {"name": "ApplicantList", "route": "/applicants"},
            {"name": "ApplicantDetail", "route": "/applicants/[id]",
             "actions": actions},
        ],
    }


class TestActionValidatorIntegration:
    def test_clean_plan_has_no_action_violations(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "ApproveRequest",
             "input_map": {"applicantId": {"kind": "route", "param": "id"}}},
        ])
        vs = validate_plan_completeness(plan)
        assert not any(v.rule.startswith("action_") for v in vs)

    def test_phantom_workflow_surfaces_as_violation(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "GhostWorkflow"},
        ])
        vs = validate_plan_completeness(plan)
        action_vs = [v for v in vs if v.rule.startswith("action_")]

        # TWO rules fire for one phantom, and both are correct.
        #   action_phantom_workflow_target — Slice B, _check_action_targets,
        #     which delegates to action_authority.validate_action_targets and
        #     builds its slug as f"action_{kind}" (which is why the name
        #     appears nowhere in the source).
        #   action_target_resolves — R3, _check_action_target_resolves, whose
        #     docstring says it "closes the phantom workflow class".
        # R3 was added after this test and covers the same ground, so the
        # REVISE loop is now told twice about one mistake. Worth collapsing;
        # asserted here as it is rather than pretending one of them is gone.
        assert {v.rule for v in action_vs} == {
            "action_phantom_workflow_target", "action_target_resolves"
        }
        assert all("GhostWorkflow" in v.msg for v in action_vs)

    def test_revise_output_names_the_action(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "GhostWorkflow"},
        ])
        vs = validate_plan_completeness(plan)
        gaps = format_revise_gaps(vs)
        assert "Approve" in gaps
        assert "GhostWorkflow" in gaps

    def test_bad_input_source_surfaces(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "ApproveRequest",
             "input_map": {"applicantId": {"kind": "route", "param": "wrongParam"}}},
        ])
        vs = validate_plan_completeness(plan)
        assert any(v.rule == "action_route_param_missing" for v in vs)

    def test_no_actions_declared_no_violations(self):
        # A page without an `actions` key is fine — the contract is
        # opt-in.
        vs = validate_plan_completeness(_plan_with_actions([]))
        assert not any(v.rule.startswith("action_") for v in vs)

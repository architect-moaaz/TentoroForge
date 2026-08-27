"""Tests for services.action_authority — Slice B action-button contract.

Same shape as ``test_submit_authority``. Locks the plan-level shape
(``page.actions[]``) so downstream consumers (deterministic page
builder, plan validator, planner prompt) can lean on stable output.
"""
from __future__ import annotations

import pytest

from services.action_authority import (
    _normalize_actions,
    _normalize_input_map,
    derive_button_props,
    resolve_page_actions,
    validate_action_targets,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

def _plan_with_actions(actions):
    return {
        "workflows": [
            {"name": "ApproveRequest", "inputs": []},
            {"name": "RejectRequest", "inputs": []},
        ],
        "pages": [
            {"name": "ApplicantList", "route": "/applicants"},
            {"name": "ApplicantDetail", "route": "/applicants/[id]",
             "actions": actions},
        ],
    }


# --------------------------------------------------------------------------- #
# _normalize_actions                                                           #
# --------------------------------------------------------------------------- #

class TestNormalizeActions:
    def test_normalizes_valid_workflow_action(self):
        raw = [{"label": "Approve", "kind": "workflow",
                "target": "ApproveRequest",
                "input_map": {"applicantId": {"kind": "route", "param": "id"}}}]
        out = _normalize_actions(raw)
        assert len(out) == 1
        assert out[0]["label"] == "Approve"
        assert out[0]["kind"] == "workflow"
        assert out[0]["target"] == "ApproveRequest"
        assert out[0]["input_map"] == {"applicantId": {"kind": "route", "param": "id"}}

    def test_normalizes_valid_navigate_action(self):
        raw = [{"label": "View history", "kind": "navigate",
                "target": "/applicants/[id]/history"}]
        out = _normalize_actions(raw)
        assert out[0]["kind"] == "navigate"
        assert out[0]["target"] == "/applicants/[id]/history"
        assert out[0]["input_map"] == {}

    def test_drops_entry_with_unknown_kind(self):
        raw = [{"label": "X", "kind": "hocus_pocus", "target": "Y"}]
        assert _normalize_actions(raw) == []

    def test_drops_entry_missing_target(self):
        raw = [{"label": "X", "kind": "workflow"}]
        assert _normalize_actions(raw) == []

    def test_drops_entry_missing_label(self):
        raw = [{"kind": "workflow", "target": "X"}]
        assert _normalize_actions(raw) == []

    def test_preserves_ui_hints(self):
        raw = [{"label": "Approve", "kind": "workflow", "target": "X",
                "variant": "primary", "requires_confirm": True,
                "confirmMessage": "Are you sure?", "icon": "check"}]
        out = _normalize_actions(raw)
        assert out[0]["variant"] == "primary"
        assert out[0]["requires_confirm"] is True
        assert out[0]["confirmMessage"] == "Are you sure?"
        assert out[0]["icon"] == "check"

    def test_non_list_returns_empty(self):
        assert _normalize_actions(None) == []
        assert _normalize_actions("not a list") == []


class TestNormalizeInputMap:
    def test_valid_route_spec_passes(self):
        m = _normalize_input_map({"id": {"kind": "route", "param": "id"}})
        assert m == {"id": {"kind": "route", "param": "id"}}

    def test_drops_unknown_kind(self):
        m = _normalize_input_map({"id": {"kind": "hocus_pocus"}})
        assert m == {}

    def test_drops_non_dict_spec(self):
        m = _normalize_input_map({"id": "route.id"})
        assert m == {}


# --------------------------------------------------------------------------- #
# resolve_page_actions                                                         #
# --------------------------------------------------------------------------- #

class TestResolvePageActions:
    def test_returns_normalized_actions(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "ApproveRequest"},
        ])
        actions = resolve_page_actions(plan, "ApplicantDetail")
        assert len(actions) == 1
        assert actions[0]["label"] == "Approve"

    def test_returns_empty_for_page_without_actions(self):
        plan = _plan_with_actions([])
        assert resolve_page_actions(plan, "ApplicantList") == []

    def test_returns_empty_for_missing_page(self):
        plan = _plan_with_actions([{"label": "X", "kind": "workflow",
                                    "target": "ApproveRequest"}])
        assert resolve_page_actions(plan, "DoesNotExist") == []

    def test_returns_empty_for_non_dict_plan(self):
        assert resolve_page_actions(None, "X") == []
        assert resolve_page_actions("not a plan", "X") == []


# --------------------------------------------------------------------------- #
# validate_action_targets                                                      #
# --------------------------------------------------------------------------- #

class TestValidateActionTargets:
    def test_no_errors_for_valid_plan(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "ApproveRequest",
             "input_map": {"applicantId": {"kind": "route", "param": "id"}}},
            {"label": "View list", "kind": "navigate", "target": "/applicants"},
        ])
        assert validate_action_targets(plan) == []

    def test_flags_phantom_workflow(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "SendForReview"},
        ])
        errs = validate_action_targets(plan)
        assert any(e["kind"] == "phantom_workflow_target" for e in errs)

    def test_flags_phantom_navigate(self):
        plan = _plan_with_actions([
            {"label": "Go", "kind": "navigate", "target": "/bogus"},
        ])
        errs = validate_action_targets(plan)
        assert any(e["kind"] == "phantom_navigate_target" for e in errs)

    def test_flags_unknown_action_kind(self):
        plan = _plan_with_actions([
            {"label": "X", "kind": "magic", "target": "ApproveRequest"},
        ])
        errs = validate_action_targets(plan)
        assert any(e["kind"] == "unknown_action_kind" for e in errs)

    def test_flags_missing_target(self):
        plan = _plan_with_actions([
            {"label": "X", "kind": "workflow"},
        ])
        errs = validate_action_targets(plan)
        assert any(e["kind"] == "missing_action_target" for e in errs)

    def test_flags_route_param_not_in_route(self):
        # Page route is /applicants/[id]; wire an input to a nonexistent
        # route param → flagged.
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "ApproveRequest",
             "input_map": {"applicantId": {"kind": "route", "param": "applicantId"}}},
        ])
        errs = validate_action_targets(plan)
        assert any(e["kind"] == "route_param_missing" for e in errs)

    def test_flags_unknown_source_kind(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "ApproveRequest",
             "input_map": {"applicantId": {"kind": "magic"}}},
        ])
        errs = validate_action_targets(plan)
        assert any(e["kind"] == "unknown_source_kind" for e in errs)

    def test_flags_invalid_actions_type(self):
        plan = {
            "workflows": [],
            "pages": [{"name": "X", "route": "/x", "actions": "not a list"}],
        }
        errs = validate_action_targets(plan)
        assert any(e["kind"] == "invalid_actions_type" for e in errs)

    def test_empty_actions_no_errors(self):
        plan = _plan_with_actions([])
        assert validate_action_targets(plan) == []

    def test_pages_without_actions_no_errors(self):
        # `actions` key absent entirely — page is fine.
        plan = {
            "workflows": [],
            "pages": [{"name": "X", "route": "/x"}],
        }
        assert validate_action_targets(plan) == []

    def test_reports_page_name_in_error(self):
        plan = _plan_with_actions([
            {"label": "Approve", "kind": "workflow", "target": "Ghost"},
        ])
        errs = validate_action_targets(plan)
        assert errs[0]["page"] == "ApplicantDetail"
        assert errs[0]["label"] == "Approve"


# --------------------------------------------------------------------------- #
# derive_button_props                                                          #
# --------------------------------------------------------------------------- #

class TestDeriveButtonProps:
    def test_workflow_action_becomes_workflow_prop(self):
        props = derive_button_props({
            "label": "Approve", "kind": "workflow", "target": "ApproveRequest",
            "input_map": {"applicantId": {"kind": "route", "param": "id"}},
        })
        assert props["label"] == "Approve"
        assert props["workflow"] == "ApproveRequest"
        assert props["input_map"] == {"applicantId": {"kind": "route", "param": "id"}}

    def test_navigate_action_becomes_navigate_prop(self):
        props = derive_button_props({
            "label": "History", "kind": "navigate",
            "target": "/applicants/[id]/history",
        })
        assert props["navigate"] == "/applicants/[id]/history"
        assert "workflow" not in props

    def test_passes_through_ui_hints(self):
        props = derive_button_props({
            "label": "Approve", "kind": "workflow", "target": "X",
            "variant": "primary", "requires_confirm": True,
        })
        assert props["variant"] == "primary"
        assert props["requires_confirm"] is True

    def test_empty_input_map_omitted_from_props(self):
        # Downstream shape convention: don't emit an empty input_map;
        # the runtime dispatcher treats absent = identity mapping.
        props = derive_button_props({
            "label": "X", "kind": "workflow", "target": "Y",
        })
        assert "input_map" not in props

    def test_bogus_action_returns_label_only(self):
        # Non-dict → empty. Unknown kind → just the label so the UI at
        # least renders a button (even if it's a no-op the audit will
        # flag).
        assert derive_button_props(None) == {}
        assert derive_button_props(
            {"label": "X", "kind": "magic", "target": "Y"}
        ) == {"label": "X"}

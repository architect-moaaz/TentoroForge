"""Tests for services.action_invariants — Slice B post-gen backstop.

Guarantees the invariant: every planner-declared ``page.actions``
becomes a Button node in the corresponding schema. Idempotent, never
raises. Applies to any target the planner declared.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.action_invariants import (
    _button_matches_action,
    _same_route,
    _schema_has_action,
    ensure_declared_actions_present,
)


def _write_plan(tmp_path: Path, plan: dict) -> Path:
    d = tmp_path / "src" / "contracts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "plan.json"
    p.write_text(json.dumps(plan))
    return p


def _write_schema(tmp_path: Path, name: str, schema: dict) -> Path:
    d = tmp_path / "src" / "schemas"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps(schema, indent=2))
    return p


def _detail_schema_with_header(route: str, extra_btns=None) -> dict:
    extra_btns = extra_btns or []
    return {
        "id":    "x-detail",
        "route": route,
        "root": {
            "type": "Stack",
            "props": {},
            "children": [
                {"type": "Row", "props": {"justify": "between"},
                 "children": [
                    {"type": "Heading", "props": {"content": "X", "level": 1}},
                    {"type": "Row", "props": {"gap": "tokens.spacing.2"},
                     "children": [
                        {"type": "Button", "props": {"label": "Back",
                                                     "navigate": "/x"}},
                        {"type": "Button", "props": {"label": "Edit",
                                                     "navigate": "/x/1/edit"}},
                        *extra_btns,
                    ]},
                ]},
            ],
        },
    }


class TestSameRoute:
    def test_exact(self):
        assert _same_route("/applicants/[id]", "/applicants/[id]")

    def test_brackets_vs_colon(self):
        assert _same_route("/applicants/[id]", "/applicants/:id")

    def test_trailing_slash(self):
        assert _same_route("/applicants/[id]/", "/applicants/[id]")

    def test_case_insensitive(self):
        assert _same_route("/Applicants/[ID]", "/applicants/[id]")

    def test_different_routes_no_match(self):
        assert not _same_route("/applicants", "/employees")


class TestButtonMatching:
    def test_workflow_props_match_action(self):
        assert _button_matches_action(
            {"workflow": "ApproveRequest"},
            {"kind": "workflow", "target": "ApproveRequest"},
        )

    def test_navigate_props_match_action(self):
        assert _button_matches_action(
            {"navigate": "/x/[id]/history"},
            {"kind": "navigate", "target": "/x/[id]/history"},
        )

    def test_onclick_navigate_matches(self):
        assert _button_matches_action(
            {"onClick": {"navigate": "/x"}},
            {"kind": "navigate", "target": "/x"},
        )

    def test_mismatched_target_no_match(self):
        assert not _button_matches_action(
            {"workflow": "Other"},
            {"kind": "workflow", "target": "ApproveRequest"},
        )


class TestSchemaHasAction:
    def test_true_when_button_present(self):
        schema = _detail_schema_with_header("/x/[id]", extra_btns=[
            {"type": "Button", "props": {"label": "Approve",
                                         "workflow": "ApproveRequest"}},
        ])
        assert _schema_has_action(schema, {
            "kind": "workflow", "target": "ApproveRequest",
        }) is True

    def test_false_when_button_missing(self):
        schema = _detail_schema_with_header("/x/[id]")
        assert _schema_has_action(schema, {
            "kind": "workflow", "target": "ApproveRequest",
        }) is False


class TestEnsureDeclaredActionsPresent:
    def test_inserts_missing_workflow_button(self, tmp_path: Path):
        _write_plan(tmp_path, {
            "workflows": [{"name": "ApproveRequest"}],
            "pages": [
                {"name": "ApplicantDetail", "route": "/applicants/[id]",
                 "actions": [{"label": "Approve", "kind": "workflow",
                              "target": "ApproveRequest",
                              "input_map": {"applicantId": {"kind": "route",
                                                            "param": "id"}}}]},
            ],
        })
        schema_path = _write_schema(
            tmp_path, "applicants_detail",
            _detail_schema_with_header("/applicants/[id]"),
        )
        result = ensure_declared_actions_present(str(tmp_path))
        assert len(result.inserted) == 1
        assert result.inserted[0].label == "Approve"
        # File actually updated with the new button.
        after = json.loads(schema_path.read_text())
        assert _schema_has_action(after, {
            "kind": "workflow", "target": "ApproveRequest",
        }) is True

    def test_idempotent(self, tmp_path: Path):
        _write_plan(tmp_path, {
            "workflows": [{"name": "ApproveRequest"}],
            "pages": [
                {"name": "X", "route": "/x/[id]",
                 "actions": [{"label": "Approve", "kind": "workflow",
                              "target": "ApproveRequest"}]},
            ],
        })
        _write_schema(tmp_path, "x_detail",
                      _detail_schema_with_header(
                          "/x/[id]",
                          extra_btns=[{
                              "type": "Button",
                              "props": {"label": "Approve",
                                        "workflow": "ApproveRequest"},
                          }],
                      ))
        result = ensure_declared_actions_present(str(tmp_path))
        assert result.inserted == []

    def test_no_plan_returns_empty(self, tmp_path: Path):
        # No plan file → no-op.
        result = ensure_declared_actions_present(str(tmp_path))
        assert result.inserted == []

    def test_pages_without_actions_ignored(self, tmp_path: Path):
        _write_plan(tmp_path, {
            "pages": [{"name": "X", "route": "/x", "actions": []}],
        })
        _write_schema(tmp_path, "x", {"root": {"type": "Container",
                                                "children": []}})
        result = ensure_declared_actions_present(str(tmp_path))
        assert result.inserted == []

    def test_missing_schema_recorded_as_skipped(self, tmp_path: Path):
        _write_plan(tmp_path, {
            "pages": [
                {"name": "Ghost", "route": "/ghost",
                 "actions": [{"label": "X", "kind": "navigate", "target": "/y"}]},
            ],
        })
        result = ensure_declared_actions_present(str(tmp_path))
        assert result.inserted == []
        assert any(s.get("reason", "").startswith("no schema") for s in result.skipped)

    def test_route_syntax_flex(self, tmp_path: Path):
        # Plan uses [id]; schema route uses :id. Should still match.
        _write_plan(tmp_path, {
            "workflows": [{"name": "ApproveRequest"}],
            "pages": [
                {"name": "ApplicantDetail", "route": "/applicants/[id]",
                 "actions": [{"label": "Approve", "kind": "workflow",
                              "target": "ApproveRequest"}]},
            ],
        })
        _write_schema(tmp_path, "applicant_detail",
                      _detail_schema_with_header("/applicants/:id"))
        result = ensure_declared_actions_present(str(tmp_path))
        assert len(result.inserted) == 1

    def test_multiple_actions_all_inserted(self, tmp_path: Path):
        _write_plan(tmp_path, {
            "workflows": [{"name": "Approve"}, {"name": "Reject"}],
            "pages": [
                {"name": "X", "route": "/x/[id]",
                 "actions": [
                    {"label": "Approve", "kind": "workflow", "target": "Approve"},
                    {"label": "Reject", "kind": "workflow", "target": "Reject"},
                 ]},
            ],
        })
        _write_schema(tmp_path, "x_detail",
                      _detail_schema_with_header("/x/[id]"))
        result = ensure_declared_actions_present(str(tmp_path))
        assert len(result.inserted) == 2
        labels = {r.label for r in result.inserted}
        assert labels == {"Approve", "Reject"}

"""Tests for build_detail_page consuming Slice B page.actions.

The deterministic detail-page builder emits Back + Edit as generic
navigation; ACTION-AUTHORITY declared buttons (Approve, Reject,
Escalate) are appended AFTER those, verbatim per action_authority
normalization.
"""
from __future__ import annotations

from services.deterministic_pages import build_detail_page


COLS = {
    "id": {"type": "uuid", "primaryKey": True},
    "name": {"type": "text"},
    "status": {"type": "text"},
}


def _find_buttons(schema: dict) -> list[dict]:
    """Walk the detail schema; return every Button node's props. The
    detail page's tree lives under ``page["root"]``."""
    out: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "Button":
                out.append(node.get("props") or {})
            for c in node.get("children") or []:
                walk(c)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(schema.get("root") or schema)
    return out


class TestBuildDetailPageActions:
    def test_no_page_hint_still_gets_back_and_edit(self):
        page = build_detail_page("Applicant", COLS, "/applicants/[id]", None)
        buttons = _find_buttons(page)
        labels = [b.get("label") for b in buttons]
        assert "Back" in labels
        assert "Edit" in labels
        assert len(buttons) == 2  # nothing else added

    def test_workflow_action_is_appended(self):
        hint = {"actions": [{
            "label": "Approve",
            "kind": "workflow",
            "target": "ApproveApplicant",
            "input_map": {"applicantId": {"kind": "route", "param": "id"}},
            "variant": "primary",
            "requires_confirm": True,
        }]}
        page = build_detail_page("Applicant", COLS, "/applicants/[id]",
                                 None, page_hint=hint)
        buttons = _find_buttons(page)
        labels = [b.get("label") for b in buttons]
        assert labels == ["Back", "Edit", "Approve"]
        approve = next(b for b in buttons if b.get("label") == "Approve")
        assert approve["workflow"] == "ApproveApplicant"
        assert approve["input_map"] == {
            "applicantId": {"kind": "route", "param": "id"},
        }
        assert approve["variant"] == "primary"
        assert approve["requires_confirm"] is True

    def test_navigate_action_is_appended(self):
        hint = {"actions": [{
            "label": "History",
            "kind": "navigate",
            "target": "/applicants/[id]/history",
        }]}
        page = build_detail_page("Applicant", COLS, "/applicants/[id]",
                                 None, page_hint=hint)
        buttons = _find_buttons(page)
        history = next(b for b in buttons if b.get("label") == "History")
        assert history["navigate"] == "/applicants/[id]/history"
        assert "workflow" not in history

    def test_multiple_actions_preserve_order(self):
        hint = {"actions": [
            {"label": "Approve", "kind": "workflow", "target": "Approve"},
            {"label": "Reject",  "kind": "workflow", "target": "Reject"},
        ]}
        page = build_detail_page("Applicant", COLS, "/applicants/[id]",
                                 None, page_hint=hint)
        labels = [b.get("label") for b in _find_buttons(page)]
        assert labels == ["Back", "Edit", "Approve", "Reject"]

    def test_malformed_action_is_dropped(self):
        # No kind → normalizer drops → detail page still renders cleanly.
        hint = {"actions": [
            {"label": "Approve", "target": "ApproveApplicant"},  # no kind
            {"label": "Reject",  "kind": "workflow", "target": "Reject"},
        ]}
        page = build_detail_page("Applicant", COLS, "/applicants/[id]",
                                 None, page_hint=hint)
        labels = [b.get("label") for b in _find_buttons(page)]
        assert "Approve" not in labels
        assert "Reject" in labels

    def test_empty_actions_list_is_noop(self):
        page = build_detail_page("Applicant", COLS, "/applicants/[id]",
                                 None, page_hint={"actions": []})
        labels = [b.get("label") for b in _find_buttons(page)]
        assert labels == ["Back", "Edit"]

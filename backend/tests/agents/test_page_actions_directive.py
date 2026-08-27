"""Tests for build_actions_directive — the prompt block that tells the page
schema agent to render the EXACT action buttons declared on the page."""
from agents.page_schema_agent import build_actions_directive


def test_directive_includes_each_label_and_placement():
    page = {
        "actions": [
            {"label": "Delete", "workflow": "DeleteThing", "kind": "row_action"},
            {"label": "Approve", "workflow": "ApproveThing", "kind": "page_action"},
            {"label": "New", "to": "/things/new", "kind": "navigate"},
        ]
    }
    directive = build_actions_directive(page)

    # Each exact label is present.
    assert '"Delete"' in directive
    assert '"Approve"' in directive
    assert '"New"' in directive

    # Placement phrasing per kind.
    # row_action → list row
    assert "list row" in directive
    # page_action → page-level
    assert "page-level" in directive
    # navigate → navigation
    assert "navigation" in directive

    # Must instruct not to invent workflow/onClick wiring.
    lowered = directive.lower()
    assert "onclick" in lowered or "workflow" in lowered


def test_directive_empty_when_no_actions():
    assert build_actions_directive({}) == ""
    assert build_actions_directive({"actions": []}) == ""
    assert build_actions_directive({"actions": None}) == ""

# backend/tests/agents/test_planner_actions.py
from agents.planner import _sanitize_page_actions


def test_sanitize_keeps_valid_drops_invalid():
    plan = {
        "workflows": [{"name": "ApproveWF"}],
        "pages": [
            {"route": "/r", "entity": "R", "actions": [
                {"label": "Approve", "workflow": "ApproveWF", "kind": "row_action"},
                {"label": "Ghost", "workflow": "MissingWF", "kind": "row_action"},
                {"label": "NoKind", "workflow": "ApproveWF"},
                {"workflow": "ApproveWF", "kind": "page_action"},   # no label
            ]},
            {"route": "/q", "entity": "Q"},                          # no actions
        ],
    }
    out = _sanitize_page_actions(plan)
    assert out["pages"][0]["actions"] == [
        {"label": "Approve", "workflow": "ApproveWF", "kind": "row_action"}]
    assert out["pages"][1]["actions"] == []    # normalized to empty list


def test_sanitize_is_safe_on_missing_pages():
    assert _sanitize_page_actions({}) == {}          # no pages → unchanged
    assert _sanitize_page_actions({"pages": "nope"}) == {"pages": "nope"}

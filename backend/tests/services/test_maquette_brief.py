"""The maquette reaches the page author as a brief, not as a later rewrite.

Maquettes were authored in the bootstrap band and then ignored until
post-generation, where a composer used them to overwrite the author's
work. These cover the reversed direction: the design is handed over
BEFORE the page is written, and a page with no maquette is unaffected.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.maquette_brief import build_maquette_brief


@pytest.fixture()
def app(tmp_path: Path) -> Path:
    c = tmp_path / "src" / "contracts"
    c.mkdir(parents=True)
    (c / "collection-maquettes.json").write_text(json.dumps([{
        "entity": "Event", "route": "/events", "layout": "table",
        "columns": [
            {"name": "name", "label": "Event", "kind": "text", "emphasis": True},
            {"name": "status", "label": "Status", "kind": "badge"},
        ],
        "filter_presets": [{"label": "Upcoming", "expr": "startDate > now"}],
        "hero": {"title": "Events", "subtitle": "Everything on the calendar"},
        "empty_state": {"illustration": "clipboard-blank",
                        "headline": "No events yet",
                        "subhead": "Create one to get going.",
                        "cta_label": "Create event", "cta_action": "/events/new"},
        "footer": {"kind": "insight", "content": "Total capacity"},
        "row_treatment": "status-led",
        "signature_moves": ["sticky-first-column"],
    }]))
    (c / "record-maquettes.json").write_text(json.dumps([{
        "entity": "Event", "route": "/events/[id]", "mode": "view",
        "hero": {"kind": "status-led", "title": "Event Detail"},
        "section_grouping": [
            {"label": "Overview", "fields": ["name", "status"]},
            {"label": "Details", "fields": ["description"]},
        ],
        "control_hints": {"description": "rich-text"},
        "footer": {"kind": "audit"},
    }]))
    (c / "dashboard-maquette.json").write_text(json.dumps({
        "kpis": [{"label": "Total Events", "entity": "Event", "op": "count"}],
        "primary_chart": {"kind": "bar", "title": "Tickets by Event",
                          "entity": "Ticket", "group_by": "eventId"},
        "subtitle": "How the season is tracking",
    }))
    return tmp_path


def test_collection_brief_carries_the_decided_content(app):
    b = build_maquette_brief(app, "/events", "list")
    # the decisions the author must honour
    assert "Shape: table" in b
    assert "name" in b and '"Event"' in b
    assert "the identifying column" in b          # emphasis survives
    assert "Upcoming (startDate > now)" in b      # filter chips reach the author
    assert "No events yet" in b                   # empty-state copy, not invented
    assert "sticky-first-column" in b


def test_record_brief_carries_groups_and_control_hints(app):
    b = build_maquette_brief(app, "/events/[id]", "detail")
    assert "Mode: view" in b
    assert "Overview: name, status" in b
    assert "description → rich-text" in b


def test_dashboard_brief_is_found_by_page_type_and_by_root(app):
    for route, ptype in (("/", "list"), ("/anything", "dashboard")):
        b = build_maquette_brief(app, route, ptype)
        assert "Total Events: count on Event" in b, (route, ptype)
        assert "Tickets by Event" in b


def test_the_brief_says_the_author_still_owns_the_structure():
    """The whole point of the reversal — the design decides WHAT, the
    author decides HOW. If this instruction weakens, we're back to a
    composer by another name."""
    from services.maquette_brief import build_maquette_brief as f
    import inspect
    src = inspect.getsource(f)
    assert "you do not choose the content" in src
    assert "You choose the component tree" in src


def test_a_page_with_no_maquette_gets_no_block(app):
    assert build_maquette_brief(app, "/unplanned", "list") == ""


def test_missing_or_unreadable_contracts_are_silent(tmp_path):
    assert build_maquette_brief(tmp_path, "/events", "list") == ""
    assert build_maquette_brief(None, "/events") == ""
    assert build_maquette_brief(tmp_path, "") == ""
    bad = tmp_path / "src" / "contracts"
    bad.mkdir(parents=True)
    (bad / "collection-maquettes.json").write_text("{not json")
    assert build_maquette_brief(tmp_path, "/events", "list") == ""


def test_route_matching_ignores_trailing_slash(app):
    assert build_maquette_brief(app, "/events/", "list")


def test_page_author_actually_asks_for_the_brief():
    """Guards the wiring, not just the module — the reversal is only
    real if the authoring agent calls this."""
    src = Path("agents/page_schema_agent.py").read_text()
    assert "build_maquette_brief" in src
    assert "_maq_block + " in src   # prepended to the prompt, not discarded

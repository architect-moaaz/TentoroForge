"""The entry point always exists.

A build that compiled cleanly, passed verification and opened on "This page
could not be found" — because `/`'s composition was refused, so no layout, no
schema, and the route fell through to the catch-all.
"""
from __future__ import annotations

from services.blueprint.landing_page import compose_landing


def _doc(**over):
    doc = {
        "application": {"id": "APP-1", "name": "Council"},
        "navigation": {"landing": "/", "tree": [
            {"page": "PAGE-002"}, {"page": "PAGE-010"}, {"page": "PAGE-011"}]},
        "pages": [
            {"id": "PAGE-001", "route": "/", "name": "Home",
             "pattern": "dashboard", "purpose": "Where a user lands."},
            {"id": "PAGE-010", "route": "/sessions", "name": "Sessions",
             "pattern": "entity_list"},
            {"id": "PAGE-011", "route": "/committees", "name": "Committees",
             "pattern": "entity_list"},
            {"id": "PAGE-012", "route": "/votes/[id]", "name": "Vote",
             "pattern": "record_workspace"},
            {"id": "PAGE-013", "route": "/votes/new", "name": "New vote",
             "pattern": "wizard"},
        ],
        "pageLayouts": [{"page": "PAGE-010"}, {"page": "PAGE-011"},
                        {"page": "PAGE-012"}],
    }
    doc.update(over)
    return doc


def test_the_entry_point_gets_a_layout_when_nothing_composed_one():
    body = compose_landing(_doc())
    assert body is not None
    assert body["page"] == "PAGE-001"
    assert body["composedBy"] == "deterministic"
    kinds = [c["type"] for c in body["root"]["children"]]
    assert kinds[0] == "Heading"
    assert "Grid" in kinds


def test_it_never_overwrites_a_composed_landing_page():
    """A composition the floor refused stays refused. This supplies a page
    where the model supplied none; it does not repair the model's work."""
    doc = _doc()
    doc["pageLayouts"].append({"page": "PAGE-001", "composedBy": "a2ui"})
    assert compose_landing(doc) is None


def test_it_only_links_to_pages_that_exist():
    """A tile pointing at a page nobody composed trades a 404 on arrival for a
    404 one click later."""
    body = compose_landing(_doc())
    grid = next(c for c in body["root"]["children"] if c["type"] == "Grid")
    hrefs = [c["children"][0]["props"]["href"] for c in grid["children"]]
    assert hrefs == ["/sessions", "/committees"]
    # PAGE-012 has a layout but is a dynamic route; PAGE-013 has no layout.
    assert "/votes/[id]" not in hrefs
    assert "/votes/new" not in hrefs


def test_it_falls_back_to_list_pages_when_navigation_is_empty():
    doc = _doc(navigation={"landing": "/"})
    body = compose_landing(doc)
    grid = next(c for c in body["root"]["children"] if c["type"] == "Grid")
    assert {c["children"][0]["props"]["href"] for c in grid["children"]} == {
        "/sessions", "/committees"}


def test_an_application_with_nowhere_to_go_says_so():
    """An empty grid reads as a page still loading."""
    doc = _doc(pageLayouts=[], navigation={"landing": "/"})
    body = compose_landing(doc)
    kinds = [c["type"] for c in body["root"]["children"]]
    assert "EmptyState" in kinds
    assert "Grid" not in kinds


def test_no_landing_page_declared_is_left_alone():
    doc = _doc(pages=[{"id": "PAGE-010", "route": "/sessions",
                       "pattern": "entity_list"}], navigation={})
    assert compose_landing(doc) is None

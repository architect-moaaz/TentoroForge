"""The entry point always exists.

A build that compiled cleanly, passed verification and opened on "This page
could not be found" — because `/`'s composition was refused, so no layout, no
schema, and the route fell through to the catch-all.


A NOTE ON WHY THESE ASSERTED `href`. They did, and they passed, because
they checked this module against itself: the composer wrote `href` and the
test read `href`. The catalog calls it `navigate`, and nothing here ever
asked the catalog — so the first real run produced an entry point that
could not render. The prop-name assertions below are now only meaningful
because `test_the_layout_it_writes_passes_the_check_that_gates_it` puts the
same output through `validate_props`.
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
    routes = [c["children"][0]["props"]["navigate"] for c in grid["children"]]
    assert routes == ["/sessions", "/committees"]
    # PAGE-012 has a layout but is a dynamic route; PAGE-013 has no layout.
    assert "/votes/[id]" not in routes
    assert "/votes/new" not in routes


def test_it_falls_back_to_list_pages_when_navigation_is_empty():
    doc = _doc(navigation={"landing": "/"})
    body = compose_landing(doc)
    grid = next(c for c in body["root"]["children"] if c["type"] == "Grid")
    assert {c["children"][0]["props"]["navigate"] for c in grid["children"]} == {
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


# ── the composer's own output has to be renderable ──────────────────────

def _catalog():
    from services.blueprint.page_planner import load_catalog
    return load_catalog()


def _errors(body):
    from services.blueprint.page_planner import validate_props, validate_template
    cat = _catalog()
    return validate_template(body, cat) + validate_props({"root": body["root"]}, cat)


def test_the_layout_it_writes_passes_the_check_that_gates_it():
    """THE ONE TEST THIS MODULE NEEDED AND DID NOT HAVE.

    It wrote `text` on a Heading, `href`/`text` on a Link and
    `title`/`description` on an EmptyState. The catalog says `content`,
    `navigate`/`label` and `message`, and `validate_props` refuses anything
    else — the same check `check_pattern_templates` runs before a layout is
    committed.

    So the first time this composer actually ran, the entry point got a layout
    that could not render: the exact outcome the module exists to prevent. It
    went unnoticed because A2UI composed the landing page on every project that
    had one, so this path had never run against a real Blueprint.
    """
    doc = {
        "application": {"name": "Test"},
        "pages": [
            {"id": "PAGE-001", "route": "/", "name": "Home",
             "pattern": "dashboard", "purpose": "where everyone lands"},
            {"id": "PAGE-002", "route": "/sittings", "name": "Sittings",
             "pattern": "entity_list"},
        ],
        "pageLayouts": [{"page": "PAGE-002", "root": {"type": "Stack"}}],
    }
    body = compose_landing(doc)
    assert body is not None
    assert _errors(body) == [], "the entry point's own layout cannot render"


def test_the_empty_case_is_renderable_too():
    """The branch taken when nothing else composed — the likeliest one on a
    run that went badly, and so the one that most needs to work."""
    doc = {
        "application": {"name": "Test"},
        "pages": [{"id": "PAGE-001", "route": "/", "name": "Home",
                   "pattern": "dashboard"}],
        "pageLayouts": [],
    }
    body = compose_landing(doc)
    assert body is not None
    assert _errors(body) == []


def test_a_deterministic_composer_that_emits_junk_is_worse_than_none():
    """Not a behaviour test — a statement of why the two above exist. A
    missing page is a 404 on one route. An invalid page is a PlanError that
    aborts `_project_frontend` before `project_design_tokens`, and the whole
    application stops compiling on a missing tokens.css."""
    import inspect

    from services.blueprint import orchestrator

    src = inspect.getsource(orchestrator._project_frontend)
    assert src.index("project_design_tokens") < src.index("raise PlanError")

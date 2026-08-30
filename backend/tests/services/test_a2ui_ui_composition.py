"""§34/§35 — compose the whole UI, one page per call."""

import pytest

from services.a2ui_ui_composition import compose_ui_via_a2ui, shared_context

DOC = {
    "pages": [
        {"route": "/articles", "name": "Articles", "pattern": "entity_list",
         "purpose": "Everything still unread."},
        {"route": "/articles/[id]", "name": "Article",
         "pattern": "record_workspace", "purpose": "One article."},
        {"route": "/articles/new", "name": "Save", "pattern": "form",
         "purpose": "Save a link."},
    ],
    "designSystem": {"colors": {"primary": "#125E8A"},
                     "informationDensity": "comfortable",
                     "navigationApproach": "sidebar"},
}


def _composer(applied_for=(), raises_for=()):
    seen = []

    def compose(output_dir, route, kind, shared_context=None):
        seen.append({"route": route, "kind": kind,
                     "context": bool(shared_context)})
        if route in raises_for:
            raise RuntimeError("server went away")
        return {"applied": route in applied_for, "route": route,
                "reason": "" if route in applied_for else "below the floor"}

    return compose, seen


def test_one_call_per_page_not_one_call_for_the_app():
    """Thirty-two pages will not fit one response, and a single call is
    all-or-nothing: per-subject tolerance is what let a run finish with 28 of
    32 pages instead of none."""
    compose, seen = _composer(applied_for={"/articles"})
    compose_ui_via_a2ui("/tmp/app", DOC, page_composer=compose)
    assert [s["route"] for s in seen] == [
        "/articles", "/articles/[id]", "/articles/new"]


def test_every_call_carries_the_page_set_so_pages_know_their_siblings():
    """Navigation presentation and density are properties of a set — a page
    composed alone rendered its heading twice and its action white on white."""
    compose, seen = _composer(applied_for=set())
    compose_ui_via_a2ui("/tmp/app", DOC, page_composer=compose)
    assert all(s["context"] for s in seen)

    ctx = shared_context(DOC)
    assert "/articles/[id]" in ctx          # the set
    assert "informationDensity" in ctx      # §37
    # `uiRegistry` used to ride along here — names for components that were
    # never code, authored by a node that no longer exists.
    assert "uiRegistry" not in ctx


def test_a_page_below_the_floor_costs_that_page_only():
    compose, _ = _composer(applied_for={"/articles"})
    out = compose_ui_via_a2ui("/tmp/app", DOC, page_composer=compose)
    assert out["composed"] == ["/articles"]
    assert set(out["declined"]) == {"/articles/[id]", "/articles/new"}


def test_a_composer_that_raises_does_not_take_the_other_pages():
    compose, seen = _composer(applied_for={"/articles/new"},
                              raises_for={"/articles"})
    out = compose_ui_via_a2ui("/tmp/app", DOC, page_composer=compose)
    assert len(seen) == 3, "composition stopped at the failure"
    assert out["composed"] == ["/articles/new"]
    assert "server went away" in out["declined"]["/articles"]


def test_composing_nothing_is_reported_not_raised():
    """Every route still has a deterministic composer behind it."""
    compose, _ = _composer(applied_for=set())
    out = compose_ui_via_a2ui("/tmp/app", DOC, page_composer=compose)
    assert out["applied"] is False
    assert out["pages"] == 3


def test_a_composer_predating_shared_context_still_composes():
    def old(output_dir, route, kind):
        return {"applied": True, "route": route}

    out = compose_ui_via_a2ui("/tmp/app", DOC, page_composer=old)
    assert len(out["composed"]) == 3


def test_the_page_set_carries_flow_not_just_names():
    """`/` came back with six nodes and no affordance leading anywhere: the
    context named four fields per page and the contract had learned three more,
    so the composer was told less than the Blueprint knew and composed the
    landing page as though it stood alone."""
    from services.a2ui_ui_composition import shared_context

    doc = {"pages": [
        {"id": "PAGE-001", "route": "/", "name": "Home", "entry": True,
         "navigatesTo": ["PAGE-002"]},
        {"id": "PAGE-002", "route": "/plants/new", "name": "Add",
         "presentation": "modal"},
    ]}
    ctx = shared_context(doc)
    assert '"entry": true' in ctx.lower().replace(" ", " ")
    assert "/plants/new" in ctx
    assert "modal" in ctx


def test_navigates_to_is_given_as_routes_not_page_ids():
    """A composer reasons about where a link goes, not about PAGE-002."""
    from services.a2ui_ui_composition import shared_context

    ctx = shared_context({"pages": [
        {"id": "PAGE-001", "route": "/", "navigatesTo": ["PAGE-002"]},
        {"id": "PAGE-002", "route": "/plants/[id]"},
    ]})
    assert "PAGE-002" not in ctx
    assert "/plants/[id]" in ctx

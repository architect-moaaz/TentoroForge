"""Composition is reachable from the ReAct loop, which is the path chat takes.

`compose_route` and `add_widgets` existed as functions and as verbs on
`SmithSession.run_iteration` — and the live chat turn goes through
`smith_architect_wire.run_iteration_via_architect`, which never builds a
SmithSession. It calls `agents.smith_agent.run_smith_agent`, whose dispatch is
by TOOL NAME against `READONLY_HANDLERS`. A verb nothing dispatches on is a
verb the user cannot reach.
"""
from __future__ import annotations

import services.smith_tools as smith_tools
from services.intent_classifier import TOOL_SUBSETS, TOOL_TAGS


def _entry(name):
    return next((t for t in smith_tools.TOOL_CATALOG if t["name"] == name), None)


def test_both_verbs_are_advertised_and_dispatchable():
    """Advertised without a handler is the `verify_app` failure — the model
    keeps calling a tool that does not exist, and it reads as stupidity."""
    for name in ("compose_route", "add_widgets"):
        assert _entry(name), f"{name} missing from TOOL_CATALOG"
        assert name in smith_tools.READONLY_HANDLERS, f"{name} has no handler"


def test_the_catalog_says_when_not_to_use_them():
    """A whole-screen recomposition offered for a one-label change would throw
    away a page the user liked."""
    assert "edit_page" in _entry("compose_route")["desc"]


def test_a_route_is_required_and_the_refusal_says_how_to_find_one():
    out = smith_tools.READONLY_HANDLERS["compose_route"]("/tmp/nowhere", {})
    assert out["applied"] is False
    assert "list_pages" in out["reason"]


def test_add_widgets_without_widgets_is_refused_not_silently_recomposed():
    """The widgets ARE the request. Composing without them would report success
    for a page that does not have them."""
    out = smith_tools.READONLY_HANDLERS["add_widgets"](
        "/tmp/nowhere", {"route": "/"})
    assert out["applied"] is False
    assert "widgets" in out["reason"]


def test_a_missing_blueprint_is_a_reason_not_a_crash(tmp_path):
    out = smith_tools.READONLY_HANDLERS["compose_route"](
        str(tmp_path), {"route": "/"})
    assert out["applied"] is False and out["edited_paths"] == []
    assert "Blueprint" in out["reason"]


def test_an_edit_ask_can_still_reach_them():
    """`intent_classifier` scopes the catalogue per intent. "the dashboard
    renders nothing" classifies as edit_page, and a screen with no layout has
    no element for `edit_page` to change."""
    for name in ("compose_route", "add_widgets"):
        assert name in TOOL_SUBSETS["edit_page"]
        assert name in TOOL_TAGS


def test_the_tool_and_the_session_share_one_implementation():
    """Two entry points loading the Blueprint and committing separately would
    be two answers to what composing a route means."""
    import inspect

    from services.smith_session import SmithSession

    src = inspect.getsource(SmithSession._compose)
    assert "from services.smith.compose import run as compose_run" in src
    # The docstring names `apply_change`; the CODE must not load a
    # Blueprint or commit one of its own.
    body = src[src.index("compose_run"):]
    assert "BlueprintService" not in body
    assert "apply_change(" not in body

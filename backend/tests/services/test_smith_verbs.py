"""A turn can ask for more than a rename.

`_UNDERSTAND_ASK_REQUIRED` demanded screen + element_label +
current_behavior + desired_behavior + target_file of every request — all five
the shape of a rename. "Build a dashboard at / with five widgets" could not be
expressed, so the model either failed validation or invented an
`element_label`, and the dispatcher then found nothing to rename and reported
that the current state already matched.
"""
from __future__ import annotations

import pytest

from services.smith.verbs import (REQUIRED_BY_VERB, is_known, missing_fields,
                                  verb_of)


def test_each_verb_asks_for_what_its_own_machinery_needs():
    assert REQUIRED_BY_VERB["compose_route"] == {"route"}
    assert REQUIRED_BY_VERB["add_widgets"] == {"route", "widgets"}
    assert REQUIRED_BY_VERB["rebuild"] == set()
    # A composition does not need a `current_behavior` for a page that does
    # not exist yet.
    assert "current_behavior" not in REQUIRED_BY_VERB["compose_route"]
    # And a rename keeps exactly what it always required.
    assert REQUIRED_BY_VERB["rename"] == {
        "screen", "element_label", "current_behavior", "desired_behavior",
        "target_file"}


def test_an_absent_verb_is_a_rename():
    """Every turn used to be one, so a caller that sets nothing behaves as it
    always did rather than falling into an unknown-verb branch."""
    assert verb_of({}) == "rename"
    assert verb_of({"verb": "  COMPOSE_ROUTE "}) == "compose_route"


def test_an_empty_widget_list_is_the_request_without_its_content():
    assert missing_fields({"verb": "add_widgets", "route": "/"}) == ["widgets"]
    assert missing_fields(
        {"verb": "add_widgets", "route": "/", "widgets": []}) == ["widgets"]
    assert missing_fields(
        {"verb": "add_widgets", "route": "/", "widgets": ["Quorum"]}) == []


def test_an_invented_verb_is_named_as_unknown():
    """An open verb string would let the model invent `refactor_everything`
    and fall through to the same silent no-op this replaces."""
    assert is_known({"verb": "compose_route"}) is True
    assert is_known({"verb": "refactor_everything"}) is False


def test_the_understanding_tool_accepts_a_composition():
    from services.smith_tools import _smith_understand_ask

    ok = _smith_understand_ask({"verb": "compose_route", "route": "/"})
    assert ok["recorded"] is True
    assert ok["understanding"]["verb"] == "compose_route"
    assert ok["understanding"]["route"] == "/"

    bad = _smith_understand_ask({"verb": "add_widgets", "route": "/"})
    assert bad["recorded"] is False
    assert "widgets" in bad["error"]


def test_the_catalogue_advertises_the_verbs_it_can_run():
    """A model coached to call a tool with no handler keeps trying, and every
    attempt reads to the user as stupidity."""
    from services.smith_tools import TOOL_CATALOG

    entry = next(t for t in TOOL_CATALOG if t["name"] == "understand_ask")
    for verb in REQUIRED_BY_VERB:
        assert verb in entry["desc"], verb

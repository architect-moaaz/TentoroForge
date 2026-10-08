"""The vocabulary must be able to say what the planner already says.

`page_planner.ENTITY_SLOTS` has always named the create slot's pattern `form`:

    ("list",   "entity_list",      "Every {name}, in one place."),
    ("detail", "record_workspace", "One {name}, with everything about it."),
    ("create", "form",             "Add a {name}."),

`form` was not in the contract's pattern enum. Structured output enforces
enums, so `page_design` could not choose it however clearly it understood the
page, and labelled every create and edit screen `record_workspace` — the
least-bad value it was offered. The composer was then handed the record job,
"This screen shows ONE record in detail", for a page whose purpose is to
collect one.

Two representations of one fact, and the consumer attached to the wrong one.
This holds them together: the deterministic planner's vocabulary and the
contract's enum are the same vocabulary.
"""
import json
import pathlib

import pytest

from services.blueprint.executors import DAG, writable_shapes
from services.blueprint.page_planner import SECTION_PLACEMENTS, SECTION_SHOWS
from services.page_kind_anatomy import _FAMILY

_CONTRACT = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"


def _pattern_enum() -> list[str]:
    c = json.loads(_CONTRACT.read_text())
    return c["properties"]["pages"]["items"]["properties"]["pattern"]["enum"]


def _section_enum(field: str) -> list[str]:
    """`PageSection.<field>`'s enum, wherever the emitter placed the section."""
    c = json.loads(_CONTRACT.read_text())
    return c["properties"]["pages"]["items"]["properties"]["sections"]["items"]["properties"][field]["enum"]


def test_the_planner_says_how_a_section_shows_in_the_contracts_words():
    """The planner now places records as sections of screens; the words it
    offers for how they show and where they sit are the contract's own, or a
    section it describes cannot be written down."""
    assert list(SECTION_SHOWS) == _section_enum("shows")
    assert list(SECTION_PLACEMENTS) == _section_enum("placement")


def test_the_enum_can_name_a_create_form():
    assert "form" in _pattern_enum()


def test_every_declared_pattern_still_has_a_family():
    """Adding a pattern without a family is how a page comes to be judged by a
    floor written for a different kind of screen."""
    # `auth` is deliberately unjudged — see test_every_pattern_is_judged_as_itself.
    missing = [p for p in _pattern_enum() if p not in _FAMILY and p != "auth"]
    assert missing == [], f"patterns with no family: {missing}"


def test_form_is_judged_as_a_form():
    assert _FAMILY["form"] == "form"


def test_the_page_authoring_agent_is_offered_the_form_pattern():
    """The constraint only exists if it reaches the agent: structured output
    enforces the enum, so a value absent here is a value it cannot pick."""
    agent = DAG["page_contracts"].agent
    shape = json.dumps(writable_shapes(agent))
    assert '"form"' in shape, (
        f"agent {agent!r} is not offered the form pattern, so it must keep "
        f"labelling create screens record_workspace"
    )

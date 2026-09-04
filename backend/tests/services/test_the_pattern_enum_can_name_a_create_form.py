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
from services.blueprint.page_planner import ENTITY_SLOTS
from services.page_kind_anatomy import _FAMILY

_CONTRACT = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"


def _pattern_enum() -> list[str]:
    c = json.loads(_CONTRACT.read_text())
    return c["properties"]["pages"]["items"]["properties"]["pattern"]["enum"]


@pytest.mark.parametrize("slot,pattern,_desc", ENTITY_SLOTS)
def test_every_planner_slot_pattern_is_a_legal_pattern(slot, pattern, _desc):
    """A pattern the planner emits and the contract rejects is a page that
    cannot be written down."""
    assert pattern in _pattern_enum(), (
        f"ENTITY_SLOTS names {pattern!r} for the {slot!r} slot, but the "
        f"contract's pattern enum does not accept it"
    )


def test_the_enum_can_name_a_create_form():
    assert "form" in _pattern_enum()


def test_every_declared_pattern_still_has_a_family():
    """Adding a pattern without a family is how a page comes to be judged by a
    floor written for a different kind of screen."""
    missing = [p for p in _pattern_enum() if p not in _FAMILY]
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

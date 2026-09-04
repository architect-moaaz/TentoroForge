"""A connected design is evidence by default, and the specification on request.

`page_slots` asks its question one entity at a time — list, detail, create per
entity — so pages come from the data model and not from the design. That is
right when a design is evidence (§48): one connected dashboard legitimately
implies a sign-in, the lists behind its numbers and the forms that create them,
and a real run turned one screen into thirteen pages.

It is wrong when somebody draws four screens and wants four screens. There was
no way to say that, and `page_slots` explains why pruning was not the answer:

    "What the user asked for is not a candidate for pruning. Deliberately not
     computed here. The obvious signals do not discriminate: every one of 21
     entities in a live run carried requirements, and 37 of 39 requirements
     cited `application.description` … Matching entity names against the
     description would discriminate, but only by string-matching a heuristic
     into a rule."

A frame list is not a heuristic. It is an enumeration somebody connected on
purpose, which is why `treatAs: "specification"` narrows the QUESTION rather
than filtering the answer — the slots become the frames, and nothing is
declined because nothing was inferred.

Per source, not per application: a project may connect a specification and a
reference and mean different things by them.
"""
import pytest

from services.blueprint.executors import build_prompt
from services.blueprint.page_planner import (
    frame_slots, page_slot_prompt, page_slots, specification_frames,
)

ENTITIES = {"data": {"entities": [{"id": "ENTITY-001", "name": "Item"},
                                  {"id": "ENTITY-002", "name": "Order"}]}}
FRAMES = [{"nodeId": "1:2", "name": "Dashboard"},
          {"nodeId": "1:9", "name": "Settings"}]


def _doc(treat_as=None, frames=FRAMES):
    source = {"id": "FIGMA-001", "frames": frames}
    if treat_as:
        source["treatAs"] = treat_as
    return {"application": {"name": "X", "description": "a stock dashboard"},
            "requirements": [], "pages": [], "modules": [], "roles": [],
            **ENTITIES, "designSources": [source]}


# --------------------------------------------------------------- the default

def test_a_design_is_evidence_unless_told_otherwise():
    """§48. The default must not change: a screen proves a capability is
    reachable and says nothing about who may use it."""
    assert specification_frames(_doc()) == []


def test_evidence_still_asks_every_entity_feature():
    """The thirteen-page outcome is correct for evidence and must survive.

    Stated as "every entity slot survives" rather than as an equal count: a
    reference now contributes its drawn screens as slots too, so the list is
    LONGER than the entity-only list. What must not change is that nothing was
    taken away — a reference does not narrow the page set, which is the whole
    distinction from a specification.
    """
    entity_only = page_slots({**ENTITIES})
    with_design = page_slots(_doc())

    assert len(with_design) > len(entity_only)
    for slot in entity_only:
        assert slot in with_design


# ------------------------------------------- a reference still drew its screens

def test_a_reference_contributes_its_frames_as_slots():
    """The gap this closes: under a reference the frames were absent from the
    slot list entirely, and `figmaFrame` was attached afterwards only if
    `page_contracts` noticed the correspondence while authoring thirty other
    pages. Nothing required it to notice, and a drawn screen quietly composed
    from components is indistinguishable from a page nobody drew."""
    from services.blueprint.page_planner import reference_frames

    assert {f["nodeId"] for f in reference_frames(_doc())} == {"1:2", "1:9"}
    drawn = [s for s in page_slots(_doc()) if s.get("figmaFrame")]
    assert {s["figmaFrame"] for s in drawn} == {"1:2", "1:9"}


def test_the_drawn_screens_lead_the_list():
    """They are the fixed points the rest is arranged around, so they are read
    before the features that must avoid colliding with them."""
    slots = page_slots(_doc())
    assert [bool(s.get("figmaFrame")) for s in slots[:2]] == [True, True]
    assert not any(s.get("figmaFrame") for s in slots[2:])


def test_a_reference_frame_that_is_not_a_screen_is_not_a_slot():
    """Same §49 reading as the specification path: a colour swatch is not a
    page, however the file is held."""
    frames = FRAMES + [{"nodeId": "1:30", "name": "Swatches",
                        "looksLikeScreen": False}]
    drawn = [s for s in page_slots(_doc(None, frames)) if s.get("figmaFrame")]
    assert len(drawn) == 2


def test_a_specification_does_not_also_get_reference_slots():
    """The two paths are exclusive: a specification REPLACES the question, so
    its frames must not arrive twice or drag entity features back in."""
    slots = page_slots(_doc("specification"))
    assert len(slots) == 2
    assert all(s.get("figmaFrame") for s in slots)


def test_the_reference_prompt_says_the_drawn_slots_keep_their_frame():
    text = page_slot_prompt(_doc())
    assert "SOME OF THESE SCREENS WERE DRAWN" in text
    assert "not declinable" in text
    # and that the rest is built around them, not instead of them
    assert "AROUND" in text
    # the collision the seeded slots create, answered in the question
    assert "second page at the same route" in text


def test_no_design_gets_no_preamble():
    """A brief-only application must read exactly as it did."""
    assert "WERE DRAWN" not in page_slot_prompt({**ENTITIES})


def test_the_page_contracts_prompt_requires_the_frame_on_those_slots():
    """The executor's reference branch used to ask it to MATCH frames against
    pages it invented. It now points at the slots, which are answered or
    visibly missing."""
    user = build_prompt(_doc(), "page_contracts")[1]
    assert "A DESIGN IS CONNECTED AS A REFERENCE" in user
    assert "must carry that `nodeId`" in user
    assert "never give one frame to two pages" in user


def test_no_design_at_all_is_unaffected():
    assert len(page_slots({**ENTITIES})) == 3      # home + two entities


# ---------------------------------------------------------- the specification

def test_a_specification_replaces_the_answer_space():
    slots = page_slots(_doc("specification"))
    assert len(slots) == 2
    assert {s["figmaFrame"] for s in slots} == {"1:2", "1:9"}


def test_every_slot_carries_the_frame_it_must_be_built_from():
    for slot in frame_slots(specification_frames(_doc("specification"))):
        assert slot["figmaFrame"] == slot["feature"]


def test_a_frame_that_is_not_a_screen_is_not_a_page():
    """`looksLikeScreen` is recorded rather than enforced at extraction (§49);
    a colour swatch is not a page even in a file that IS the specification."""
    frames = FRAMES + [{"nodeId": "1:30", "name": "Swatches",
                        "looksLikeScreen": False}]
    assert len(page_slots(_doc("specification", frames))) == 2


def test_a_frame_with_no_node_id_is_skipped():
    """It could not be built from, so offering it as a slot promises a screen
    that cannot exist."""
    frames = FRAMES + [{"name": "Nameless"}]
    assert len(page_slots(_doc("specification", frames))) == 2


def test_two_sources_can_mean_different_things():
    """Per source: a project may connect a specification and a reference."""
    doc = _doc("specification")
    doc["designSources"].append(
        {"id": "FIGMA-002", "frames": [{"nodeId": "9:1", "name": "Moodboard"}]})
    assert {f["nodeId"] for f in specification_frames(doc)} == {"1:2", "1:9"}


# --------------------------------------------------------------- the prompts

def test_the_specification_prompt_asks_for_one_page_per_frame():
    text = page_slot_prompt(_doc("specification")).lower()
    assert "one page per frame" in text
    # None of the entity-feature reasoning applies when nothing is declinable.
    assert "decline a feature" not in text


def test_the_evidence_prompt_is_unchanged():
    assert "decline a feature" in page_slot_prompt(_doc()).lower()


@pytest.mark.parametrize("treat_as,expected", [(None, False), ("specification", True)])
def test_figma_frame_is_required_only_under_a_specification(treat_as, expected):
    """Under evidence, omitting the frame is the good answer for a page the
    design does not show — the prompt says so. Under a specification there is
    no such page."""
    user = build_prompt(_doc(treat_as), "page_contracts")[1]
    assert ("EVERY page you author" in user) is expected


def test_the_specification_prompt_forbids_inventing_the_obvious():
    """A sign-in and a create form are reasonable, absent from the frames, and
    out of scope — the failure mode is inventing them helpfully."""
    user = build_prompt(_doc("specification"), "page_contracts")[1]
    assert "Do NOT add pages the design does not show" in user

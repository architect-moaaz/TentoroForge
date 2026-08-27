"""§8's Context Resolver — *"retrieve only context relevant to the current request."*

The failure this prevents is not "wrong answer", it is "right answer, every
turn, for 94k tokens". The ATS fixture is ~313 artifacts; a conversation that
hands all of them to every turn costs more than the work it is doing.

So these tests care about two things at once: that the slice is small, and that
it still contains what the request is actually about.
"""
import json

import pytest

from services.smith.context import DEFAULT_BUDGET, resolve, score_artifacts
from services.smith.conversation import Conversation


def _tokens(obj) -> int:
    return len(json.dumps(obj)) // 4


# --- the point of the exercise ----------------------------------------------

def test_a_slice_is_much_smaller_than_the_application(ats):
    sliced = _tokens(resolve(ats, "make the data table more compact").blueprint)
    assert sliced < _tokens(ats) / 2


def test_a_slice_still_contains_what_the_request_is_about(ats):
    ctx = resolve(ats, "the data table is too wide")
    assert "CMP-033" in ctx.artifacts


# --- matching ---------------------------------------------------------------

def test_camel_case_names_are_matched_by_ordinary_words(ats):
    """`DataTable` lowercases to one token. Without splitting on case, "data
    table" matches every rule mentioning data and misses the component the user
    is pointing at."""
    top = score_artifacts(ats, "the data table is too wide")[0]
    assert top.artifact_id == "CMP-033"


def test_identity_outranks_prose(ats):
    """A component *named* for the thing beats one that merely mentions it."""
    ranked = score_artifacts(ats, "data table")
    assert ranked[0].score > ranked[-1].score


def test_an_id_named_in_the_request_is_used_directly(ats):
    ctx = resolve(ats, "why does PAGE-014 exist?")
    assert "PAGE-014" in ctx.artifacts
    assert ctx.why["PAGE-014"] == "named in the request"


def test_stopwords_do_not_match_everything(ats):
    assert score_artifacts(ats, "the and of it") == []


def test_a_request_matching_nothing_is_reported_not_guessed(ats):
    """Not grounded is a reason to ask, not a reason to answer anyway."""
    ctx = resolve(ats, "flurblewhatsit please")
    assert not ctx.grounded and ctx.artifacts == []


# --- §69: anchors are certainty ---------------------------------------------

def test_anchors_bypass_matching_entirely(ats):
    """The preview already knew which component was clicked."""
    ctx = resolve(ats, "make this more compact", anchors=["CMP-033"])
    assert ctx.why["CMP-033"].startswith("anchor")


def test_an_anchor_is_never_dropped_by_the_budget(ats):
    """A resolver that budgets away the component the user literally clicked
    has failed at the one case where it had certainty."""
    ctx = resolve(ats, "candidate role offer interview stage",
                  anchors=["PAGE-018"], budget=1)
    assert "PAGE-018" in ctx.artifacts


def test_an_unknown_anchor_is_ignored_rather_than_faked(ats):
    ctx = resolve(ats, "x", anchors=["PAGE-999"])
    assert "PAGE-999" not in ctx.artifacts


# --- expansion --------------------------------------------------------------

def test_a_page_arrives_with_the_data_it_shows(ats):
    """A page shown without its entity reads as though it has none."""
    ctx = resolve(ats, "", anchors=["PAGE-009"])
    assert any(a.startswith("ENTITY-") for a in ctx.artifacts)


def test_entities_arrive_with_their_relationships(ats):
    ctx = resolve(ats, "", anchors=["ENTITY-003"])
    assert ctx.blueprint.get("data", {}).get("relationships")


def test_expansion_is_bounded(ats):
    """The full closure reaches a role, and a role reaches every permission;
    on this fixture that turns a 60-artifact slice into 152."""
    ctx = resolve(ats, "candidate offer interview role stage recruiter")
    assert len(ctx.artifacts) < DEFAULT_BUDGET * 3


def test_truncation_is_reported_rather_than_hidden(ats):
    ctx = resolve(ats, "candidate role offer interview stage recruiter", budget=3)
    assert ctx.truncated


def test_a_slice_keeps_the_sections_the_document_uses(ats):
    """It goes straight into a prompt as JSON; a reshaped slice would teach the
    model a schema the Blueprint does not have."""
    ctx = resolve(ats, "", anchors=["PAGE-009", "ENTITY-003"])
    assert "pages" in ctx.blueprint
    assert "entities" in ctx.blueprint.get("data", {})
    assert ctx.blueprint["application"] == ats["application"]


# --- the other layers -------------------------------------------------------

def test_the_slice_carries_the_immediate_conversation(ats, tmp_path):
    conv = Conversation(tmp_path)
    conv.append("user", "I need an ATS")
    ctx = resolve(ats, "and offers too", conversation=conv)
    assert ctx.conversation and ctx.conversation[0]["id"] == "MSG-001"


def test_the_slice_carries_binding_decisions(ats):
    assert resolve(ats, "anything").decisions


def test_the_slice_carries_known_implementation(ats):
    ctx = resolve(ats, "", anchors=["ENTITY-001"])
    assert ctx.code.get("ENTITY-001") == ["src/db/schema/user.ts"]


def test_resolution_is_reproducible(ats):
    a = resolve(ats, "make the data table compact")
    b = resolve(ats, "make the data table compact")
    assert a.artifacts == b.artifacts


def test_deprecated_artifacts_are_not_offered(ats):
    ats["pages"][0]["status"] = "DEPRECATED"
    target = ats["pages"][0]["id"]
    ctx = resolve(ats, ats["pages"][0]["name"])
    assert ctx.why.get(target) is None

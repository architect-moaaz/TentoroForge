"""The model seam — and the rule that a bad plan is re-asked, never repaired.

The old platform accumulated 151 post-generation repair passes, and every one
of them started as something reasonable: a model named an artifact that did not
quite exist, and mapping it to the nearest real one worked often enough that
nobody removed the mapping. Then it was load-bearing.

So the tests here are mostly about refusal. A plan naming ``PAGE-099`` is
thrown away whole. Nothing has been written when that happens, so re-asking is
free — and re-asking is the only correct move, because the alternative is
guessing at intent silently.
"""
import json

import pytest

from services.blueprint.agent_contract import ASK_USER
from services.smith.clarification import Question, select
from services.smith.context import resolve
from services.smith.turn import (
    INTENTS,
    TURN_SCHEMA,
    TurnRejected,
    build_interpret_prompt,
    interpret,
    parse_turn,
    phrase,
    validate_turn,
)


def plan_json(**over) -> str:
    body = {
        "intent": "change", "summary": "s", "reply": "r",
        "answers": [], "anchors": [], "proposals": [], "confidence": 0.9,
    }
    body.update(over)
    return json.dumps(body)


class FakeModel:
    """A model that returns canned replies and records what it was asked."""

    enforces_schema = True

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, *, system: str, user: str, schema=None) -> str:
        self.calls.append((system, user))
        return self.replies.pop(0) if self.replies else self.replies[-1]


# --- parsing ----------------------------------------------------------------

def test_a_non_json_reply_is_rejected():
    with pytest.raises(TurnRejected):
        parse_turn("I think you want a table.")


def test_an_unknown_intent_is_rejected():
    with pytest.raises(TurnRejected):
        parse_turn(plan_json(intent="refactor"))


def test_the_model_cannot_assign_ids(ats):
    """§12/§116 — identity belongs to the deterministic layer."""
    plan = parse_turn(plan_json(proposals=[{
        "section": "pages", "natural_key": "/x",
        "body": json.dumps({"id": "PAGE-042", "name": "X", "route": "/x"}),
    }]))
    assert "id" not in plan.proposals[0].body


def test_intents_stay_a_closed_set():
    """An intent set that grows a category per phrasing is a synonym table."""
    assert set(TURN_SCHEMA["properties"]["intent"]["enum"]) == set(INTENTS)


# --- validation: reject, never repair ---------------------------------------

def test_an_anchor_that_does_not_exist_is_rejected(ats):
    with pytest.raises(TurnRejected, match="do not exist"):
        validate_turn(parse_turn(plan_json(anchors=["PAGE-099"])), ats)


def test_an_unknown_anchor_is_not_quietly_dropped(ats):
    """Dropping it silently changes what the turn is about."""
    plan = parse_turn(plan_json(anchors=["PAGE-009", "PAGE-099"]))
    with pytest.raises(TurnRejected):
        validate_turn(plan, ats)
    assert plan.anchors == ["PAGE-009", "PAGE-099"]


def test_a_write_outside_smiths_boundary_is_rejected(ats):
    with pytest.raises(TurnRejected, match="outside Smith's boundary"):
        validate_turn(parse_turn(plan_json(proposals=[{
            "section": "apis", "natural_key": "GET /x", "body": "{}",
        }])), ats)


def test_derived_sections_are_outside_the_boundary(ats):
    """Endpoints, file paths and pattern templates are derived from what Smith
    writes. Authoring them is overwritten on the next derivation."""
    for section in ("apis", "codeMap", "patternTemplates", "runtime"):
        with pytest.raises(TurnRejected):
            validate_turn(parse_turn(plan_json(proposals=[{
                "section": section, "natural_key": "k", "body": "{}",
            }])), ats)


def test_a_proposal_without_a_natural_key_is_rejected(ats):
    with pytest.raises(TurnRejected, match="natural_key"):
        validate_turn(parse_turn(plan_json(proposals=[{
            "section": "pages", "natural_key": "", "body": "{}",
        }])), ats)


def test_an_answer_must_settle_something_that_was_asked(ats):
    """Otherwise a turn records a "user decision" about an artifact the user
    was never shown — the one thing §20's `source: user` must never mean."""
    asked = [Question("PAGE-001", "pages", "l", 0.5, "clarification", 1, 1.0, "w")]
    plan = parse_turn(plan_json(intent="answer", answers=[
        {"artifact": "PAGE-002", "decision": "d", "reason": "", "delegated": False},
    ]))
    with pytest.raises(TurnRejected, match="not among the questions asked"):
        validate_turn(plan, ats, asked=asked)


def test_an_answer_recording_no_decision_is_rejected(ats):
    asked = [Question("PAGE-001", "pages", "l", 0.5, "clarification", 1, 1.0, "w")]
    plan = parse_turn(plan_json(intent="answer", answers=[
        {"artifact": "PAGE-001", "decision": "  ", "reason": "", "delegated": False},
    ]))
    with pytest.raises(TurnRejected):
        validate_turn(plan, ats, asked=asked)


def test_confidence_outside_the_range_is_rejected_not_clamped(ats):
    """Clamping overrules the model's own report of how sure it is."""
    with pytest.raises(TurnRejected):
        validate_turn(parse_turn(plan_json(confidence=1.7)), ats)


def test_a_valid_plan_passes(ats):
    validate_turn(parse_turn(plan_json(anchors=["PAGE-009"])), ats)


# --- the retry --------------------------------------------------------------

def test_a_rejected_plan_is_re_asked_with_the_reason(ats):
    model = FakeModel(plan_json(anchors=["PAGE-099"]), plan_json(anchors=["PAGE-009"]))
    plan = interpret(model, resolve(ats, "x"), ats)
    assert plan.anchors == ["PAGE-009"]
    assert "was rejected" in model.calls[1][1]
    assert "PAGE-099" in model.calls[1][1]


def test_a_plan_that_never_validates_raises_rather_than_being_patched(ats):
    model = FakeModel(plan_json(anchors=["PAGE-099"]), plan_json(anchors=["PAGE-098"]))
    with pytest.raises(TurnRejected):
        interpret(model, resolve(ats, "x"), ats)


def test_the_retry_does_not_invite_invention(ats):
    model = FakeModel(plan_json(anchors=["PAGE-099"]), plan_json())
    interpret(model, resolve(ats, "x"), ats)
    assert "do not invent ids" in model.calls[1][1]


# --- §17 --------------------------------------------------------------------

def test_a_low_confidence_plan_is_not_actionable():
    assert not parse_turn(plan_json(confidence=ASK_USER - 0.01)).actionable
    assert parse_turn(plan_json(confidence=ASK_USER)).actionable


# --- the prompt -------------------------------------------------------------

def test_the_prompt_states_smiths_boundary(ats):
    system, _ = build_interpret_prompt(resolve(ats, "x"))
    assert "requirements" in system and "decisions" in system


def test_the_prompt_carries_decisions_the_user_already_made(ats):
    """§20 — future agents must respect accepted decisions."""
    ats["decisions"][0]["source"] = "user"
    system, _ = build_interpret_prompt(resolve(ats, "x"))
    assert ats["decisions"][0]["id"] in system


def test_the_prompt_admits_when_the_slice_is_incomplete(ats):
    _s, user = build_interpret_prompt(
        resolve(ats, "candidate role offer interview stage", budget=3)
    )
    assert "does not contain every artifact" in user


def test_the_prompt_says_when_nothing_matched(ats):
    _s, user = build_interpret_prompt(resolve(ats, "flurblewhatsit"))
    assert "ask what they mean" in user


# --- §16 wording ------------------------------------------------------------

def test_questions_are_joined_back_to_the_artifacts_they_settle(ats):
    batch = select(ats)
    model = FakeModel(json.dumps({
        "preamble": "I understand the pipeline.",
        "questions": [{"artifact": q.artifact, "question": f"Q about {q.label}?"}
                      for q in batch],
    }))
    worded = phrase(model, batch)
    assert worded.artifacts == [q.artifact for q in batch]
    assert "1." in worded.render()


def test_the_model_may_not_edit_the_selected_batch(ats):
    """The batch is chosen by materiality. A model quietly swapping a question
    overrules the ranking with an impression, which is §116 backwards."""
    batch = select(ats)
    model = FakeModel(json.dumps({
        "preamble": "p",
        "questions": [{"artifact": batch[0].artifact, "question": "only one"}],
    }))
    with pytest.raises(TurnRejected, match="not the model's to edit"):
        phrase(model, batch)


def test_an_empty_batch_asks_nothing(ats):
    assert phrase(FakeModel(), []).items == []

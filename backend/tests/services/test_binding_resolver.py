"""The resolver answers only what the binder could not, and only from the set.

Why these tests are shaped this way
-----------------------------------
This module exists because substring matching cannot read a label. That makes
it the one place in the binder chain where a model's judgement is load-bearing,
so every test here pins a way of NOT trusting it: the answer must name a
registered entity, must answer a question that was actually asked, and an
outage must cost nothing but quality.

The provider is injected. What needs pinning is the contract, not the transport.
"""

import json

from services.binding_resolver import build_prompt, resolve_entities

REG = {
    "entities": {
        "Session": {"slug": "sessions", "columns": [
            {"name": "id"}, {"name": "quorumMet"}, {"name": "scheduledAt"}]},
        "Bill": {"slug": "bills", "columns": [
            {"name": "id"}, {"name": "title"}, {"name": "status"}]},
    }
}

QUESTION = {
    "component": "quorumGauge", "prop": "value", "path": "/quorum/value",
    "label": "نسبة النصاب القانوني", "assumed": "Bill",
    "candidates": ["Bill", "Session"],
}


def _provider(payload):
    def call(prompt):
        return json.dumps(payload)
    return call


def test_an_answer_inside_the_candidate_set_is_taken():
    """The live failure: quorum belongs to Session, the binder guessed Bill."""
    out = resolve_entities([QUESTION], registry=REG, route="/dashboard",
                           provider=_provider({"quorumGauge": "Session"}))
    assert out == {"quorumGauge": "Session"}


def test_an_invented_entity_is_refused():
    """A name outside the closed set would become a dataSource nothing serves."""
    out = resolve_entities([QUESTION], registry=REG, route="/dashboard",
                           provider=_provider({"quorumGauge": "Quorum"}))
    assert out == {}


def test_an_answer_to_a_question_nobody_asked_is_ignored():
    out = resolve_entities([QUESTION], registry=REG, route="/dashboard",
                           provider=_provider({"someOtherNode": "Session"}))
    assert out == {}


def test_an_omitted_component_stays_unanswered():
    """Silence is a legitimate answer — it keeps the binder's own fallback,
    which is better than forcing a confident wrong pick."""
    out = resolve_entities([QUESTION], registry=REG, route="/dashboard",
                           provider=_provider({}))
    assert out == {}


def test_no_questions_means_no_call():
    """Pages that resolved on their own must not pay for a round trip."""
    calls = []

    def call(prompt):
        calls.append(prompt)
        return "{}"

    assert resolve_entities([], registry=REG, route="/x", provider=call) == {}
    assert calls == []


def test_a_provider_that_raises_never_fails_the_build():
    def boom(prompt):
        raise RuntimeError("resolver down")

    assert resolve_entities([QUESTION], registry=REG, route="/dashboard",
                            provider=boom) == {}


def test_prose_around_the_json_is_tolerated():
    def chatty(prompt):
        return ('Looking at the route, quorum is a session concept.\n'
                '```json\n{"quorumGauge": "Session"}\n```\nHope that helps.')

    out = resolve_entities([QUESTION], registry=REG, route="/dashboard",
                           provider=chatty)
    assert out == {"quorumGauge": "Session"}


def test_junk_output_yields_no_answers():
    out = resolve_entities([QUESTION], registry=REG, route="/dashboard",
                           provider=lambda p: "I'm not sure, sorry!")
    assert out == {}


def test_the_prompt_carries_what_the_decision_needs():
    p = build_prompt([QUESTION], registry=REG, route="/sessions/[id]",
                     kind="detail")
    assert "/sessions/[id]" in p
    assert "detail" in p
    assert "Session: id, quorumMet, scheduledAt" in p, "columns tell them apart"
    assert "نسبة النصاب القانوني" in p, "the label is the evidence"
    assert "quorumGauge" in p
    assert "OMIT" in p, "the prompt must license silence"


def test_the_question_count_is_bounded(monkeypatch):
    """A pathological surface must not become an unbounded prompt."""
    monkeypatch.setattr("services.binding_resolver.MAX_QUESTIONS", 2)
    seen = {}

    def call(prompt):
        seen["n"] = prompt.count("id=")
        return "{}"

    qs = [dict(QUESTION, component=f"c{i}") for i in range(9)]
    resolve_entities(qs, registry=REG, route="/x", provider=call)
    assert seen["n"] == 2

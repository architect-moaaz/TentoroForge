"""§16 — which five questions, out of fifty-four.

§16 caps the ask at "approximately 3–5 important decisions at a time" and §15
says which: those where "missing information materially affects the
application". These tests are about the word *important*. Anything can pick
five; the question is whether they are the five worth a user's attention, and
whether the same Blueprint picks the same five twice.
"""
import pytest

from services.blueprint.agent_contract import ASK_USER, RECORD_ASSUMPTION
from services.smith.clarification import (
    DEFAULT_BATCH,
    QUESTION_SECTIONS,
    already_asked,
    candidates,
    in_degree,
    select,
    summary,
)
from services.smith.conversation import Conversation


def test_only_artifacts_below_the_ask_line_are_candidates(ats):
    for q in candidates(ats):
        assert q.confidence < RECORD_ASSUMPTION


def test_requirements_are_askable_even_though_they_are_not_decisions(ats):
    """`decision_memory` excludes requirements, correctly, because §20 records
    decisions and a requirement is an input. For *questions* that exclusion is
    backwards: nine of eighteen requirements here sit below the ask line, and a
    misunderstood requirement is inherited by everything downstream."""
    from services.blueprint.decision_memory import unresolved_questions

    asked_about = {q.section for q in candidates(ats)}
    assert "requirements" in asked_about
    assert "requirements" not in {u["section"] for u in unresolved_questions(ats)}


def test_apis_are_never_asked_about(ats):
    """Endpoints are derived from entities, workflows and widgets. A
    low-confidence endpoint is a symptom; asking about it is asking about the
    shadow instead of the thing casting it."""
    assert "apis" not in QUESTION_SECTIONS
    assert not [q for q in candidates(ats) if q.section == "apis"]


def test_tests_are_never_asked_about(ats):
    assert not [q for q in candidates(ats) if q.section == "tests"]


# --- materiality ------------------------------------------------------------

def test_blocked_artifacts_outrank_merely_uncertain_ones(ats):
    """§17: below 0.40, do not implement the behaviour without clarification.
    That is a stronger claim than wanting confirmation, and it should sort
    like one."""
    ranked = candidates(ats)
    blocking = [i for i, q in enumerate(ranked) if q.confidence < ASK_USER]
    assert blocking and blocking[0] == 0


def test_a_widely_depended_on_artifact_outranks_an_isolated_one(ats):
    """Both at the same confidence; one has fifty dependents and one has none.
    Guessing about the first is a much more expensive mistake."""
    ats["businessRules"].append(
        {"id": "RULE-900", "name": "Lonely rule", "confidence": 0.6,
         "description": "Nothing references this.", "status": "PROPOSED"}
    )
    ranked = {q.artifact: i for i, q in enumerate(candidates(ats))}
    busy = max(
        (q for q in candidates(ats) if q.confidence == 0.6 and q.blast > 5),
        key=lambda q: q.blast,
    )
    assert ranked[busy.artifact] < ranked["RULE-900"]


def test_in_degree_counts_direct_references_only(ats):
    """Transitively almost everything reaches almost everything — module
    membership alone connects every page to every other — so a transitive count
    ranks nothing above anything."""
    degree = in_degree(ats)
    assert max(degree.values()) < len(ats["requirements"]) * 60


def test_a_thin_dimension_raises_its_artifacts(ats):
    """§15 — ask where missing information materially affects the app."""
    before = {q.artifact: q.score for q in candidates(ats)}
    ats["integrations"] = [
        i for i in ats["integrations"] if i["id"] != "INT-001"
    ]
    after = {q.artifact: q.score for q in candidates(ats)}
    common = [a for a in before if a in after and a.startswith("INT-")]
    assert common
    assert all(after[a] >= before[a] for a in common)


# --- §16's batch ------------------------------------------------------------

def test_a_batch_is_three_to_five(ats):
    assert 3 <= len(select(ats)) <= 5
    assert DEFAULT_BATCH == 5


def test_a_batch_does_not_ask_five_versions_of_one_question(ats):
    """Five questions about widgets are five ways of asking one thing. The
    user answers the first and is bored by the fifth."""
    batch = select(ats)
    assert len({q.section for q in batch}) >= 4


def test_the_single_most_material_question_is_still_first(ats):
    """Diversification spreads the batch; it must not displace the top."""
    assert select(ats)[0].artifact == candidates(ats)[0].artifact


def test_selection_is_reproducible(ats):
    assert [q.artifact for q in select(ats)] == [q.artifact for q in select(ats)]


def test_selection_is_stable_across_a_reserialised_document(ats):
    import json

    reordered = json.loads(json.dumps(ats))
    reordered["pages"] = list(reversed(reordered["pages"]))
    assert [q.artifact for q in select(ats)] == [q.artifact for q in select(reordered)]


# --- not re-asking ----------------------------------------------------------

def test_questions_just_asked_are_not_asked_again(ats, tmp_path):
    conv = Conversation(tmp_path)
    first = select(ats, conversation=conv)
    conv.append("smith", "…", refs=tuple(q.artifact for q in first))
    second = select(ats, conversation=conv)
    assert not ({q.artifact for q in first} & {q.artifact for q in second})


def test_what_was_asked_is_read_off_the_transcript_not_a_queue(ats, tmp_path):
    """There is no stored list of open questions anywhere in this package. An
    open question is a derived property of the Blueprint; a stored one would be
    a second source of truth to reconcile with the first."""
    conv = Conversation(tmp_path)
    conv.append("smith", "…", refs=("PAGE-001", "REQ-016"))
    assert already_asked(conv) == {"PAGE-001", "REQ-016"}


def test_a_question_stops_being_asked_once_it_is_answered(ats, tmp_path):
    """The mechanism is confidence, not bookkeeping — see test_smith_decisions."""
    from services.blueprint.service import BlueprintService
    from services.smith import decisions as decision_log
    from services.smith.smith import bootstrap

    svc = BlueprintService(output_dir=tmp_path)
    svc.doc = ats
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    bootstrap(svc)

    target = select(svc.doc)[0]
    decision_log.record(
        svc, artifact_id=target.artifact, decision="Settled.", message_id="MSG-001",
    )
    assert target.artifact not in {q.artifact for q in candidates(svc.doc)}


# --- reporting --------------------------------------------------------------

def test_summary_does_not_invent_weak_dimensions(ats):
    """All eleven dimensions score 1.0 on this fixture. Reporting the bottom
    three anyway names three "weakest" that are not weak."""
    assert summary(ats)["weakest"] == []


def test_summary_names_a_dimension_that_really_is_thin(ats):
    ats["integrations"] = []
    assert "integrations" in summary(ats)["weakest"]


def test_an_empty_blueprint_asks_nothing_rather_than_erroring():
    assert select({}) == []
    assert candidates({}) == []

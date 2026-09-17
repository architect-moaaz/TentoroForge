"""An agent that says the fault is upstream is acted on, not filed.

§30 gave every agent a way to say "the fault is in that section" and the run
collected those into the report, where a person might read them afterwards.
On a calculator whose requirements say nothing is stored, `entity_fields`
raised exactly the right one — recommend removing this entity — at confidence
0.35, and the observer agreed twice. The run then spent seven minutes
authoring that table's columns and produced an application that cannot work.
"""

from __future__ import annotations

import pytest

from services.blueprint.corrections import actionable, apply_corrections
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Calculator",
                                domain="tools")
    s.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "CalculatorSession", "table": "calculator_sessions",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]},
        {"id": "ENTITY-002", "name": "Note", "table": "notes",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}]}
    s.doc["workflows"] = [{"id": "FLOW-001", "name": "EnterDigit", "purpose": "x",
                           "trigger": {"kind": "manual"}, "launchedFrom": [],
                           "steps": [{"key": "s", "name": "S", "type": "trigger",
                                      "config": {"type": "manual"}, "next": []}]}]
    s.save()
    return s


def _ask(section="data.entities", retire="ENTITY-001",
         reason="REQ-003 says nothing is stored; this models screen state as a table"):
    return [{"section": section, "reason": reason, "retire": retire}]


def test_a_request_naming_what_should_not_exist_is_actionable(svc):
    acts = actionable(_ask(), svc.doc)
    assert [a["id"] for a in acts] == ["ENTITY-001"]
    assert acts[0]["name"] == "CalculatorSession" and "nothing is stored" in acts[0]["reason"]


def test_prose_alone_is_recorded_and_not_guessed_at(svc):
    """"This section is wrong" is not a decision the document can carry out."""
    assert actionable([{"section": "data.entities",
                        "reason": "something about this feels wrong"}], svc.doc) == []
    assert actionable([{"section": "data.entities", "reason": "x",
                        "retire": "ENTITY-404"}], svc.doc) == []
    assert actionable([{"section": "designSystem", "reason": "x",
                        "retire": "ENTITY-001"}], svc.doc) == []
    assert actionable([], svc.doc) == [] and actionable(None, svc.doc) == []


def test_the_artifact_is_retired_and_the_history_says_who_asked(svc):
    done = apply_corrections(svc, _ask(), asked_by="entity_fields")
    assert done == ["ENTITY-001"]

    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    gone = next(e for e in fresh.doc["data"]["entities"] if e["id"] == "ENTITY-001")
    assert gone["status"] == "DEPRECATED"
    # RETIRED, NOT DELETED: §92 keeps it and its history.
    assert gone["name"] == "CalculatorSession"
    assert len(fresh.doc["data"]["entities"]) == 2
    last = fresh.doc["changeHistory"][-1]
    assert last["userRequest"] == "retire ENTITY-001"
    assert "entity_fields" in last["smithInterpretation"]
    assert "nothing is stored" in last["smithInterpretation"]


def test_asking_twice_changes_nothing_the_second_time(svc):
    assert apply_corrections(svc, _ask(), asked_by="entity_fields") == ["ENTITY-001"]
    versions = len(svc.doc["changeHistory"])
    assert apply_corrections(svc, _ask(), asked_by="entity_fields") == []
    assert len(svc.doc["changeHistory"]) == versions


def test_a_process_can_be_retired_the_same_way(svc):
    assert apply_corrections(svc, _ask(section="workflows", retire="FLOW-001",
                                       reason="nothing triggers it"),
                             asked_by="workflow_steps") == ["FLOW-001"]
    assert svc.doc["workflows"][0]["status"] == "DEPRECATED"


def test_the_run_acts_on_it_and_records_that_it_did(svc, monkeypatch):
    """The wiring: a node whose result carries the request has it carried out
    while the run is still going, so every stage after it sees it gone."""
    from services.blueprint import orchestrator

    report = orchestrator.RunReport()
    orchestrator._act_on(svc, "entity_fields", _ask(), report, commit=True)
    assert report.corrections == [{"node": "entity_fields", "retired": "ENTITY-001"}]
    assert svc.doc["data"]["entities"][0]["status"] == "DEPRECATED"


def test_a_dry_run_reports_without_changing_anything(svc):
    from services.blueprint import orchestrator

    report = orchestrator.RunReport()
    orchestrator._act_on(svc, "entity_fields", _ask(), report, commit=False)
    assert report.corrections == []
    assert "status" not in svc.doc["data"]["entities"][0]


# ------------------------------------------------ the retry that follows it

def _outcome(change_requests, *, confidence=0.35):
    """An agent result shaped the way `_apply_subject` reads one."""
    from services.blueprint.agent_contract import AgentResult

    return AgentResult(task_id="t", agent="data_model", status="completed",
                       proposals=[], change_requests=list(change_requests),
                       confidence=confidence)


def _apply(svc, outcome, subject="ENTITY-001", attempt=1, max_attempts=3):
    from services.blueprint.orchestrator import (
        RunReport, _apply_subject, _NodeRun,
    )

    report = RunReport()
    state = _NodeRun(subjects=[subject], pending=[subject])
    verdict = _apply_subject(
        svc, "entity_fields", state, subject, outcome,
        attempt=attempt, max_attempts=max_attempts, commit=True,
        user_request="", report=report,
    )
    return verdict, report, state


def test_a_subject_the_run_just_retired_is_not_asked_about_again(svc):
    """227 seconds to conclude the table should not exist, the entity retired
    on that conclusion, and the same agent immediately asked to author its
    columns — a worse answer in 57 seconds, then two observer repair rounds on
    a table the run had already agreed to remove."""
    verdict, report, _state = _apply(svc, _outcome(_ask()))
    assert verdict == "applied"
    assert [c["retired"] for c in report.corrections] == ["ENTITY-001"]

    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    gone = next(e for e in fresh.doc["data"]["entities"] if e["id"] == "ENTITY-001")
    assert gone["status"] == "DEPRECATED"


def test_objecting_to_somebody_elses_artifact_still_leaves_work_to_do(svc):
    """A subject that survives its own objection is still unwritten."""
    verdict, report, _state = _apply(
        svc, _outcome(_ask(retire="ENTITY-002")), subject="ENTITY-001")
    assert verdict == "retry"
    assert [c["retired"] for c in report.corrections] == ["ENTITY-002"]


def test_a_question_that_names_nothing_is_still_a_question(svc):
    """The retry exists for a real case: `data_model` is bimodal, and a stub
    asks to be re-run in its own change_requests. That names no artifact, so
    nothing is retired and the retry is still the right answer."""
    verdict, report, _state = _apply(
        svc, _outcome([{"section": "data.entities",
                        "reason": "Re-run this stage with a clean emission"}]))
    assert verdict == "retry"
    assert report.corrections == []


# ----------------------------------- an empty data model is an answer, not a stall

def _envelope(**over):
    import json
    body = {"entities": [], "confidence": 0.9, "issues": [], "change_requests": [],
            "assumptions": ["REQ-001 says nothing is stored; a calculator keeps "
                            "its display on the screen"]}
    body.update(over)
    return json.dumps(body)


def test_an_application_that_stores_nothing_may_say_so():
    """MEASURED, ON A LIVE RUN. `data_model` is told in its own task text that
    some applications store nothing and that the answer is then `entities: []`
    with the reason in `assumptions`. It did exactly that, three attempts in a
    row, and the envelope check refused all three as malformed — so the node
    retried until it invented a table. The instruction and the validator were
    describing different contracts."""
    from services.blueprint.executors import parse_envelope

    out = parse_envelope(_envelope(), task_id="t", agent="data_model",
                         node="data_model")
    assert out.proposals == []
    assert out.assumptions


def test_a_reply_that_named_nothing_and_said_nothing_is_still_malformed():
    """The check exists for a real failure: a reply that parsed and stalled.
    A stall carries no `entities` key and no reasoning; the instructed answer
    carries both, because the instruction asks for both."""
    from services.blueprint.executors import MalformedEnvelope, parse_envelope

    for body in (_envelope(assumptions=[]), _envelope(entities=None)):
        with pytest.raises(MalformedEnvelope):
            parse_envelope(body, task_id="t", agent="data_model",
                           node="data_model")


def test_a_field_author_cannot_answer_with_nothing():
    """`entity_fields` is handed ONE entity and asked for its columns. "This
    entity has no fields" is not an answer it can mean — an entity that should
    not exist is a change_request, which is the path above."""
    from services.blueprint.executors import MalformedEnvelope, parse_envelope

    with pytest.raises(MalformedEnvelope):
        parse_envelope(_envelope(), task_id="t", agent="data_model",
                       node="entity_fields")

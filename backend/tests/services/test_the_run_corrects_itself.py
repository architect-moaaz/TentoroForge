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

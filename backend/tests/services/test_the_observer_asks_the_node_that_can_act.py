"""A finding goes to the node that can act on it, or it is reported, not repaired.

MEASURED ON UAT. LabConnect's field author took 34 minutes and 18 repair
rounds across 23 entities. Among the findings still open when the rounds ran
out:

    ENTITY-001  REQ-004: No Patient entity is defined to hold profile fields

The critic was judging ENTITY-001 and reported that a DIFFERENT entity is
missing. It is told to leave `artifact` empty when the thing does not exist
yet, and it did. The observer then filled that blank with the subject being
judged — so the finding was filed against ENTITY-001 and sent to the field
author, who writes the columns of the entity it is handed and has no way to
create another. Every round re-asked it for something outside its reach.
"""
import json

import pytest

from services.blueprint.observer import CRITIC_EDGE, Observer
from services.blueprint.orchestrator import run
from services.blueprint.service import BlueprintService
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.run_ledger import read, runs


class _Critic:
    def __init__(self, findings):
        self.findings = findings
        self.calls = []
        self.enforces_schema = True

    def __call__(self, *, system, user, schema):
        self.calls.append(json.loads(user))
        return json.dumps({"verdict": "fail" if self.findings else "pass",
                           "findings": self.findings})


def _missing_patient(artifact=""):
    return {"section": "data.entities", "artifact": artifact,
            "requirement": "REQ-004",
            "detail": "No Patient entity is defined to hold profile fields"}


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="lab",
                                name="LabConnect", domain="health")
    # Declared and not yet detailed — which is what makes them subjects of
    # `entity_fields`; an entity that already has fields counts as done.
    s.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "User", "table": "users"},
        {"id": "ENTITY-002", "name": "Booking", "table": "bookings"}]}
    s.save()
    return s


def _observe(svc, critic, subjects=("ENTITY-001", "ENTITY-002")):
    return Observer(critic=critic).observe(
        "entity_fields", agent="data_model", subjects=list(subjects),
        doc=svc.doc, pending=set(), planned={"data.entities"})


def _with_fields(svc):
    for e in svc.doc["data"]["entities"]:
        e["fields"] = [{"name": "id", "type": "uuid", "primaryKey": True}]


def test_a_missing_entity_is_not_a_repair_of_an_existing_one(svc):
    _with_fields(svc)
    obs = _observe(svc, _Critic([_missing_patient()]))
    assert not any(obs.findings.values())
    # Judged once per subject, so both entities report it; the run dedupes.
    assert {f.detail for f in obs.deferred if f.edge == CRITIC_EDGE} == {
        "REQ-004: No Patient entity is defined to hold profile fields"}
    assert Observer().repairs(obs) == []


def test_a_finding_about_the_subject_itself_is_still_repaired(svc):
    _with_fields(svc)
    finding = {"section": "data.entities", "artifact": "ENTITY-001",
               "requirement": "REQ-002",
               "detail": "User has no email column"}
    obs = _observe(svc, _Critic([finding]))
    assert list(obs.findings) == ["ENTITY-001"]
    assert [t.subject for t in Observer().repairs(obs)] == ["ENTITY-001"]


def test_a_node_that_owns_the_whole_section_still_hears_it(svc):
    """The data model is ONE subject over every entity. It can create the
    missing Patient, so the finding is its to repair."""
    obs = Observer(critic=_Critic([_missing_patient()])).observe(
        "data_model", agent="data_model", subjects=[""], doc=svc.doc,
        pending=set(), planned={"data.entities"})
    assert len(obs.findings.get("", [])) == 1
    assert [t.subject for t in Observer().repairs(obs)] == [""]


def _field_author(svc):
    def author(spec):
        entity = next(e for e in svc.doc["data"]["entities"] if e["id"] == spec.subject)
        body = {**entity, "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}
        body.pop("id", None)
        return AgentResult(
            task_id=spec.task_id, agent=spec.agent, confidence=0.9,
            proposals=[ArtifactProposal(section="data.entities",
                                        natural_key=entity["name"], body=body)])
    return author


def test_the_field_author_is_not_sent_to_the_observer(svc):
    """25 sent back across 71 observed runs, 4 passed; the rest were flagged
    and stayed wrong. Its repair rounds are zero, so the critic is not asked."""
    critic = _Critic([{"section": "data.entities", "artifact": "ENTITY-001",
                       "requirement": "REQ-002", "detail": "User has no email column"}])
    report = run(svc, _field_author(svc), plan=["entity_fields"],
                 observer_agent=Observer(critic=critic, rounds=2))
    assert critic.calls == []
    events = [l["event"] for l in read(svc.output_dir, runs(svc.output_dir)[0])]
    assert not any(e.startswith("observer:") for e in events)
    assert "entity_fields" in report.completed
    assert "entity_fields" not in report.observed


def test_a_deferred_finding_reaches_the_report_instead_of_disappearing(svc, monkeypatch):
    """Deferred findings used to be counted and dropped. The ones the critic
    raised are the useful kind, so they travel as change requests.

    The field author is not observed in a real run; the routing is the same for
    any watched fan-out, so the test watches it here to exercise it."""
    from services.blueprint import orchestrator
    monkeypatch.delitem(orchestrator.OBSERVER_ROUNDS_BY_NODE, "entity_fields")

    critic = _Critic([_missing_patient()])
    report = run(svc, _field_author(svc), plan=["entity_fields"],
                 observer_agent=Observer(critic=critic, rounds=2))
    asked = [c for c in report.change_requests
             if isinstance(c, dict) and c.get("raisedBy") == "observer:entity_fields"]
    assert [c["reason"] for c in asked] == [
        "REQ-004: No Patient entity is defined to hold profile fields"]
    events = [l["event"] for l in read(svc.output_dir, runs(svc.output_dir)[0])]
    assert "observer:repair" not in events
    assert "observer:deferred" in events


def test_the_requirements_author_is_not_sent_to_the_observer(tmp_path):
    """Its repair rounds are zero (2026-09-17): the critic is not asked."""
    s = BlueprintService.create(output_dir=tmp_path, app_id="req",
                                name="Notes", domain="notes")

    def author(spec):
        return AgentResult(
            task_id=spec.task_id, agent=spec.agent, confidence=0.9,
            proposals=[ArtifactProposal(section="requirements",
                                        natural_key="members-list-their-notes",
                                        body={"description": "Members list their notes"})])
    critic = _Critic([{"section": "requirements", "artifact": "", "requirement": "",
                       "detail": "Nothing says who may delete a note"}])
    report = run(s, author, plan=["requirements"],
                 observer_agent=Observer(critic=critic, rounds=2))
    assert critic.calls == []
    events = [l["event"] for l in read(s.output_dir, runs(s.output_dir)[0])]
    assert not any(e.startswith("observer:") for e in events)
    assert "requirements" in report.completed


@pytest.mark.parametrize("node", ["page_layouts", "entity_fields", "requirements",
                                  "database", "integrations"])
def test_the_nodes_taken_off_the_observer_have_no_repair_rounds(node):
    """Zero rounds is what keeps a node away from the critic entirely
    (`finish` skips `observe`); the runs above show it for three of them."""
    from services.blueprint.orchestrator import OBSERVER_ROUNDS_BY_NODE
    assert OBSERVER_ROUNDS_BY_NODE[node] == 0

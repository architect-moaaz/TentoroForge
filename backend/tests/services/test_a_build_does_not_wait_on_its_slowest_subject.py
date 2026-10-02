"""A build does not wait on its slowest subject, or its slowest repair.

HippieKit's measured rebuild (2026-09-21) was 2,790s, and 1,742s of it was
two fan-out nodes, `page_details` and `workflow_steps`. Three things made them
long, and none of them was work that had to be done in that order:

* every subject was judged when the LAST one landed — features written at
  606s waited for one written at 1,417s, and every verdict came at 1,538s;
* one feature (Product) owned eight pages in one call while most owned one to
  three, so it was that last one;
* a repair — a targeted fix against named findings — thought as hard as a
  first draft: one workflow repair took 280s and the node waited on it.
"""
import json
import threading
import time

import pytest

from services.blueprint import orchestrator
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.executors import AnthropicModel, for_repair
from services.blueprint.observer import Observer, _rows
from services.blueprint.orchestrator import (
    PAGES_PER_SUBJECT, TaskSpec, feature_pages, page_features, page_subject_of, run,
)
from services.blueprint.run_ledger import read, runs
from services.blueprint.service import BlueprintService

ENTITIES = ("ENTITY-001", "ENTITY-002", "ENTITY-003")


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.delitem(orchestrator.OBSERVER_ROUNDS_BY_NODE, "entity_fields", raising=False)
    s = BlueprintService.create(output_dir=tmp_path, app_id="lab", name="Lab", domain="health")
    s.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "User", "table": "users"},
        {"id": "ENTITY-002", "name": "Booking", "table": "bookings"},
        {"id": "ENTITY-003", "name": "Sample", "table": "samples"}]}
    s.save()
    return s


class _Critic:
    """Per subject: fail until `passes_after` checks; the coverage pass
    (subject "") answers `domain`. Records when each check was asked."""

    def __init__(self, *, passes_after=None, domain=(), domain_delay=0.0):
        self.passes_after = passes_after or {}
        self.domain = list(domain)
        self.domain_delay = domain_delay
        self.enforces_schema = True
        self.asked: list[tuple[str, float]] = []
        self.domain_done: float | None = None
        self._n: dict[str, int] = {}
        self._lock = threading.Lock()

    def __call__(self, *, system, user, schema):
        subject = json.loads(user)["subject"]
        with self._lock:
            n = self._n[subject] = self._n.get(subject, 0) + 1
            self.asked.append((subject, time.monotonic()))
        if not subject:
            time.sleep(self.domain_delay)
            self.domain_done = time.monotonic()
            return json.dumps({"verdict": "fail" if self.domain else "pass",
                               "findings": self.domain})
        if n > self.passes_after.get(subject, 10**6):
            return json.dumps({"verdict": "pass", "findings": []})
        return json.dumps({"verdict": "fail", "findings": [{
            "section": "data.entities", "artifact": subject, "requirement": "REQ-001",
            "detail": f"{subject} has no created-at column (check {n})"}]})


def _author(svc, *, delay=lambda spec: 0.0, landed=None, specs=None):
    def author(spec):
        if specs is not None:
            specs.append(spec)
        if spec.node == "security":
            return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9)
        time.sleep(delay(spec))
        entity = next(e for e in svc.doc["data"]["entities"] if e["id"] == spec.subject)
        body = {k: v for k, v in entity.items() if k not in ("id", "fields")}
        body["fields"] = [{"name": "id", "type": "uuid", "primaryKey": True}]
        if landed is not None:
            landed.append((spec.subject, spec.repair, time.monotonic()))
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal(section="data.entities",
                                                       natural_key=entity["name"], body=body)])
    return author


def _events(svc):
    return read(svc.output_dir, runs(svc.output_dir)[0])


# --- 1. a subject is judged when IT lands ------------------------------------

def test_a_subject_is_judged_and_repaired_before_a_slow_sibling_lands(svc):
    landed: list = []
    author = _author(svc, landed=landed,
                     delay=lambda spec: 0.8 if spec.subject == "ENTITY-003" and not spec.repair else 0.0)
    critic = _Critic(passes_after={"ENTITY-001": 1, "ENTITY-002": 0, "ENTITY-003": 0})
    report = run(svc, author, plan=["entity_fields"],
                 observer_agent=Observer(critic=critic, rounds=2))

    slow = next(t for s, r, t in landed if s == "ENTITY-003" and not r)
    first_check = next(t for s, t in critic.asked if s == "ENTITY-001")
    repaired = next(t for s, r, t in landed if s == "ENTITY-001" and r)
    assert first_check < slow, "ENTITY-001 was judged only after ENTITY-003 landed"
    assert repaired < slow, "ENTITY-001's repair waited for ENTITY-003"
    assert report.repaired == ["entity_fields:ENTITY-001"]
    assert "entity_fields" in report.completed


def test_the_coverage_pass_runs_once_after_every_subject_has_landed(svc):
    landed: list = []
    author = _author(svc, landed=landed,
                     delay=lambda spec: 0.3 if spec.subject == "ENTITY-002" else 0.0)
    critic = _Critic(passes_after={s: 0 for s in ENTITIES})
    run(svc, author, plan=["entity_fields"], observer_agent=Observer(critic=critic))
    domain = [t for s, t in critic.asked if s == ""]
    assert len(domain) == 1
    assert domain[0] > max(t for _, _, t in landed)


def test_the_node_is_not_done_until_its_sweep_is(svc):
    """Every subject passed on its own; the node still waits for the pass that
    needs them all, and its dependent starts after it."""
    started: list = []

    def author(spec):
        if spec.node == "security":
            started.append(time.monotonic())
        return _author(svc)(spec)

    critic = _Critic(passes_after={s: 0 for s in ENTITIES}, domain_delay=0.4)
    run(svc, author, plan=["entity_fields", "security"], observer_agent=Observer(critic=critic))
    assert critic.domain_done is not None and started and started[0] > critic.domain_done


def test_a_sweep_finding_sends_back_a_subject_that_had_passed(svc):
    critic = _Critic(passes_after={"ENTITY-001": 0, "ENTITY-002": 0, "ENTITY-003": 0},
                     domain=[{"section": "data.entities", "artifact": "ENTITY-002",
                              "requirement": "REQ-004", "detail": "no booking reference"}])
    specs: list = []
    report = run(svc, _author(svc, specs=specs), plan=["entity_fields"],
                 observer_agent=Observer(critic=critic, rounds=2))
    repairs = [s.subject for s in specs if s.repair]
    assert repairs == ["ENTITY-002"]
    assert "no booking reference" in next(s.feedback for s in specs if s.repair)
    assert report.repaired == ["entity_fields:ENTITY-002"]


def test_a_sweep_that_says_nothing_about_a_subject_does_not_pass_it(svc):
    """ENTITY-001 is still wrong after its only repair; the coverage pass said
    nothing about it. Silence is not a verdict: it is flagged."""
    critic = _Critic(passes_after={"ENTITY-002": 0, "ENTITY-003": 0})
    report = run(svc, _author(svc), plan=["entity_fields"],
                 observer_agent=Observer(critic=critic, rounds=1))
    assert "entity_fields:ENTITY-001" not in report.repaired
    assert list(report.unrepaired) == ["entity_fields:ENTITY-001"]


# --- 2. no page_details subject carries more than three pages ----------------

def _pages(n, entity="ENTITY-003", start=1):
    return [{"id": f"PAGE-{i:03d}", "route": f"/p{i}", "name": f"P{i}",
             "data": {"primaryEntity": entity}} for i in range(start, start + n)]


def test_a_large_feature_is_written_in_parts():
    doc = {"pages": _pages(8) + _pages(2, entity="ENTITY-001", start=20)
           + [{"id": "PAGE-030", "route": "/login", "pattern": "auth", "data": {"primaryEntity": "ENTITY-001"}}]}
    assert PAGES_PER_SUBJECT == 3
    assert page_features(doc) == ["ENTITY-003~1", "ENTITY-003~2", "ENTITY-003~3", "ENTITY-001"]
    assert [len(feature_pages(doc, s)) for s in page_features(doc)] == [3, 3, 2, 2]
    assert page_subject_of(doc)["PAGE-008"] == "ENTITY-003~3"
    assert page_subject_of(doc)["PAGE-021"] == "ENTITY-001"
    # Four pages go two and two, not three and one.
    assert [len(feature_pages({"pages": _pages(4)}, s)) for s in page_features({"pages": _pages(4)})] == [2, 2]


def test_a_part_is_judged_on_its_own_pages():
    doc = {"pages": _pages(8)}
    assert [r["id"] for r in _rows(doc, "pages", "ENTITY-003~2")] == ["PAGE-004", "PAGE-005", "PAGE-006"]


# --- 3. a repair thinks one notch less than a first draft --------------------

def test_a_repair_runs_one_effort_notch_lower():
    client = AnthropicModel(effort="high")
    repair = TaskSpec(task_id="T", node="workflow_steps", agent="workflow", repair=True,
                      feedback="findings", current=({"x": 1},))
    retry = TaskSpec(task_id="T", node="workflow_steps", agent="workflow", feedback="rejected")
    assert for_repair(client, repair).effort == "medium"
    assert for_repair(AnthropicModel(effort="medium"), repair).effort == "low"
    assert for_repair(AnthropicModel(effort="low"), repair).effort == "low"
    assert for_repair(client, retry) is client, "a retry was never accepted; it keeps the node's effort"


def test_the_scheduler_marks_what_it_sends_back_as_a_repair(svc):
    specs: list = []
    critic = _Critic(passes_after={"ENTITY-001": 1, "ENTITY-002": 0, "ENTITY-003": 0})
    run(svc, _author(svc, specs=specs), plan=["entity_fields"],
        observer_agent=Observer(critic=critic, rounds=2))
    assert [(s.subject, s.repair) for s in specs if s.subject == "ENTITY-001"] == \
        [("ENTITY-001", False), ("ENTITY-001", True)]

"""The observer's round trips cost calls, not queueing.

Measured over 71 observed runs, the eight nodes still watched made 334 critic
calls and 161 repair calls, and the time went on waiting as much as on calls:

* a fan-out node's subjects were judged one after another — `workflow_steps`
  took a median 60s to be judged on two workflows, `page_details` up to 380s;
* a repair round waited for its slowest repair before judging any of them;
* the check after a subject's last repair held the node, although its verdict
  could only become a flag.

The fan-out node here is `entity_fields`, whose own rounds are zero in a real
run; each test gives it rounds back so the loop has something to exercise.
"""
import json
import threading
import time

import pytest

from services.blueprint import orchestrator
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.observer import Observer
from services.blueprint.orchestrator import run
from services.blueprint.run_ledger import read, runs
from services.blueprint.service import BlueprintService

ENTITIES = ("ENTITY-001", "ENTITY-002", "ENTITY-003")


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.delitem(orchestrator.OBSERVER_ROUNDS_BY_NODE, "entity_fields")
    s = BlueprintService.create(output_dir=tmp_path, app_id="lab",
                                name="LabConnect", domain="health")
    s.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "User", "table": "users"},
        {"id": "ENTITY-002", "name": "Booking", "table": "bookings"},
        {"id": "ENTITY-003", "name": "Sample", "table": "samples"}]}
    s.save()
    return s


class _Critic:
    """Fails a subject until `passes_after` of its checks have been made;
    `delay(subject, n)` says how long its n-th check (1-based) takes."""

    def __init__(self, *, passes_after=None, delay=lambda subject, n: 0.0,
                 raises_for=()):
        self.passes_after = passes_after or {}
        self.delay = delay
        self.raises_for = set(raises_for)
        self.enforces_schema = True
        self.asked: list[tuple[str, float]] = []
        self._n: dict[str, int] = {}
        self._lock = threading.Lock()

    def __call__(self, *, system, user, schema):
        subject = json.loads(user)["subject"]
        with self._lock:
            n = self._n[subject] = self._n.get(subject, 0) + 1
            self.asked.append((subject, time.monotonic()))
        time.sleep(self.delay(subject, n))
        if subject in self.raises_for:
            raise RuntimeError("overloaded")
        if n > self.passes_after.get(subject, 10**6):
            return json.dumps({"verdict": "pass", "findings": []})
        return json.dumps({"verdict": "fail", "findings": [{
            "section": "data.entities", "artifact": subject, "requirement": "REQ-001",
            # Worded by check, so a later round is not the same finding again
            # (which the early stop would rightly flag at once).
            "detail": f"{subject} has no created-at column (check {n})"}]})


def _repair(spec) -> bool:
    return "-observer" in spec.task_id


def _author(svc, *, delay=lambda spec: 0.0, returned=None):
    def author(spec):
        time.sleep(delay(spec))
        entity = next(e for e in svc.doc["data"]["entities"] if e["id"] == spec.subject)
        body = {k: v for k, v in entity.items() if k not in ("id", "fields")}
        body["fields"] = [{"name": "id", "type": "uuid", "primaryKey": True}]
        if returned is not None:
            returned.append((spec.subject, _repair(spec), time.monotonic()))
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal(section="data.entities",
                                                       natural_key=entity["name"], body=body)])
    return author


def _events(svc):
    return read(svc.output_dir, runs(svc.output_dir)[0])


# --- 1. a fan-out's subjects are judged together ------------------------------

def test_the_subjects_of_one_node_are_judged_side_by_side(svc):
    critic = _Critic(delay=lambda s, n: 0.3)
    t0 = time.monotonic()
    obs = Observer(critic=critic).observe(
        "entity_fields", agent="data_model", subjects=list(ENTITIES),
        doc=svc.doc, pending=set(), planned={"data.entities"})
    elapsed = time.monotonic() - t0
    assert elapsed < 0.6, f"three 0.3s checks took {elapsed:.2f}s — one after another"
    # Filed exactly as a one-at-a-time pass would have filed them.
    assert list(obs.findings) == list(ENTITIES)
    assert obs.critic == "fail"


def test_one_unavailable_subject_does_not_discard_the_others(svc):
    critic = _Critic(raises_for={"ENTITY-002"})
    obs = Observer(critic=critic).observe(
        "entity_fields", agent="data_model", subjects=list(ENTITIES),
        doc=svc.doc, pending=set(), planned={"data.entities"})
    assert obs.critic.startswith("unavailable: RuntimeError")
    assert set(obs.findings) == {"ENTITY-001", "ENTITY-003"}


# --- 2. a subject is judged again as soon as its own repair lands ------------

def test_a_fast_repair_is_judged_without_waiting_for_a_slow_one(svc):
    returned: list = []
    author = _author(svc, returned=returned,
                     delay=lambda spec: 0.6 if (spec.subject == "ENTITY-002"
                                                and _repair(spec)) else 0.0)
    critic = _Critic(passes_after={s: 1 for s in ENTITIES})
    report = run(svc, author, plan=["entity_fields"],
                 observer_agent=Observer(critic=critic, rounds=2))

    rechecked_001 = [t for s, t in critic.asked if s == "ENTITY-001"][1]
    repaired_002 = next(t for s, a, t in returned if s == "ENTITY-002" and a)
    assert rechecked_001 < repaired_002, "ENTITY-001 waited for ENTITY-002's repair"
    assert sorted(report.repaired) == [f"entity_fields:{s}" for s in ENTITIES]
    assert "entity_fields" in report.completed


def test_each_subject_counts_its_own_rounds(svc):
    """ENTITY-001 is fixed by its first repair; ENTITY-002 needs both. The
    first finishing early gives the second no extra round, and takes none."""
    critic = _Critic(passes_after={"ENTITY-001": 1, "ENTITY-002": 2, "ENTITY-003": 0})
    report = run(svc, _author(svc), plan=["entity_fields"],
                 observer_agent=Observer(critic=critic, rounds=2))
    repairs = [(e["subject"], e["round"]) for e in _events(svc)
               if e["event"] == "observer:repair"]
    assert sorted(repairs) == [("ENTITY-001", 1), ("ENTITY-002", 1), ("ENTITY-002", 2)]
    assert sorted(report.repaired) == ["entity_fields:ENTITY-001", "entity_fields:ENTITY-002"]
    assert report.unrepaired == {}


# --- 3. the last check does not hold the node ----------------------------------

def test_the_check_after_the_last_repair_does_not_hold_the_node(svc):
    """rounds=1: one repair, then a check that can only flag. It is slow; the
    node completes — and its dependent starts — before the flag is written."""
    def author(spec):
        if spec.node == "security":
            return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9)
        return _author(svc)(spec)

    critic = _Critic(passes_after={"ENTITY-002": 0, "ENTITY-003": 0},
                     delay=lambda s, n: 0.5 if n == 2 else 0.0)
    report = run(svc, author, plan=["entity_fields", "security"],
                 observer_agent=Observer(critic=critic, rounds=1))

    events = _events(svc)
    at = {(e["event"], e.get("node")): i for i, e in enumerate(events)}
    flagged = at[("observer:unrepaired", "entity_fields")]
    assert at[("node:done", "entity_fields")] < flagged
    assert at[("node:start", "security")] < flagged
    # The verdict still lands in full: reported, and the entity flagged.
    assert list(report.unrepaired) == ["entity_fields:ENTITY-001"]
    entity = next(e for e in svc.doc["data"]["entities"] if e["id"] == "ENTITY-001")
    assert entity["status"] == "OUT_OF_SYNC"


def test_a_check_that_can_still_send_back_does_hold_the_node(svc):
    """§28 is unchanged: with a round left, dependents wait for the verdict."""
    def author(spec):
        if spec.node == "security":
            return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9)
        return _author(svc)(spec)

    critic = _Critic(passes_after={"ENTITY-001": 1, "ENTITY-002": 0, "ENTITY-003": 0},
                     delay=lambda s, n: 0.3 if n == 2 else 0.0)
    run(svc, author, plan=["entity_fields", "security"],
        observer_agent=Observer(critic=critic, rounds=2))
    events = _events(svc)
    verdicts = [i for i, e in enumerate(events)
                if e["event"] == "observer:verdict" and e["subject"] == "ENTITY-001"]
    start = next(i for i, e in enumerate(events)
                 if e["event"] == "node:start" and e["node"] == "security")
    assert verdicts[-1] < start

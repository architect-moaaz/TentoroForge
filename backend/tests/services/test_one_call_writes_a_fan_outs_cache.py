"""One call writes a fan-out's cached prefix; the others read it.

HippieKit's rebuild (2026-09-22) wrote page_details' 35,649-token prefix ten
times and workflow_steps' 42,527-token prefix nine times, at 1.25x, and read
it almost never: every first call started together, and a cache entry is
readable only once the response writing it streams. The warm-up that stopped
that (b6588932) was lost with the wave scheduler. These pin it to the event
scheduler.
"""
import threading
import time

import pytest

from services.blueprint import orchestrator
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.executors import _prefix_readable
from services.blueprint.orchestrator import run
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="lab", name="Lab", domain="health")
    s.doc["data"] = {"entities": [{"id": f"ENTITY-00{i}", "name": f"E{i}", "table": f"e{i}"}
                                  for i in range(1, 5)]}
    s.save()
    return s


def _author(svc, *, signals_after=None, runs_for=0.0, log=None):
    lock = threading.Lock()

    def author(spec):
        with lock:
            log.append(("start", spec.subject, time.monotonic()))
        if signals_after is not None:
            time.sleep(signals_after)
            _prefix_readable()           # what the client does at its first streamed event
            with lock:
                log.append(("readable", spec.subject, time.monotonic()))
        time.sleep(runs_for)
        entity = next(e for e in svc.doc["data"]["entities"] if e["id"] == spec.subject)
        body = {"name": entity["name"], "table": entity["table"],
                "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal(section="data.entities",
                                                       natural_key=entity["name"], body=body)])
    return author


def test_the_others_start_once_the_first_calls_prefix_is_readable(svc):
    log: list = []
    run(svc, _author(svc, signals_after=0.3, runs_for=0.5, log=log), plan=["entity_fields"])
    starts = [(s, t) for kind, s, t in log if kind == "start"]
    leader, t_leader = starts[0]
    readable = next(t for kind, s, t in log if kind == "readable" and s == leader)
    followers = [t for s, t in starts[1:]]
    assert len(followers) == 3
    assert all(t >= readable for t in followers), "a follower started before the prefix was readable"
    # ...and they did not wait for the leader to FINISH (0.3s + 0.5s).
    assert max(followers) - t_leader < 0.6


def test_a_first_call_that_cannot_signal_releases_the_others_when_it_returns(svc):
    log: list = []
    t0 = time.monotonic()
    run(svc, _author(svc, runs_for=0.2, log=log), plan=["entity_fields"])
    starts = [t for kind, _, t in log if kind == "start"]
    assert all(t - t0 >= 0.2 for t in starts[1:])
    assert time.monotonic() - t0 < orchestrator.PREFIX_WARM_WAIT_S


def test_a_node_that_does_not_fan_out_is_not_held(svc):
    svc.doc["data"]["entities"] = svc.doc["data"]["entities"][:1]
    log: list = []
    t0 = time.monotonic()
    run(svc, _author(svc, log=log), plan=["entity_fields"])
    assert time.monotonic() - t0 < 1.0 and len(log) == 1

"""The virtual office's two contracts.

1. The office cast *is* the Blueprint agent registry, seated in a declared
   department. If an agent is added to §27's registry with no desk, the office
   silently drops it on the floor — so that is asserted, not assumed.
2. :class:`OfficeNarrator` turns a DAG run's lifecycle events into office
   events. Every branch of ``orchestrator.run`` that can end a node is
   translated into something the office can draw: worked, finished, went round
   again, parked on a question, never started.

The narrator is a pure translation, so none of this needs a model, a
Blueprint, or a browser.
"""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AGENT_REGISTRY
from services.office_events import (
    DEPARTMENTS,
    LEGACY_AGENT_ALIAS,
    PHASE_TO_AGENTS,
    ROOM_OF,
    OfficeNarrator,
    agent_start_event,
    office_agent,
    room_for,
)


# ---------------------------------------------------------------------------
# The cast
# ---------------------------------------------------------------------------

def test_every_blueprint_agent_has_a_desk():
    """A §27 agent with no department cannot be drawn."""
    assert set(AGENT_REGISTRY) == set(ROOM_OF)


def test_every_desk_is_in_a_declared_department():
    assert set(ROOM_OF.values()) <= set(DEPARTMENTS)


def test_every_department_has_someone_in_it():
    """An empty room on the floor plan is a room the user has to explain."""
    occupied = set(ROOM_OF.values())
    assert set(DEPARTMENTS) == occupied


def test_the_legacy_relays_agents_all_land_on_a_real_character():
    """The old pipeline's vocabulary is aliased, not carried as a second cast."""
    for legacy, current in LEGACY_AGENT_ALIAS.items():
        assert current in ROOM_OF, f"{legacy} aliases to unknown agent {current}"


def test_the_relays_phase_agents_resolve_to_departments():
    for phase, agents in PHASE_TO_AGENTS.items():
        for agent in agents:
            assert room_for(agent) in DEPARTMENTS, f"{phase}/{agent}"


def test_a_start_event_seats_the_agent_in_its_own_department():
    """The room the producer names is advisory; the registry decides."""
    evt = agent_start_event("schema_designer", room="nowhere")
    assert evt["agent"] == "data_model"
    assert evt["room"] == "data"


def test_an_unaliased_name_passes_through():
    assert office_agent("a2ui_pages") == "a2ui_pages"


# ---------------------------------------------------------------------------
# The narrator
# ---------------------------------------------------------------------------

@pytest.fixture
def narrated():
    """Collect office events for a scripted run ledger."""
    def run(*lines: dict) -> list[dict]:
        out: list[dict] = []
        narrator = OfficeNarrator(out.append)
        for line in lines:
            narrator(line)
        return out
    return run


PLAN = {"event": "plan", "total": 3,
        "nodes": ["data_model", "page_contracts", "page_layouts"]}


def test_the_plan_line_publishes_the_roster(narrated):
    (plan,) = narrated(PLAN)
    assert plan["type"] == "run_plan"
    # Agents, not node keys — the office moves people.
    assert plan["agents"] == ["a2ui_pages", "data_model", "page_design"]


def test_a_node_start_walks_the_agent_in_and_says_what_it_is_doing(narrated):
    start, status = narrated(PLAN, {
        "event": "node:start", "node": "data_model", "subjects": 1,
    })[1:]
    assert start == {"type": "agent_start", "agent": "data_model",
                     "room": "data", "node": "data_model"}
    assert status["status"] == "Designing the entities"
    assert status["progress"] == 0.0


def test_a_node_the_office_does_not_know_is_ignored_rather_than_guessed(narrated):
    """A ledger line for a node outside this plan names no agent the office can
    move. Better silent than moving the wrong character."""
    assert narrated(PLAN, {"event": "node:start", "node": "testing"})[1:] == []


def test_a_completed_node_sends_a_parcel_to_everyone_waiting(narrated):
    """The only thing on screen that draws the DAG's edges."""
    done, delivery = narrated(PLAN, {
        "event": "node:done", "node": "data_model", "artifacts": 2,
    })[1:]
    assert done["type"] == "agent_complete"
    assert done["files_generated"] == 2
    # page_contracts depends on data_model and is on the plan; database is not.
    assert delivery == {"type": "artifact_delivery", "from": "data_model",
                        "to": "page_design", "artifact": "data_model"}


def test_a_parcel_is_not_sent_to_the_agent_that_just_sent_it(narrated):
    """Two nodes can share one agent. A desk does not post itself mail."""
    events = narrated(
        {"event": "plan", "nodes": ["data_model", "database"]},
        {"event": "node:done", "node": "data_model", "artifacts": 0},
    )
    assert not [e for e in events if e["type"] == "artifact_delivery"]


def test_a_fanout_reports_its_position(narrated):
    (status,) = narrated(PLAN, {
        "event": "node:subject", "node": "page_layouts", "subject": "PAGE-009",
        "index": 3, "total": 18, "ok": True,
    })[1:]
    assert "(3/18)" in status["status"]
    assert status["subject"] == "PAGE-009"
    assert status["progress"] == pytest.approx(3 / 18)


def test_a_node_that_authors_one_thing_shows_no_counter(narrated):
    """A single-subject node has no progress to show *through* it; its start
    and its completion already say everything."""
    assert narrated(PLAN, {
        "event": "node:subject", "node": "data_model", "subject": "",
        "index": 1, "total": 1, "ok": True,
    })[1:] == []


def test_a_refused_proposal_shows_as_a_retry_with_the_reason(narrated):
    (retry,) = narrated(PLAN, {
        "event": "node:retry", "node": "page_layouts", "subject": "PAGE-009",
        "attempt": 2, "of": 2,
        "reason": "component   DataTable\nis not in the catalog",
    })[1:]
    assert retry["type"] == "agent_retry"
    assert retry["attempt"] == 2 and retry["of"] == 2
    # Collapsed to one line — it has to fit in a speech bubble.
    assert retry["reason"] == "component DataTable is not in the catalog"


def test_blocked_and_skipped_are_different_events(narrated):
    """They look the same in a log and mean opposite things: blocked asked a
    question, skipped never got to ask one."""
    _, blocked, skipped = narrated(
        PLAN,
        {"event": "node:blocked", "node": "page_contracts", "reason": "not ported yet"},
        {"event": "node:skipped", "node": "page_layouts", "unmet": "patterns"},
    )
    assert blocked["type"] == "agent_blocked"
    assert skipped["type"] == "agent_skipped"
    assert "patterns" in skipped["reason"]


def test_a_failure_is_an_error_not_a_block(narrated):
    (err,) = narrated(PLAN, {"event": "node:failed", "node": "data_model",
                             "reason": "envelope was malformed"})[1:]
    assert err == {"type": "agent_error", "agent": "data_model",
                   "message": "envelope was malformed"}


def test_a_clean_run_throws_the_party(narrated):
    (done,) = narrated(PLAN, {
        "event": "run:end", "completed": ["data_model", "page_contracts"],
        "failed": [], "blocked": [], "skipped": [],
    })[1:]
    assert done["type"] == "build_success"
    assert done["total_files"] == 2


def test_a_run_with_failures_does_not(narrated):
    """Confetti over a half-built app is a lie the office should not tell."""
    (done,) = narrated(PLAN, {
        "event": "run:end", "completed": ["data_model"], "failed": ["workflows"],
        "blocked": [], "skipped": [],
    })[1:]
    assert done["type"] == "run_complete"
    assert done["failed"] == 1


def test_a_crashed_run_still_ends_the_office(narrated):
    """`run:crashed` is the line that exists because a run used to stop and say
    nothing. If the office ignored it, it would wait forever for a finish."""
    (done,) = narrated(PLAN, {
        "event": "run:crashed", "error": "RuntimeError: the model went away",
    })[1:]
    assert done["type"] == "run_complete"
    assert done["failed"] == 1
    assert "went away" in done["error"]


def test_lines_the_office_does_not_need_are_ignored(narrated):
    """The ledger is written for post-mortems and will grow lines the office
    has no use for. It must not have to know about all of them."""
    assert narrated({"event": "run:start", "phase": "build", "pid": 42}) == []
    assert narrated({"event": "something:new", "node": "data_model"}) == []


def test_a_narrator_that_raises_does_not_fail_the_run(tmp_path):
    """The run is load-bearing; watching it is not."""
    from services.blueprint.run_ledger import RunLedger

    def boom(line):
        raise RuntimeError("the browser went away")

    ledger = RunLedger(tmp_path, "run-1", observer=boom)
    ledger.node_start("data_model")  # must not raise
    assert (tmp_path / ".forge" / "runs" / "run-1.jsonl").exists()


def test_the_observer_sees_every_line_the_ledger_writes(tmp_path):
    """One account, two readers. A line that reaches disk reaches the office."""
    import json

    from services.blueprint.run_ledger import RunLedger

    seen: list[dict] = []
    ledger = RunLedger(tmp_path, "run-2", observer=seen.append)
    ledger.planned(["data_model"])
    ledger.node_start("data_model", 1)
    ledger.node_subject("data_model", "", 1, 1, True)
    ledger.node_retry("data_model", "", 2, 2, "rejected")
    ledger.node_done("data_model", 3)

    on_disk = [json.loads(line) for line in
               (tmp_path / ".forge" / "runs" / "run-2.jsonl").read_text().splitlines()]
    assert [e["event"] for e in seen] == [e["event"] for e in on_disk]

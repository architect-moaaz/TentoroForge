"""A `wait` is a pause the clock ends, declared as `for` or `until`; an
unreadable one is refused at the author (it used to be `Number("1 hour")`,
NaN, a wait of zero). The runtime suite `run-clock-tests.sh` runs the
shipped engine through a two-day wait."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidTrigger, check_workflow_triggers

DOC = {"roles": [{"id": "ROLE-001", "name": "Manager"}], "data": {"entities": [{"id": "ENTITY-001", "name": "Order"}]},
       "integrations": [{"id": "INT-001", "name": "Shop", "status": "APPROVED"}]}


def _flow(trigger: dict, steps: list[dict]) -> AgentResult:
    return AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Follow up", body={"name": "Follow up", "trigger": trigger, "steps": steps})])


def test_a_readable_wait_and_a_readable_deadline_pass():
    check_workflow_triggers(_flow({"kind": "manual"}, [
        {"key": "pause", "type": "wait", "config": {"for": "2 days"}},
        {"key": "later", "type": "wait", "config": {"until": "{{booking.startsAt}}"}},
        {"key": "sign", "type": "approval", "config": {"assignType": "role", "assignTarget": "ROLE-001",
                                                       "dueIn": 2880, "escalateTo": "ROLE-001"}}]), DOC)


@pytest.mark.parametrize("trigger,steps,said", [
    ({"kind": "manual"}, [{"key": "pause", "type": "wait", "config": {"duration": ""}}], "a wait says how long"),
    ({"kind": "manual"}, [{"key": "pause", "type": "wait", "config": {"for": "soon"}}], "a wait says how long"),
    ({"kind": "schedule", "detail": "every monday"}, [], "five fields"),
    ({"kind": "schedule", "cron": "0 9 * * 1", "timezone": "Mars/Olympus"}, [], "not an IANA zone"),
    ({"kind": "db_change", "entity": "ENTITY-404", "on": "created"}, [], "names the record type"),
    ({"kind": "db_change", "entity": "ENTITY-001", "on": "touched"}, [], "which change"),
    ({"kind": "webhook", "event": "order.paid"}, [], "names the integration"),
    ({"kind": "manual"}, [{"key": "sign", "type": "approval", "config": {"assignType": "role", "assignTarget": "x", "escalateTo": "Boss"}}], "declared role"),
    ({"kind": "manual"}, [{"key": "sign", "type": "approval", "config": {"assignType": "role", "assignTarget": "x", "dueIn": "two days"}}], "number of minutes"),
])
def test_what_the_clock_cannot_read_is_refused_with_what_to_write(trigger, steps, said):
    with pytest.raises(InvalidTrigger, match=said):
        check_workflow_triggers(_flow(trigger, steps), DOC)


def test_the_engine_puts_a_long_wait_down_and_the_tick_picks_it_up():
    runtime = Path(__file__).resolve().parents[2] / "templates" / "runtime"
    engine = (runtime / "workflows" / "engine.ts").read_text()
    assert 'taskType: "wait_timer"' in engine and "parseDurationMs(" in engine
    bus = (runtime / "events" / "bus.ts").read_text()
    assert "task_type IN ('wait_for_event', 'wait_timer')" in bus and "buildTimerResumeInput" in bus
    catalog = (Path(__file__).resolve().parents[2] / "contracts" / "workflow-node-catalog.json").read_text()
    assert '"1 hour"' not in catalog, "the default that waited zero is gone"

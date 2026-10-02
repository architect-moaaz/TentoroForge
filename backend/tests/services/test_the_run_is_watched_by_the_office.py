"""The office is told everything the ledger says, and who is who.

The v3 panel showed a build as a list of stages ticking off — linear, and
silent about the fan-out, the reviewer, the retries and the API stalls that
are most of what happens. The office already animates all of those; it only
lacked the events. The relay now forwards the stall and the pause, and the
plan carries each node's agent and the plan's concurrency levels.
"""
from services.blueprint.run_progress import Progress


def test_the_relay_forwards_a_stall_and_a_pause():
    got = []
    p = Progress(lambda ev, data: got.append((ev, data)), total=3)
    p({"event": "node:stalled", "node": "entity_fields", "subject": "ENTITY-002", "reason": "529", "at": "t"})
    p({"event": "run:paused", "reason": "credit balance is too low", "at": "t"})
    assert [e for e, _ in got] == ["node:stalled", "run:paused"]
    assert got[1][1] == {"event": "run:paused", "reason": "credit balance is too low"}


def test_the_plan_names_each_nodes_agent_and_the_levels():
    from routers.blueprint_generate import _plan_event

    ev = _plan_event(["requirements", "application_model", "data_model", "design_system", "entity_fields"], [], False)
    assert ev["agents"] == {"requirements": "requirement", "application_model": "product_analysis",
                            "data_model": "data_model", "design_system": "accessibility",
                            "entity_fields": "data_model"}
    assert ev["levels"] == [["requirements"], ["application_model"], ["data_model", "design_system"], ["entity_fields"]]
    assert ev["total"] == 5 and ev["awaitingApproval"] is False

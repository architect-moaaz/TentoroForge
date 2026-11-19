"""A run an EVENT starts is the application's own, not the person who caused the event.

(A workflow's own write used to be announced here by `announceRecordChange`; smithv5's `_announce` replaced it and has its own
behaviour test, `a-process-write-starts-the-process-that-watches-it.test.mts`. What stays is the marking and the scoping.)
"""
from pathlib import Path

WORKFLOWS = (Path(__file__).resolve().parents[2] / "templates" / "runtime" / "workflows" / "index.ts").read_text(encoding="utf-8")


BUS = (Path(__file__).resolve().parents[2] / "templates" / "runtime" / "events" / "bus.ts").read_text(encoding="utf-8")


def test_a_run_an_event_starts_is_the_applications_own_not_the_person_who_caused_it():
    """Scoped to the restaurant manager who pressed "ready", the dispatch step found no drivers (a manager reaches none) and
    no driver was ever offered the order."""
    assert "__byEvent: evt.type" in BUS
    scoped = WORKFLOWS[WORKFLOWS.index("async function _scoped"):WORKFLOWS.index("async function _trail")]
    assert "variables?.__byEvent" in scoped and "return where" in scoped


def test_a_run_a_person_starts_is_still_scoped_to_that_person():
    scoped = WORKFLOWS[WORKFLOWS.index("async function _scoped"):WORKFLOWS.index("async function _trail")]
    assert "scopeForTable(table, user, op" in scoped   # only the event's run is exempt

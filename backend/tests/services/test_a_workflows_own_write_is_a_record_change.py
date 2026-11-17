"""A workflow's own write raises the same record-change event a data-API write raises.

The event bus carried only writes that went through the data API. A workflow that starts when a record changes ("an order has just
become ready: offer it to the drivers") never started when ANOTHER workflow made the change ("Mark ready for pickup"): no event, no
offers, and a driver could not see the order (Zomato, 2026-11-16). The workflow handlers now announce what they write.
"""
from pathlib import Path

WORKFLOWS = (Path(__file__).resolve().parents[2] / "templates" / "runtime" / "workflows" / "index.ts").read_text(encoding="utf-8")


def _handler(name: str) -> str:
    start = WORKFLOWS.index(f'registerActionHandler("{name}"')
    nxt = WORKFLOWS.find("registerActionHandler(", start + 10)
    return WORKFLOWS[start:nxt if nxt > 0 else len(WORKFLOWS)]


def test_an_update_announces_each_row_with_the_row_it_was():
    h = _handler("db_update")
    assert 'announceRecordChange("updated", table, r,' in h
    assert "was.get(String(r?.id))" in h               # `previousEntity`: a trigger can ask what the record WAS


def test_the_previous_rows_are_read_whether_or_not_the_audit_is_on():
    h = _handler("db_update")
    assert "auditOn() ? await" not in h                # it used to read them only for the audit trail


def test_an_insert_announces_the_record_it_made():
    assert 'announceRecordChange("created", table, sealedRow' in _handler("db_insert")


def test_the_event_has_the_same_name_and_shape_the_data_engine_gives():
    helper = WORKFLOWS[WORKFLOWS.index("function announceRecordChange"):WORKFLOWS.index("function numericColumnsAsNumbers")]
    assert "`${key}.${op}`" in helper                  # `orders.updated`, as the trigger names it
    assert "entity: row" in helper and "previousEntity: previous" in helper
    assert "emitEventAndProcess" in helper


def test_a_bus_failure_never_fails_the_write_and_the_platforms_own_tables_are_left_alone():
    helper = WORKFLOWS[WORKFLOWS.index("function announceRecordChange"):WORKFLOWS.index("function numericColumnsAsNumbers")]
    assert ".catch(" in helper and "non-fatal" in helper
    assert 'key.startsWith("forge_")' in helper


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

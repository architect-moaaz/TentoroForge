"""Self-heal heals an application once for everything open, and never while
other work is fixing it.

Refund And Chargeback (pah7lhfz, 2026-10-21): a checks run broke 25
processes; each new error started its own Opus turn at once — five at a
time, three tries each, blind to each other and to the checks fixing the
same app — and the hour cost $92.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from services import self_healing as sh


def _err(i: int, **over) -> dict:
    base = {"id": uuid.uuid4(), "project_id": uuid.uuid4(), "kind": "workflow",
            "message": f"invalid input syntax for type uuid: \"CASE-{i}\"", "stack": None,
            "source_file": None, "source_line": None, "workflow_id": f"flow-{i}", "node_id": "record",
            "page_route": None, "request_url": None, "request_method": None,
            "occurrence_count": 1, "heal_attempts": 1}
    base.update(over)
    return base


@pytest.fixture
def app(monkeypatch):
    """A heal's surroundings, faked: the queue of open errors, the busy
    ledger, and the turn itself."""
    state = {"open": [], "busy": 0, "turns": []}

    async def output_dir(_pid):
        return "/tmp/app"

    async def claim(_pid):
        taken, state["open"] = state["open"][:sh._MAX_BATCH], state["open"][sh._MAX_BATCH:]
        return taken

    async def heal(_pid, _out, batch):
        state["turns"].append([b["message"] for b in batch])
        return {"status": "resolved", "errors": len(batch)}

    def in_flight(_out):
        if state["busy"]:
            state["busy"] -= 1
            return True
        return False

    from services import run_registry
    monkeypatch.setattr(sh, "_output_dir_of", output_dir)
    monkeypatch.setattr(sh, "_claim_open_errors", claim)
    monkeypatch.setattr(sh, "_heal_batch", heal)
    monkeypatch.setattr(run_registry, "work_in_flight", in_flight)
    monkeypatch.setattr(sh, "_BUSY_POLL_S", 0.0)
    sh._heal_turns.clear()
    sh._healing.clear()
    return state


def test_every_open_error_goes_into_one_turn(app):
    app["open"] = [_err(i) for i in range(5)]
    out = asyncio.run(sh.invoke_smith_on_exception(uuid.uuid4(), uuid.uuid4()))
    assert out["status"] == "resolved"
    assert len(app["turns"]) == 1 and len(app["turns"][0]) == 5


def test_a_heal_waits_while_other_work_fixes_the_app(app):
    app["open"] = [_err(1)]
    app["busy"] = 4
    asyncio.run(sh.invoke_smith_on_exception(uuid.uuid4(), uuid.uuid4()))
    assert app["busy"] == 0, "it started while the app was busy"
    assert len(app["turns"]) == 1


def test_a_heal_that_waited_too_long_leaves_the_errors_open(app, monkeypatch):
    monkeypatch.setattr(sh, "_BUSY_GIVE_UP_S", 0.0)
    app["open"] = [_err(1)]
    app["busy"] = 10
    out = asyncio.run(sh.invoke_smith_on_exception(uuid.uuid4(), uuid.uuid4()))
    assert out["status"] == "deferred" and app["turns"] == [] and len(app["open"]) == 1


def test_an_error_while_a_heal_runs_joins_it(app):
    pid = uuid.uuid4()
    sh._healing.add(pid)
    out = asyncio.run(sh.invoke_smith_on_exception(pid, uuid.uuid4()))
    assert out["status"] == "queued" and app["turns"] == []


def test_more_errors_than_one_turn_takes_go_to_the_next_round(app):
    app["open"] = [_err(i) for i in range(sh._MAX_BATCH + 3)]
    asyncio.run(sh.invoke_smith_on_exception(uuid.uuid4(), uuid.uuid4()))
    assert [len(t) for t in app["turns"]] == [sh._MAX_BATCH, 3]


def test_heal_turns_are_capped_per_hour(app, monkeypatch):
    monkeypatch.setattr(sh, "_MAX_HEAL_TURNS_PER_HOUR", 1)
    pid = uuid.uuid4()
    app["open"] = [_err(1)]
    asyncio.run(sh.invoke_smith_on_exception(pid, uuid.uuid4()))
    app["open"] = [_err(2)]
    out = asyncio.run(sh.invoke_smith_on_exception(pid, uuid.uuid4()))
    assert out["status"] == "rate_limited" and len(app["turns"]) == 1


def test_the_ask_names_every_error_and_asks_for_the_shared_cause():
    text = sh._synthesize_batch_prompt([_err(1), _err(2, workflow_id="approve-case")])
    assert "2 different runtime errors" in text and "CASE-1" in text and "CASE-2" in text
    assert "approve-case" in text and "cause once" in text
    assert text.count("RULES for runtime-exception healing") == 1
    assert sh._synthesize_batch_prompt([_err(1)]) == sh._synthesize_smith_prompt(_err(1))


def test_the_card_lists_the_other_errors():
    first, other = _err(1), _err(2)
    meta = sh._terminal_metadata(first, ["app/x.ts"], "abc", {"answer": "Fixed both."}, [other])
    assert meta["others"][0]["error_message"].endswith('"CASE-2"')
    assert "and 1 more error" in sh._format_chat_message(first, {"answer": "x"}, None, others=[other])


@pytest.mark.asyncio
async def test_the_open_errors_are_claimed_most_frequent_first_and_tried_out_ones_retired(test_db, auth_client, org_id):
    from database import async_session
    from models.runtime_exception import RuntimeException, RuntimeExceptionKind, RuntimeExceptionStatus
    resp = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Heal"})
    assert resp.status_code in (200, 201), resp.text
    pid = uuid.UUID(resp.json()["id"])
    async with async_session() as db:
        for i, (seen, tries, status) in enumerate([(1, 0, "open"), (9, 1, "open"), (4, 3, "open"),
                                                   (2, 0, "resolved")]):
            db.add(RuntimeException(project_id=pid, kind=RuntimeExceptionKind.workflow, message=f"e{i}",
                                    dedup_key=f"k{i}", occurrence_count=seen, heal_attempts=tries,
                                    status=RuntimeExceptionStatus(status)))
        await db.commit()
    batch = await sh._claim_open_errors(pid)
    assert [b["message"] for b in batch] == ["e1", "e0"]
    assert [b["heal_attempts"] for b in batch] == [2, 1]
    async with async_session() as db:
        from sqlalchemy import select
        rows = {r.message: r.status.value for r in (await db.execute(select(RuntimeException))).scalars()}
    assert rows == {"e0": "in_progress", "e1": "in_progress", "e2": "unresolvable", "e3": "resolved"}

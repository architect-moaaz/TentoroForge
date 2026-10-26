"""The buffer and the worker: nothing is lost when a worker dies, nothing is counted twice when an entry is delivered again.

The bus contract is checked against the in-memory twin and, where the `fakeredis` package is installed (tests only), against the
real Redis code path (streams, consumer groups, XAUTOCLAIM, HyperLogLog) running on it.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio

from database import async_session
from models.agent_insights import agent_turn_events
from services import agent_insights_bus as bus_mod
from services import agent_insights_store as store
from services import agent_insights_summary as summary
from services import agent_insights_worker as worker_mod
from services.agent_insights_bus import MemoryBus, RedisBus, pack, unpack
from tests.insights_stream_helpers import NOW, Truth, norm, random_events, turn

PID = uuid.UUID("cccccccc-1111-2222-3333-444444444444")
OTHER = uuid.UUID("dddddddd-1111-2222-3333-444444444444")


def make_bus(kind: str):
    if kind == "memory":
        return MemoryBus()
    fakeredis = pytest.importorskip("fakeredis")
    return RedisBus(fakeredis.FakeAsyncRedis(decode_responses=False))


@pytest.fixture(params=["memory", "redis"])
def bus(request):
    return make_bus(request.param)


@pytest_asyncio.fixture
async def db(test_db):
    bus_mod.use_bus(None)
    yield
    bus_mod.reset_bus()


def payload(events, pid=PID):
    return pack(str(pid), NOW.timestamp(), norm(events))


async def totals(pid=PID, range_="24h"):
    async with async_session() as s:
        out = await summary.build_summary(s, pid, range_=range_, now=NOW)
    return out["insights"]["totals"] if out["ok"] else None


# --- the bus ----------------------------------------------------------------------------------------------------

def test_a_payload_round_trips_and_large_ones_are_compressed():
    small = pack("p", 1.0, norm([turn(1, NOW)]))
    big = pack("p", 1.0, norm([turn(i, NOW) for i in range(300)]))
    assert small[:1] == b"j" and big[:1] == b"z"
    assert unpack(big)["p"] == "p" and len(unpack(big)["e"]) == 300 and len(big) < 300 * 120


@pytest.mark.asyncio
async def test_an_entry_is_read_once_kept_until_acknowledged_and_removed_after(bus):
    await bus.publish(b"j{}")
    assert await bus.depth(0) == 1
    got = await bus.read("w1", 10, 50)
    assert len(got) == 1
    assert await bus.read("w2", 10, 0) == []         # a second worker is not handed the same entry
    assert await bus.depth(0) == 1                   # still counted as backlog: it has not been applied
    await bus.ack([got[0][0]])
    assert await bus.depth(0) == 0


@pytest.mark.asyncio
async def test_an_entry_a_worker_never_finished_goes_to_another_worker_with_its_delivery_count(bus):
    await bus.publish(b"j{}")
    (entry_id, _), = await bus.read("w1", 10, 50)
    await asyncio.sleep(0.03)
    assert await bus.claim_stale("w2", 60_000, 10) == []             # not idle long enough yet
    claimed = await bus.claim_stale("w2", 10, 10)
    assert [(c[0], c[2]) for c in claimed] == [(entry_id, 2)]        # delivered a second time
    await bus.ack([entry_id])
    assert await bus.claim_stale("w3", 0, 10) == [] and await bus.depth(0) == 0


@pytest.mark.asyncio
async def test_an_entry_set_aside_leaves_the_backlog(bus):
    await bus.publish(b"j{}")
    (entry_id, data), = await bus.read("w1", 10, 50)
    await bus.dead_letter(entry_id, data)
    assert await bus.depth(0) == 0


@pytest.mark.asyncio
async def test_distinct_counters_count_people_once_and_merge_across_keys(bus):
    await bus.hll_add([("k-a", 60, ["u1", "u2"]), ("k-b", 60, ["u2", "u3"])])
    await bus.hll_add([("k-a", 60, ["u1", "u2"])])        # the same people again: nothing changes
    assert await bus.hll_counts([["k-a"], ["k-a", "k-b"], ["missing"], []]) == [2, 3, 0, 0]


# --- the worker -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_worker_applies_entries_for_several_projects_and_acknowledges_them(db, bus):
    await bus.publish(payload([turn(1, NOW - timedelta(minutes=5)), turn(2, NOW - timedelta(minutes=4), user=2)]))
    await bus.publish(payload([turn(3, NOW - timedelta(minutes=3))]))
    await bus.publish(payload([turn(1, NOW - timedelta(minutes=2))], pid=OTHER))
    w = worker_mod.InsightsWorker(consumer="w1")
    assert await w.drain(bus, timeout=5) == 3
    assert (await totals())["turns"] == 3 and (await totals(OTHER))["turns"] == 1
    assert await bus.depth(0) == 0


@pytest.mark.asyncio
async def test_a_worker_killed_after_saving_but_before_acknowledging_loses_nothing_and_double_counts_nothing(db, bus):
    rng = random.Random(5)
    events = random_events(rng, turns=120, users=15, hours=5)
    for i in range(0, len(events), 40):
        await bus.publish(payload(events[i:i + 40]))

    class Killed(Exception):
        pass

    real_ack = bus.ack

    async def die(ids):
        raise Killed()

    bus.ack = die
    w1 = worker_mod.InsightsWorker(consumer="w1", stale_ms=0)
    with pytest.raises(Killed):
        await w1.run_once(bus, block_ms=0)                 # applied to the database, then "killed" before the acknowledgement
    bus.ack = real_ack
    assert await bus.depth(0) > 0                          # still waiting: nobody acknowledged it
    mid = await totals()
    w2 = worker_mod.InsightsWorker(consumer="w2", stale_ms=0)
    await asyncio.sleep(0.02)
    await w2.drain(bus, timeout=10)                        # the other worker takes over what the dead one held
    after = await totals()
    truth = Truth(events, NOW, "24h")
    assert mid["turns"] > 0 and after["turns"] == truth.turns
    assert (after["inputTokens"], after["outputTokens"], after["errors"], after["up"], after["down"]) == \
           (truth.input_tokens, truth.output_tokens, truth.errors, truth.up, truth.down)
    assert await bus.depth(0) == 0


@pytest.mark.asyncio
async def test_a_worker_whose_database_write_fails_leaves_the_entry_to_be_retried(db, bus, monkeypatch):
    events = [turn(i, NOW - timedelta(minutes=i + 1)) for i in range(10)]
    await bus.publish(payload(events))
    real = store.apply_events

    async def broken(*a, **k):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(store, "apply_events", broken)
    w = worker_mod.InsightsWorker(consumer="w1", stale_ms=0)
    assert await w.run_once(bus, block_ms=0) == 0
    assert await bus.depth(0) == 1 and await totals() is None
    monkeypatch.setattr(store, "apply_events", real)
    await asyncio.sleep(0.02)
    assert await w.drain(bus, timeout=5) == 1
    assert (await totals())["turns"] == 10 and await bus.depth(0) == 0


@pytest.mark.asyncio
async def test_an_entry_nobody_can_read_or_that_keeps_coming_back_is_set_aside_not_retried_forever(db, bus):
    await bus.publish(b"zNOT-COMPRESSED-DATA")
    w = worker_mod.InsightsWorker(consumer="w1")
    await w.run_once(bus, block_ms=50)
    assert w.dead_lettered == 1 and await bus.depth(0) == 0
    await bus.publish(payload([turn(1, NOW - timedelta(minutes=1))]))
    (entry_id, data), = await bus.read("w1", 5, 50)
    n = await w.process(bus, [(entry_id, data, bus_mod.MAX_DELIVERIES + 1)])
    assert n == 0 and w.dead_lettered == 2 and await totals() is None


@pytest.mark.asyncio
async def test_the_same_entry_applied_twice_by_two_workers_counts_once(db, bus):
    await bus.publish(payload([turn(i, NOW - timedelta(minutes=i + 1), user=i) for i in range(6)]))
    (entry_id, data), = await bus.read("w1", 5, 50)
    w1, w2 = worker_mod.InsightsWorker(consumer="w1"), worker_mod.InsightsWorker(consumer="w2")
    await w1.process(bus, [(entry_id, data, 1)])
    await w2.process(bus, [(entry_id, data, 2)])           # redelivered after the first already saved it
    assert (await totals())["turns"] == 6
    async with async_session() as s:
        from sqlalchemy import func, select

        assert (await s.execute(select(func.count()).select_from(agent_turn_events))).scalar() == 6


@pytest.mark.asyncio
async def test_the_worker_starts_works_and_stops_cleanly(db):
    memory = MemoryBus()
    bus_mod.use_bus(memory)
    w = worker_mod.InsightsWorker(consumer="w1", block_ms=50)
    await w.start()
    await memory.publish(payload([turn(i, NOW - timedelta(minutes=i + 1)) for i in range(5)]))
    for _ in range(100):
        if await memory.depth(0) == 0 and w.applied_events == 5:
            break
        await asyncio.sleep(0.05)
    assert w.applied_events == 5
    await asyncio.wait_for(w.stop(), 10)
    assert all(t.done() for t in w._tasks) and w._tasks == []
    assert (await totals())["turns"] == 5


def test_the_worker_is_off_until_it_is_switched_on(monkeypatch):
    monkeypatch.setenv("FORGE_INSIGHTS_WORKER", "0")
    assert worker_mod.enabled() is False
    monkeypatch.setenv("FORGE_INSIGHTS_WORKER", "1")
    assert worker_mod.enabled() is True
    monkeypatch.setenv("FORGE_INSIGHTS_WORKER", "")
    assert worker_mod.enabled() is False
    monkeypatch.delenv("FORGE_INSIGHTS_WORKER")
    assert worker_mod.enabled() is False        # the Insights page still says "Coming soon": nothing runs by default


@pytest.mark.asyncio
async def test_a_stream_batch_updates_the_distinct_people_counters_after_it_is_saved(db):
    bus = MemoryBus()
    await bus.publish(payload([turn(i, NOW - timedelta(minutes=1), user=i % 4) for i in range(12)]))
    w = worker_mod.InsightsWorker(consumer="w1")
    await w.drain(bus, timeout=5)
    key = store.hll_key(str(PID), "support", "Admin", "hour", int(NOW.replace(minute=0, second=0).timestamp()))
    assert await bus.hll_counts([[key]]) == [4]

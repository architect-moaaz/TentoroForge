"""The same writer and summary, on a real Postgres (the day-partitioned raw table, the array-based bulk upserts, advisory locks, two workers at once).

The rest of the suite runs on in-memory SQLite, which cannot show any of that. This file is skipped unless FORGE_INSIGHTS_TEST_PG names a
SCRATCH database (its name must start with "loadtest": the tables in it are dropped and re-made), for example

    FORGE_INSIGHTS_TEST_PG=postgresql+asyncpg://scratch@127.0.0.1:5599/loadtest_parity python -m pytest tests/services/test_agent_insights_postgres.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

URL = os.getenv("FORGE_INSIGHTS_TEST_PG")
pytestmark = pytest.mark.skipif(not URL, reason="FORGE_INSIGHTS_TEST_PG (a scratch Postgres) is not set")

import models  # noqa: E402,F401
from database import Base  # noqa: E402
from models.agent_insights import agent_turn_events  # noqa: E402
from services import agent_insights_bus as bus_mod  # noqa: E402
from services import agent_insights_store as store  # noqa: E402
from services import agent_insights_summary as summary  # noqa: E402
from services import agent_insights_worker as worker_mod  # noqa: E402
from tests.insights_stream_helpers import NOW, Truth, _dt as _dt_, norm, random_events, turn  # noqa: E402
from tests.services.test_agent_insights_summary import check  # noqa: E402

PID = uuid.UUID("eeeeeeee-1111-2222-3333-444444444444")


@pytest_asyncio.fixture
async def pg():
    from tools.insights_load_test import _prepare_schema

    engine = create_async_engine(URL)
    await _prepare_schema(engine, Base, "postgresql", argparse.Namespace(create_schema=True))
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO projects (id) VALUES (:p) ON CONFLICT DO NOTHING"), {"p": PID})
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def apply(sf, events, pid=PID, now=NOW):
    async with sf() as s, s.begin():
        return await store.apply_events(s, pid, norm(events, now), now=now)


async def get(sf, range_, agent=None, role=None, pid=PID):
    async with sf() as s:
        out = await summary.build_summary(s, pid, range_=range_, agent_id=agent, role=role, now=NOW)
    assert out["ok"], out
    return out["insights"]


@pytest.mark.asyncio
async def test_the_refusal_to_touch_a_database_that_is_not_a_scratch_one():
    from tools.insights_load_test import _prepare_schema

    with pytest.raises(SystemExit):
        await _prepare_schema(create_async_engine("postgresql+asyncpg://x@127.0.0.1:1/production"), Base, "postgresql",
                              argparse.Namespace(create_schema=True))


@pytest.mark.asyncio
async def test_the_raw_table_is_partitioned_by_day_and_the_summary_equals_brute_force(pg):
    async with pg() as s:
        parts = (await s.execute(text("SELECT count(*) FROM pg_inherits i JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'agent_turn_events'"))).scalar()
    assert parts >= 38
    rng = random.Random(3)
    events = random_events(rng, turns=400, users=60, hours=40, days_back=25)
    pieces = [events[i::3] for i in range(3)]
    for piece in pieces:
        await apply(pg, piece)
    await apply(pg, pieces[1])
    for range_ in ("1h", "24h", "7d", "30d"):
        for agent, role in ((None, None), ("support", None), (None, "Admin"), ("sales", "(no role)")):
            check(await get(pg, range_, agent, role), Truth(events, NOW, range_, agent, "" if role == "(no role)" else role), range_,
                  filtered=bool(agent or role))
    async with pg() as s:
        where = (await s.execute(text("SELECT tableoid::regclass::text, count(*) FROM agent_turn_events GROUP BY 1"))).all()
    assert sum(n for _t, n in where) == len({e["id"] for e in events if e["type"] == "turn"})
    assert all(name.startswith("agent_turn_events_p") for name, _n in where)


@pytest.mark.asyncio
async def test_an_event_older_than_the_partitions_lands_in_the_default_one_and_is_still_counted_once(pg):
    old = turn(1, NOW - timedelta(days=60))
    await apply(pg, [old])
    await apply(pg, [old])
    async with pg() as s:
        got = (await s.execute(text("SELECT tableoid::regclass::text, count(*) FROM agent_turn_events GROUP BY 1"))).all()
    assert got == [("agent_turn_events_default", 1)]
    assert (await get(pg, "90d"))["totals"]["turns"] == 1


@pytest.mark.asyncio
async def test_housekeeping_drops_day_partitions_older_than_30_days_and_makes_the_coming_ones(pg):
    await apply(pg, [turn(1, NOW - timedelta(minutes=5))])
    far = NOW + timedelta(days=45)
    done = await store.housekeeping(pg, now=far)
    assert any(d.startswith("agent_turn_events_p") for d in done["partitions_dropped"]) and done["partitions_made"]
    async with pg() as s:
        left = (await s.execute(select(func.count()).select_from(agent_turn_events))).scalar()
    assert left == 0                                         # the day's partition (22 Oct) is 45 days old at `far`
    again = await store.housekeeping(pg, now=far)
    assert again["partitions_made"] == []                    # nothing more to make


@pytest.mark.asyncio
async def test_two_workers_applying_the_same_project_at_once_do_not_deadlock_or_double_count(pg):
    bus = bus_mod.MemoryBus()
    rng = random.Random(8)
    events = random_events(rng, turns=600, users=80, hours=5)
    for i in range(0, len(events), 60):
        await bus.publish(bus_mod.pack(str(PID), NOW.timestamp(), norm(events[i:i + 60])))
    w1, w2 = (worker_mod.InsightsWorker(session_factory=pg, consumer=f"w{i}", read_count=4) for i in (1, 2))

    async def run(w):
        while await bus.depth(0):
            if not await w.run_once(bus, block_ms=0):
                await asyncio.sleep(0.01)      # nothing left to read: the other worker holds the rest; let it run

    await asyncio.gather(run(w1), run(w2))
    await store.sweep_pending_ratings(pg, now=NOW)
    truth = Truth(events, NOW, "24h")
    t = (await get(pg, "24h"))["totals"]
    assert (t["turns"], t["inputTokens"], t["errors"], t["up"], t["down"]) == (truth.turns, truth.input_tokens, truth.errors, truth.up, truth.down)
    assert w1.applied_events + w2.applied_events == truth.turns
    assert w1.applied_events > 0 and w2.applied_events > 0


@pytest.mark.asyncio
async def test_the_people_cache_is_refreshed_on_postgres_and_its_top_list_equals_brute_force(pg):
    from services import agent_insights_people as people
    from tests.services.test_agent_insights_people import brute_top

    rng = random.Random(21)
    events = random_events(rng, turns=500, users=50, hours=30, days_back=25)
    await apply(pg, events)
    for range_ in ("1h", "24h", "7d", "30d", "90d"):                 # a first request each: works it out inside its limit and stores it
        async with pg() as s:
            out = await summary.build_summary(s, PID, range_=range_, now=NOW, use_cache=True)
        assert out["ok"] and out["insights"]["users"]["topAsOf"] is not None
    done = await people.refresh_due(pg, now=NOW + timedelta(seconds=5), force=True)
    assert done["refreshed"] == 5
    for range_ in ("1h", "24h", "7d", "30d", "90d"):
        async with pg() as s:
            ins = (await summary.build_summary(s, PID, range_=range_, now=NOW + timedelta(seconds=6), use_cache=True))["insights"]
        since = people.window_start(NOW + timedelta(seconds=5), range_)
        assert [(u["userKey"], u["turns"]) for u in ins["users"]["top"]] == brute_top(events, since.date()), range_
        assert ins["users"]["active"] == len({e["userKey"] for e in events if e["type"] == "turn" and _dt_(e["at"]) >= since}), range_

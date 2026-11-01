"""The people numbers (top users, different people, people per role) come from a cache the worker refreshes, never from a scan on the
summary request. These tests check the cache is exact at the moment it is refreshed, that it is refreshed when (and only when) it should
be, and that a request never waits for what it cannot get quickly."""
from __future__ import annotations

import random
import uuid
from collections import Counter, defaultdict
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from database import async_session
from models.agent_insights import (
    AgentInsightKey, agent_insight_people_cache, agent_insight_users_daily, agent_insight_users_weekly,
)
from services import agent_insights_bus as bus_mod
from services import agent_insights_keys as keys
from services import agent_insights_people as people
from services import agent_insights_store as store
from services import agent_insights_summary as summary
from services.agent_insights_bus import MemoryBus
from tests.insights_stream_helpers import NOW, _dt, norm, random_events, turn

PID = uuid.UUID("ffffffff-1111-2222-3333-444444444444")


@pytest_asyncio.fixture
async def db(test_db):
    bus_mod.use_bus(None)
    async with async_session() as s:
        await keys.create_or_rotate(s, PID, None)
    yield
    bus_mod.reset_bus()


async def apply(events, now=NOW):
    async with async_session() as s, s.begin():
        return await store.apply_events(s, PID, norm(events, now), now=now)


async def cached_summary(range_="7d", now=NOW, **kw):
    async with async_session() as s:
        out = await summary.build_summary(s, PID, range_=range_, now=now, use_cache=True, **kw)
    assert out["ok"], out
    return out["insights"]


def brute_top(events, since_day, agent=None, role=None):
    per: Counter = Counter()
    seen = set()
    for e in events:
        if e["type"] != "turn" or e["id"] in seen:
            continue
        seen.add(e["id"])
        at = _dt(e["at"])
        if at.date() >= since_day and (agent is None or e["agentId"] == agent) and (role is None or (e["role"] or "") == role):
            per[e["userKey"]] += 1
    return sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))[:20]


@pytest.mark.asyncio
async def test_the_weekly_rows_are_the_daily_rows_added_up(db):
    events = random_events(random.Random(4), turns=300, users=30, hours=30, days_back=40)
    await apply(events[:150])
    await apply(events[100:])
    async with async_session() as s:
        daily = (await s.execute(select(agent_insight_users_daily))).all()
        weekly = (await s.execute(select(agent_insight_users_weekly))).all()
    want: dict[tuple, Counter] = defaultdict(Counter)
    for r in daily:
        c = want[(r.day - timedelta(days=r.day.weekday()), r.user_key)]
        for k in ("turns", "input_tokens", "output_tokens", "errors", "up", "down"):
            c[k] += getattr(r, k)
    assert {(r.week, r.user_key): {k: getattr(r, k) for k in ("turns", "input_tokens", "output_tokens", "errors", "up", "down")} for r in weekly} \
           == {k: dict(v) for k, v in want.items()}
    assert all(r.week.weekday() == 0 for r in weekly)


@pytest.mark.asyncio
async def test_the_top_list_equals_brute_force_from_any_starting_day_with_and_without_filters(db):
    events = random_events(random.Random(9), turns=500, users=40, hours=30, days_back=40)
    await apply(events)
    today = NOW.date()
    async with async_session() as s:
        for back in range(0, 30):                                 # every weekday as the first day of the window
            since_day = today - timedelta(days=back)
            for agent, role in ((None, None), ("support", None), (None, "Admin"), ("sales", "Agent")):
                got = await people.compute_top(s, PID, since_day, agent, role)
                assert [(u["userKey"], u["turns"]) for u in got] == brute_top(events, since_day, agent, role), (back, agent, role)


@pytest.mark.asyncio
async def test_a_request_with_no_cache_works_it_out_once_and_the_next_one_reads_it(db):
    await apply([turn(i, NOW - timedelta(minutes=5 + i), user=i % 6) for i in range(30)])
    first = await cached_summary("7d")
    assert first["users"]["topAsOf"] and len(first["users"]["top"]) == 6 and first["users"]["active"] == 6
    async with async_session() as s:
        row = (await s.execute(select(agent_insight_people_cache))).one()
    assert (row.agent_id, row.role, row.range) == ("*", "*", "7d") and row.payload["active"] == 6
    # more events arrive; with no refresh the page keeps the list it has and says when it was worked out
    await apply([turn(100 + i, NOW - timedelta(minutes=1), user=50 + i) for i in range(4)])
    second = await cached_summary("7d")
    assert second["users"]["active"] == 6 and second["users"]["topAsOf"] == first["users"]["topAsOf"]
    assert second["totals"]["turns"] == 34                       # the headline numbers are live; only the people block is as-of


@pytest.mark.asyncio
async def test_the_worker_refreshes_a_view_only_when_its_project_has_news_and_its_interval_has_passed(db):
    await apply([turn(i, NOW - timedelta(minutes=5), user=i) for i in range(5)])
    await cached_summary("24h")
    await cached_summary("30d")
    assert (await people.refresh_due(async_session, now=NOW + timedelta(seconds=40)))["refreshed"] == 0       # nothing new: left alone
    await apply([turn(99, NOW + timedelta(seconds=5), user=77)], now=NOW + timedelta(seconds=10))
    assert (await people.refresh_due(async_session, now=NOW + timedelta(seconds=20)))["refreshed"] == 0       # news, but 20 s < 30 s
    done = await people.refresh_due(async_session, now=NOW + timedelta(seconds=40))
    assert [v["range"] for v in done["views"]] == ["24h"]                                                     # the 5-minute view is not due yet
    fresh = await cached_summary("24h", now=NOW + timedelta(seconds=41))
    assert fresh["users"]["active"] == 6 and fresh["users"]["topAsOf"].startswith((NOW + timedelta(seconds=40)).strftime("%Y-%m-%dT%H:%M:%S"))
    assert (await people.refresh_due(async_session, now=NOW + timedelta(seconds=310)))["refreshed"] == 1      # the 30d view, five minutes on (the 24h one is only 270 s old)
    assert (await people.refresh_due(async_session, now=NOW + timedelta(seconds=320)))["refreshed"] == 0


@pytest.mark.asyncio
async def test_a_refreshed_list_equals_brute_force_for_each_view(db):
    events = random_events(random.Random(12), turns=400, users=35, hours=30, days_back=25)
    await apply(events)
    for range_ in ("1h", "24h", "7d", "30d", "90d"):
        await cached_summary(range_)
        await cached_summary(range_, agent_id="support", role="Admin")
    extra = [turn(5000 + i, NOW - timedelta(minutes=i), user=i % 35, role=["Admin", "Agent", "Manager", None][(i % 35) % 4]) for i in range(20)]
    await apply(extra, now=NOW + timedelta(minutes=1))
    done = await people.refresh_due(async_session, now=NOW + timedelta(minutes=2), force=True)
    assert done["refreshed"] == 10
    async with async_session() as s:
        rows = {(r.agent_id, r.role, r.range): r.payload for r in (await s.execute(select(agent_insight_people_cache))).all()}
    for (agent, role, range_), payload in rows.items():
        since = people.window_start(NOW + timedelta(minutes=2), range_)
        everything = events + extra
        assert [(u["userKey"], u["turns"]) for u in payload["top"]] == brute_top(everything, since.date(), None if agent == "*" else agent,
                                                                                None if role == "*" else role), (agent, role, range_)


@pytest.mark.asyncio
async def test_when_the_list_cannot_be_worked_out_quickly_the_request_answers_without_it_and_leaves_a_placeholder(db, monkeypatch):
    await apply([turn(i, NOW - timedelta(minutes=5), user=i % 4) for i in range(8)])
    real = people._bounded
    calls = []

    async def too_slow(db_, ms, work):
        calls.append(ms)
        return (False, None) if len(calls) == 2 else await real(db_, ms, work)      # the counts are quick, the top list is not

    monkeypatch.setattr(people, "_bounded", too_slow)
    ins = await cached_summary("30d")
    assert ins["users"]["top"] == [] and ins["users"]["topAsOf"] is None and ins["users"]["approximate"] is True and ins["exact"] is False
    assert ins["users"]["active"] == 4                                              # what could be counted still is
    assert calls == [people.REQUEST_TIMEOUT_MS, people.REQUEST_TOP_TIMEOUT_MS]
    async with async_session() as s:
        row = (await s.execute(select(agent_insight_people_cache))).one()
    assert row.payload is None and row.computed_at is None                          # a placeholder: the worker will fill it in
    monkeypatch.undo()
    assert (await people.refresh_due(async_session, now=NOW + timedelta(seconds=1)))["refreshed"] == 1
    assert len((await cached_summary("30d", now=NOW + timedelta(seconds=2)))["users"]["top"]) == 4


@pytest.mark.asyncio
async def test_a_list_the_worker_has_stopped_refreshing_is_not_trusted_forever(db):
    await apply([turn(1, NOW - timedelta(minutes=5), user=1)])
    await cached_summary("24h")
    await apply([turn(2, NOW - timedelta(minutes=4), user=2)])
    later = NOW + timedelta(seconds=people.REFRESH_SECONDS["24h"] * people.MAX_AGE_INTERVALS + 5)
    assert (await cached_summary("24h", now=later))["users"]["active"] == 2        # older than six intervals: worked out again


@pytest.mark.asyncio
async def test_a_view_nobody_has_asked_for_in_a_day_is_not_refreshed_and_is_dropped(db):
    await apply([turn(1, NOW - timedelta(minutes=5), user=1)])
    await cached_summary("24h")
    await apply([turn(2, NOW - timedelta(minutes=4), user=2)], now=NOW + timedelta(seconds=5))
    assert (await people.refresh_due(async_session, now=NOW + timedelta(days=1, minutes=1)))["refreshed"] == 0
    await store.housekeeping(async_session, now=NOW + timedelta(days=1, minutes=1))
    async with async_session() as s:
        assert (await s.execute(select(agent_insight_people_cache))).all() == []


@pytest.mark.asyncio
async def test_a_refresh_does_not_keep_an_abandoned_view_alive(db):
    await apply([turn(1, NOW - timedelta(minutes=5), user=1)])
    await cached_summary("24h")
    async with async_session() as s:
        before = (await s.execute(select(agent_insight_people_cache.c.wanted_at))).scalar()
    await people.refresh_due(async_session, now=NOW + timedelta(hours=3), force=True)
    async with async_session() as s:
        assert (await s.execute(select(agent_insight_people_cache.c.wanted_at))).scalar() == before


@pytest.mark.asyncio
async def test_apply_records_when_a_project_last_had_news(db):
    await apply([turn(1, NOW - timedelta(days=2))], now=NOW)             # an OLD event arriving now still counts as news
    async with async_session() as s:
        k = (await s.execute(select(AgentInsightKey))).scalar_one()
    assert store.aware(k.last_applied_at) == NOW and store.aware(k.last_event_at) == NOW - timedelta(days=2)



@pytest.mark.asyncio
async def test_the_live_people_count_is_a_merge_of_minute_counters_when_there_is_a_bus_and_is_flagged(db):
    bus = MemoryBus()
    bus_mod.use_bus(bus)
    events = [turn(i, NOW - timedelta(minutes=1, seconds=i), user=i % 9) for i in range(40)]
    async with async_session() as s, s.begin():
        res = await store.apply_events(s, PID, norm(events), now=NOW)
    await bus.hll_add(res.hll)
    live = (await cached_summary("24h"))["live"]
    assert live["activeUsers5m"] == 9


@pytest.mark.asyncio
async def test_the_per_hour_people_without_redis_never_scans_more_than_a_fixed_number_of_events(db, monkeypatch):
    monkeypatch.setattr(summary, "RAW_DISTINCT_MAX_TURNS", 5)
    await apply([turn(i, NOW - timedelta(minutes=30 + i), user=i) for i in range(12)])
    async with async_session() as s:
        ins = (await summary.build_summary(s, PID, range_="24h", now=NOW))["insights"]
    assert ins["users"]["approximate"] is True and ins["exact"] is False and all(p["activeUsers"] == 0 for p in ins["series"])


@pytest.mark.asyncio
async def test_the_load_tests_history_seeder_writes_exactly_the_rows_the_real_writer_writes(db):
    """The history seeder skips only the raw event rows and the problem feed: every counter table it fills must equal what apply_events makes."""
    import argparse
    from datetime import datetime, timezone

    from models.agent_insights import (
        MODEL_TABLES, ROLLUP_TABLES, TOOL_TABLES, agent_insight_active_daily, agent_insight_user_days, agent_insight_users,
    )
    from tools.insights_load_test import Generator, seed_history

    other = uuid.uuid4()
    now = datetime(2026, 10, 22, 12, 30, 30, tzinfo=timezone.utc)
    recorded: list = []
    args = argparse.Namespace(seed_history_days=6, users=60, daily_active=35, seed=3, seed_chunk=17)
    await seed_history(args, Generator(60, 3, 0.0, 0.0), other, now, async_session, store, record=recorded)
    assert len(recorded) > 150
    async with async_session() as s, s.begin():
        await store.apply_events(s, PID, recorded, now=now)
    tables = [*ROLLUP_TABLES.values(), *MODEL_TABLES.values(), *TOOL_TABLES.values(), agent_insight_users, agent_insight_users_daily,
              agent_insight_users_weekly, agent_insight_user_days, agent_insight_active_daily]
    async with async_session() as s:
        for t in tables:
            got = {}
            for pid in (PID, other):
                got[pid] = sorted(tuple(str(v) for k, v in r._mapping.items() if k != "project_id")
                                  for r in (await s.execute(select(t).where(t.c.project_id == pid))).all())
            assert got[PID] == got[other], t.name
            assert got[PID], t.name


@pytest.mark.asyncio
async def test_right_after_a_refresh_the_cached_summary_equals_the_one_counted_in_full(db):
    events = random_events(random.Random(31), turns=350, users=45, hours=30, days_back=25)
    await apply(events)
    for range_ in ("1h", "24h", "7d", "30d"):
        for agent, role in ((None, None), ("support", None), (None, "Admin")):
            await cached_summary(range_, agent_id=agent, role=role)
    await people.refresh_due(async_session, now=NOW, force=True)
    for range_ in ("1h", "24h", "7d", "30d"):
        for agent, role in ((None, None), ("support", None), (None, "Admin")):
            async with async_session() as s:
                full = (await summary.build_summary(s, PID, range_=range_, agent_id=agent, role=role, now=NOW))["insights"]
            cached = await cached_summary(range_, agent_id=agent, role=role)
            for ins in (full, cached):
                ins["users"].pop("topAsOf")
                ins.pop("generatedAt")
            assert cached == full, (range_, agent, role)

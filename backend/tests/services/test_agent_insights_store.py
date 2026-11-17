"""The writer: a batch becomes counters exactly once, whatever order it arrives in and however often it is re-sent."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from database import async_session
from models.agent_insights import (
    MODEL_TABLES, ROLLUP_TABLES, TOOL_TABLES, agent_insight_pending_ratings, agent_insight_problems, agent_insight_users,
    agent_insight_users_daily, agent_turn_events,
)
from services import agent_insights_bus as bus_mod
from services import agent_insights_store as store
from services import agent_insights_summary as summary
from tests.insights_stream_helpers import NOW, handoff, norm, rating, turn

PID = uuid.UUID("aaaaaaaa-1111-2222-3333-444444444444")


@pytest_asyncio.fixture
async def db(test_db):
    bus_mod.use_bus(None)  # no Redis: the plain database path
    yield
    bus_mod.reset_bus()


async def apply(events, *, pid=PID, now=NOW):
    async with async_session() as s, s.begin():
        return await store.apply_events(s, pid, norm(events, now), now=now)


async def get(range_="24h", *, agent=None, role=None, pid=PID, now=NOW):
    async with async_session() as s:
        out = await summary.build_summary(s, pid, range_=range_, agent_id=agent, role=role, now=now)
    assert out["ok"], out
    return out["insights"]


async def count(table, **where) -> int:
    async with async_session() as s:
        q = select(func.count()).select_from(table)
        for k, v in where.items():
            q = q.where(table.c[k] == v)
        return (await s.execute(q)).scalar()


def at(minutes_ago: float = 5):
    return NOW - timedelta(minutes=minutes_ago)


# --- exactly once -----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_same_batch_twice_gives_the_same_numbers(db):
    events = [turn(i, at(i + 1), user=i % 3, tools=[{"name": "refund", "ok": i % 2 == 0, "ms": 10}], status="error" if i % 4 == 0 else "ok",
                   problem={"reason": "error", "message": "x", "detail": None} if i % 4 == 0 else None) for i in range(20)]
    events += [rating(2, -1, at(0.5)), handoff("conv-9", "open", at(3))]
    first = await apply(events)
    before = await get()
    again = await apply(events)
    after = await get()
    assert first.new_turns == 20 and again.new_turns == 0 and again.duplicate_turns == 20
    before.pop("generatedAt"), after.pop("generatedAt")
    assert before == after
    assert after["totals"]["turns"] == 20 and after["totals"]["down"] == 1 and after["handoffs"]["total"] == 1
    assert await count(agent_turn_events) == 20
    assert await count(ROLLUP_TABLES["day"]) >= 1


@pytest.mark.asyncio
async def test_a_batch_that_fails_half_way_changes_nothing(db, monkeypatch):
    events = [turn(i, at(i + 1)) for i in range(5)]

    async def boom(*a, **k):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(store, "_flush", boom)
    with pytest.raises(RuntimeError):
        await apply(events)
    assert await count(agent_turn_events) == 0  # the raw rows were rolled back with the rest: a retry counts them
    monkeypatch.undo()
    assert (await apply(events)).new_turns == 5
    assert (await get())["totals"]["turns"] == 5


@pytest.mark.asyncio
async def test_two_projects_never_see_each_other(db):
    other = uuid.uuid4()
    await apply([turn(1, at(), user=1)])
    await apply([turn(1, at(), user=2), turn(2, at(), user=2)], pid=other)  # the same event id in another project is another event
    assert (await get())["totals"]["turns"] == 1
    assert (await get(pid=other))["totals"]["turns"] == 2


# --- late events -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_late_event_lands_in_the_bucket_it_happened_in_not_when_it_arrived(db):
    now_event = turn(1, at(2), inp=10)
    old = turn(2, NOW - timedelta(days=3, hours=5), inp=1000)        # three days old, arrives now
    await apply([now_event, old])
    day = ROLLUP_TABLES["day"]
    async with async_session() as s:
        rows = {r.bucket.date().isoformat(): r.input_tokens for r in (await s.execute(select(day.c.bucket, day.c.input_tokens))).all()}
    assert rows == {"2026-10-22": 10, "2026-10-19": 1000}
    # three days old is past the 48-hour minute rollups: no minute row is made for it
    assert await count(ROLLUP_TABLES["minute"]) == 1
    assert (await get("24h"))["totals"]["inputTokens"] == 10
    week = await get("7d")
    assert week["totals"]["inputTokens"] == 1010
    assert {d["day"]: d["inputTokens"] for d in week["byDay"]} == {"2026-10-22": 10, "2026-10-19": 1000}


@pytest.mark.asyncio
async def test_an_old_event_arriving_after_a_newer_one_moves_first_seen_back(db):
    await apply([turn(1, at(10), user=5)])
    await apply([turn(2, NOW - timedelta(days=2), user=5)])
    async with async_session() as s:
        r = (await s.execute(select(agent_insight_users))).one()
    assert (store.aware(r.first_seen_at), store.aware(r.last_seen_at)) == (NOW - timedelta(days=2), at(10))
    week = await get("7d")
    assert week["users"]["active"] == 1 and week["users"]["newUsers"] == 1 and week["users"]["returning"] == 0
    day = await get("24h")
    assert day["users"]["active"] == 1 and day["users"]["newUsers"] == 0 and day["users"]["returning"] == 1  # first seen two days ago


# --- ratings -----------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_rating_replaces_the_earlier_one_and_only_the_difference_is_counted(db):
    await apply([turn(1, at(30), user=1)])
    for value, n, up, down in [(1, 0, 1, 0), (-1, 1, 0, 1), (1, 2, 1, 0)]:   # (rating, its number, expected up, expected down)
        await apply([rating(1, value, at(25 - n), n=n)])
        t = (await get())["totals"]
        assert (t["up"], t["down"], t["rated"]) == (up, down, 1), (value, t)


@pytest.mark.asyncio
async def test_an_older_rating_that_arrives_late_does_not_undo_the_newer_one(db):
    await apply([turn(1, at(30))])
    await apply([rating(1, -1, at(20), n=1)])
    await apply([rating(1, 1, at(25), n=0)])            # given BEFORE the thumbs-down, delivered after it
    assert (await get())["totals"]["down"] == 1
    await apply([rating(1, -1, at(20), n=1)])           # and the same one twice
    t = (await get())["totals"]
    assert (t["up"], t["down"]) == (0, 1)


@pytest.mark.asyncio
async def test_two_ratings_for_one_turn_in_one_batch_count_the_latest_once(db):
    await apply([turn(1, at(30))])
    await apply([rating(1, 1, at(25), n=0), rating(1, -1, at(20), n=1)])
    t = (await get())["totals"]
    assert (t["up"], t["down"]) == (0, 1)


@pytest.mark.asyncio
async def test_a_rating_before_its_turn_is_held_and_applied_when_the_turn_arrives(db):
    await apply([rating(1, -1, at(4), note="wrong answer")])
    assert await count(agent_insight_pending_ratings) == 1
    await apply([turn(1, at(5), user=7)])
    assert await count(agent_insight_pending_ratings) == 0
    insights = await get()
    assert (insights["totals"]["down"], insights["totals"]["rated"]) == (1, 1)
    assert insights["problems"][0]["reason"] == "thumbs_down" and insights["problems"][0]["detail"] == "wrong answer"
    async with async_session() as s:
        raw = (await s.execute(select(agent_turn_events.c.rating, agent_turn_events.c.rating_note))).one()
    assert tuple(raw) == (-1, "wrong answer")


@pytest.mark.asyncio
async def test_the_newest_held_rating_wins_and_a_rating_in_the_same_batch_as_its_turn_works(db):
    await apply([rating(1, 1, at(8), n=0)])
    await apply([rating(1, -1, at(6), n=1)])
    await apply([rating(1, 1, at(7), n=2)])             # older than the held one: ignored
    await apply([turn(1, at(9))])
    assert (await get())["totals"]["down"] == 1
    await apply([rating(2, 1, at(3)), turn(2, at(4))])  # the rating listed before its turn, in one batch
    assert (await get())["totals"]["up"] == 1


@pytest.mark.asyncio
async def test_the_sweep_applies_a_rating_whose_turn_was_written_by_another_worker_a_moment_later(db):
    await apply([turn(1, at(5))])
    async with async_session() as s, s.begin():          # the state the race leaves: the turn exists AND its rating is held
        await s.execute(agent_insight_pending_ratings.insert().values(project_id=PID, turn_id="turn-00000001", rating=-1, at=at(4), note=None, received_at=NOW))
    assert await store.sweep_pending_ratings(async_session, now=NOW) == 1
    assert await count(agent_insight_pending_ratings) == 0
    assert (await get())["totals"]["down"] == 1


@pytest.mark.asyncio
async def test_a_rating_counts_in_its_turns_day_not_the_day_it_was_given(db):
    await apply([turn(1, NOW - timedelta(days=2, hours=1))])
    await apply([rating(1, 1, at(1))])
    week = await get("7d")
    days = {d["day"]: (d["up"], d["down"]) for d in week["byDay"]}
    assert days == {"2026-10-20": (1, 0)}
    assert (await get("24h"))["totals"]["up"] == 0


@pytest.mark.asyncio
async def test_a_rating_changes_the_users_daily_counters_too(db):
    await apply([turn(1, at(30), user=4), turn(2, at(29), user=4)])
    await apply([rating(1, -1, at(20)), rating(2, 1, at(20))])
    top = (await get())["users"]["top"][0]
    assert (top["turns"], top["thumbsDown"]) == (2, 1)


@pytest.mark.asyncio
async def test_a_thumbs_down_problem_goes_away_when_the_rating_changes_back_but_the_apps_own_problem_stays(db):
    await apply([turn(1, at(30)), turn(2, at(29), status="error", problem={"reason": "error", "message": "boom", "detail": None})])
    await apply([rating(1, -1, at(20), n=0), rating(2, -1, at(20), n=0)])
    assert {p["reason"] for p in (await get())["problems"]} == {"thumbs_down", "error"}
    await apply([rating(1, 1, at(10), n=1), rating(2, 1, at(10), n=1)])
    assert [p["reason"] for p in (await get())["problems"]] == ["error"]


# --- handoffs ----------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_handoff_moves_between_states_and_the_counters_follow(db):
    await apply([turn(1, at(30))])
    async def state():
        h = (await get())["handoffs"]
        return h["total"], h["open"], h["claimed"], h["resolved"], h["avgResolveMinutes"]

    await apply([handoff("conv-a", "open", at(20))])
    assert await state() == (1, 1, 0, 0, None)
    await apply([handoff("conv-a", "claimed", at(15))])
    assert await state() == (1, 0, 1, 0, None)
    await apply([handoff("conv-b", "open", at(14)), handoff("conv-a", "resolved", at(10), minutes=12.0)])
    assert await state() == (2, 1, 0, 1, 12.0)
    await apply([handoff("conv-a", "claimed", at(15)), handoff("conv-a", "open", at(20))])   # re-sent, out of date: nothing changes
    assert await state() == (2, 1, 0, 1, 12.0)


@pytest.mark.asyncio
async def test_handoff_events_in_any_order_end_in_the_same_state(db):
    events = [handoff("conv-a", "open", at(20)), handoff("conv-a", "claimed", at(15)), handoff("conv-a", "resolved", at(10), minutes=9.0)]
    await apply(list(reversed(events)))
    h = (await get())["handoffs"]
    assert (h["total"], h["open"], h["claimed"], h["resolved"], h["avgResolveMinutes"]) == (1, 0, 0, 1, 9.0)


# --- who is a new user -------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_and_returning_users_and_active_by_day(db):
    await apply([turn(1, NOW - timedelta(days=3), user=1), turn(2, at(30), user=1), turn(3, at(20), user=2), turn(4, at(10), user=2)])
    week = await get("7d")
    assert (week["users"]["active"], week["users"]["newUsers"], week["users"]["returning"]) == (2, 2, 0)
    day = await get("24h")
    assert (day["users"]["active"], day["users"]["newUsers"], day["users"]["returning"]) == (2, 1, 1)
    assert {d["day"]: d["active"] for d in week["users"]["activeByDay"]}["2026-10-19"] == 1


# --- the problems feed -------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_problems_feed_keeps_only_the_newest_per_project(db, monkeypatch):
    monkeypatch.setattr(store, "PROBLEMS_PER_PROJECT", 10)
    await apply([turn(i, NOW - timedelta(minutes=100 - i), status="error", problem={"reason": "error", "message": f"m{i}", "detail": None}) for i in range(25)])
    async with async_session() as s:
        kept = [r.turn_id for r in (await s.execute(select(agent_insight_problems.c.turn_id).order_by(agent_insight_problems.c.at))).all()]
    assert kept == [f"turn-{i:08d}" for i in range(15, 25)]
    feed = (await get())["problems"]
    assert feed[0]["message"] == "m24" and len(feed) == 10


# --- models, tools, errors --------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_models_tools_and_status_counts(db):
    await apply([
        turn(1, at(5), model="claude-sonnet-4-5", inp=1000, out=100, tools=[{"name": "refund", "ok": True, "ms": 100}, {"name": "refund", "ok": False, "ms": 300}]),
        turn(2, at(4), model="claude-haiku-4-5", inp=500, out=50, status="error"),
        turn(3, at(3), model=None, inp=0, out=0, status="blocked"),
    ])
    s = await get()
    assert (s["totals"]["errors"], s["totals"]["blocked"], s["totals"]["toolCalls"], s["totals"]["toolErrors"]) == (1, 1, 2, 1)
    assert {m["model"]: (m["turns"], m["inputTokens"]) for m in s["byModel"]} == {"claude-sonnet-4-5": (1, 1000), "claude-haiku-4-5": (1, 500)}
    assert s["tools"] == [{"name": "refund", "calls": 2, "errors": 1, "avgMs": 200, "failurePct": 50.0}]
    assert s["cost"]["estimatedUsd"] == pytest.approx((1000 * 3 + 100 * 15 + 500 * 1 + 50 * 5) / 1e6)


# --- retention ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retention_trims_minutes_after_48_hours_hours_after_90_days_and_keeps_the_rest(db):
    # written "now" (so every grain accepts them), then the clock moves on
    await apply([turn(1, at(5)), turn(2, NOW - timedelta(days=1, hours=1))])
    await apply([turn(3, NOW - timedelta(days=80))])
    assert await count(ROLLUP_TABLES["minute"]) == 2 and await count(ROLLUP_TABLES["hour"]) == 3 and await count(ROLLUP_TABLES["day"]) == 3

    await store.housekeeping(async_session, now=NOW + timedelta(days=1, hours=23))      # +47h: the 25-hour-old minute is 72h old: gone, the fresh one 47h: kept
    assert await count(ROLLUP_TABLES["minute"]) == 1
    assert await count(MODEL_TABLES["minute"]) == 1 and await count(TOOL_TABLES["minute"]) == 0
    await store.housekeeping(async_session, now=NOW + timedelta(days=11))                # the 80-day-old hour is now 91 days old
    assert await count(ROLLUP_TABLES["hour"]) == 2 and await count(ROLLUP_TABLES["day"]) == 3
    assert await count(ROLLUP_TABLES["minute"]) == 0


@pytest.mark.asyncio
async def test_retention_removes_raw_events_after_30_days_by_arrival_and_held_ratings_after_an_hour(db):
    await apply([turn(1, at(5)), rating(99, 1, at(2))])
    assert await count(agent_turn_events) == 1 and await count(agent_insight_pending_ratings) == 1
    done = await store.housekeeping(async_session, now=NOW + timedelta(minutes=61))
    assert done["held_ratings_expired"] == 1 and await count(agent_insight_pending_ratings) == 0 and await count(agent_turn_events) == 1
    await store.housekeeping(async_session, now=NOW + timedelta(days=31))
    assert await count(agent_turn_events) == 0
    # the counters outlive the raw rows: the day rollup is kept
    assert await count(ROLLUP_TABLES["day"]) == 1


@pytest.mark.asyncio
async def test_old_per_person_rows_are_dropped_after_120_days(db):
    await apply([turn(1, NOW - timedelta(days=85), user=3)])
    assert await count(agent_insight_users_daily) == 1
    await store.housekeeping(async_session, now=NOW + timedelta(days=36))     # the row is now 121 days old
    assert await count(agent_insight_users_daily) == 0 and await count(agent_insight_users) == 1


# --- shapes ------------------------------------------------------------------------------------------------------

def test_the_latency_histogram_finds_the_right_bucket_and_percentiles_stay_inside_it():
    from models.agent_insights import LATENCY_BUCKETS, LATENCY_EDGES_MS

    assert store.latency_bucket(0) == 0 and store.latency_bucket(50) == 0 and store.latency_bucket(51) == 1
    assert store.latency_bucket(10 ** 9) == LATENCY_BUCKETS - 1
    hist = [0] * LATENCY_BUCKETS
    for ms in (120, 130, 140, 900, 910):
        hist[store.latency_bucket(ms)] += 1
    assert 100 <= store.percentile_from_hist(hist, 0.5) <= 150
    assert 800 <= store.percentile_from_hist(hist, 0.95) <= 1000
    assert store.percentile_from_hist([0] * LATENCY_BUCKETS, 0.5) is None
    last = [0] * LATENCY_BUCKETS
    last[-1] = 3
    assert store.percentile_from_hist(last, 0.5) == LATENCY_EDGES_MS[-1]

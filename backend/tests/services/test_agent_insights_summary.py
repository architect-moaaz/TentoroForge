"""The summary against a brute-force answer: a random mix of turns, thumbs (some changed), handoffs and re-sent events is applied in
pieces, in a shuffled order and partly twice, and every number the page shows is compared with what looping over the raw events says."""
from __future__ import annotations

import random
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from database import async_session
from services import agent_insights_bus as bus_mod
from services import agent_insights_store as store
from services import agent_insights_summary as summary
from services.agent_insights_bus import MemoryBus
from tests.insights_stream_helpers import NOW, Truth, _dt, handoff, iso, norm, random_events, turn, window_start

PID = uuid.UUID("bbbbbbbb-1111-2222-3333-444444444444")


@pytest_asyncio.fixture
async def db(test_db):
    bus_mod.use_bus(None)
    yield
    bus_mod.reset_bus()


async def apply(events, pid=PID, now=NOW):
    async with async_session() as s, s.begin():
        return await store.apply_events(s, pid, norm(events, now), now=now)


async def get(range_="24h", *, agent=None, role=None, pid=PID):
    async with async_session() as s:
        return await summary.build_summary(s, pid, range_=range_, agent_id=agent, role=role, now=NOW)


def hist_of(turns):
    from models.agent_insights import LATENCY_BUCKETS

    h = [0] * LATENCY_BUCKETS
    for t in turns:
        h[store.latency_bucket(t["ms"])] += 1
    return h


def check(ins: dict, tr: Truth, range_: str, *, filtered: bool) -> None:
    t = ins["totals"]
    assert t["turns"] == tr.turns
    assert (t["errors"], t["blocked"], t["handedOff"], t["conversations"]) == (min(tr.errors, tr.turns), min(tr.blocked, tr.turns), min(tr.handed_off, tr.turns), min(tr.conversations, tr.turns))
    assert (t["inputTokens"], t["outputTokens"]) == (tr.input_tokens, tr.output_tokens)
    assert (t["toolCalls"], t["toolErrors"]) == (tr.tool_calls, tr.tool_errors)
    assert (t["up"], t["down"], t["rated"]) == (tr.up, tr.down, tr.up + tr.down)

    # latency: from the histogram, so it must equal the percentile of the same histogram built from the raw rows
    h = hist_of(tr.turns_list)
    assert ins["latencyMs"]["p50"] == store.percentile_from_hist(h, 0.5)
    assert ins["latencyMs"]["p95"] == store.percentile_from_hist(h, 0.95)
    if tr.turns:
        assert ins["latencyMs"]["avg"] == pytest.approx(sum(x["ms"] for x in tr.turns_list) / tr.turns, abs=1)
        true_p95 = sorted(x["ms"] for x in tr.turns_list)[min(tr.turns - 1, int(0.95 * tr.turns))]
        assert true_p95 / 1.6 <= ins["latencyMs"]["p95"] <= true_p95 * 1.6 + 60   # one bucket wide, no more

    # models (a model with no tokens is not a model to price: the page leaves it out) and tools
    want_models = {m: (c["turns"], c["in"], c["out"]) for m, c in tr.by_model.items() if c["in"] or c["out"]}
    assert {m["model"]: (m["turns"], m["inputTokens"], m["outputTokens"]) for m in ins["byModel"]} == want_models
    assert {x["name"]: (x["calls"], x["errors"]) for x in ins["tools"]} == {k: (c["calls"], c["errors"]) for k, c in tr.tools.items()}

    # the series: zero-filled, oldest first, adds up to the totals, and each point is its own bucket's truth
    grain = {"1h": "minute", "24h": "hour", "7d": "hour", "30d": "day", "90d": "day"}[range_]
    assert ins["granularity"] == grain and ins["mode"] == "stream" and ins["range"] == range_
    size = {"minute": 60, "hour": 3600, "day": 86400}[grain]
    pts = ins["series"]
    start, end = int(tr.since.timestamp()), int(NOW.timestamp()) // size * size
    assert [datetime.fromisoformat(p["t"].replace("Z", "+00:00")).timestamp() for p in pts] == list(range(start, end + 1, size))
    assert sum(p["turns"] for p in pts) == tr.turns and sum(p["errors"] for p in pts) == tr.errors
    assert sum(p["inputTokens"] for p in pts) == tr.input_tokens and sum(p["outputTokens"] for p in pts) == tr.output_tokens
    per_bucket = Counter(int(_dt(x["at"]).timestamp()) // size * size for x in tr.turns_list)
    users_per_bucket: dict[int, set] = defaultdict(set)
    for x in tr.turns_list:
        users_per_bucket[int(_dt(x["at"]).timestamp()) // size * size].add(x["userKey"])
    for p in pts:
        b = int(datetime.fromisoformat(p["t"].replace("Z", "+00:00")).timestamp())
        assert p["turns"] == per_bucket.get(b, 0), p["t"]
        if grain != "day" or not filtered:
            assert p["activeUsers"] == len(users_per_bucket.get(b, ())), p["t"]

    if range_ in ("7d", "30d", "90d"):
        assert {d["day"]: (d["turns"], d["inputTokens"], d["outputTokens"], d["errors"]) for d in ins["byDay"] if d["turns"]} == \
               {k: (c["turns"], c["in"], c["out"], c["errors"]) for k, c in tr.by_day.items()}
        assert sum(d["up"] for d in ins["byDay"]) == tr.up and sum(d["down"] for d in ins["byDay"]) == tr.down
    else:
        assert ins["byDay"] == []

    # roles
    roles = {r["role"]: (r["turns"]) for r in ins["users"]["byRole"]}
    assert roles == {(k or "(no role)"): c["turns"] for k, c in tr.by_role.items()}
    for r in ins["users"]["byRole"]:
        c = tr.by_role[("" if r["role"] == "(no role)" else r["role"])]
        assert r["thumbsDownPct"] == (round(100.0 * c["down"] / (c["up"] + c["down"]), 1) if c["up"] + c["down"] else None)

    # different people per day (a counter): exact for whole-day windows, with any filter
    if range_ in ("7d", "30d", "90d"):
        per_day: dict[str, set] = defaultdict(set)
        for x in tr.turns_list:
            per_day[_dt(x["at"]).date().isoformat()].add(x["userKey"])
        assert {d["day"]: d["active"] for d in ins["users"]["activeByDay"] if d["active"]} == {k: len(v) for k, v in per_day.items()}

    # people: exact when the window is whole days or nobody is filtered
    day_aligned = range_ in ("7d", "30d", "90d")
    if day_aligned or not filtered:
        assert ins["users"]["active"] == len(tr.users) == ins["totals"]["users"]
        top = sorted(tr.per_user.items(), key=lambda kv: (-kv[1]["turns"], kv[0]))[:20]
        if day_aligned:
            assert [(u["userKey"], u["turns"], u["inputTokens"], u["outputTokens"]) for u in ins["users"]["top"]] == \
                   [(k, c["turns"], c["in"], c["out"]) for k, c in top]

    # handoffs (the role filter does not apply to them)
    hf = ins["handoffs"]
    assert (hf["total"], hf["open"], hf["claimed"], hf["resolved"]) == (tr.handoffs["total"], tr.handoffs["open"], tr.handoffs["claimed"], tr.handoffs["resolved"])
    assert hf["avgResolveMinutes"] == (pytest.approx(tr.avg_resolve, abs=0.06) if tr.avg_resolve is not None else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", [11, 22, 33])
async def test_the_summary_equals_a_brute_force_count_for_every_range_and_filter(db, seed):
    rng = random.Random(seed)
    events = random_events(rng, turns=320, users=40, hours=40, days_back=25)
    pieces = [events[i::3] for i in range(3)]
    for piece in pieces:
        await apply(piece)
    await apply(pieces[0])          # delivered twice
    await apply(pieces[2][:50])     # and a part of another one again

    for range_ in ("1h", "24h", "7d", "30d"):
        for agent, role in ((None, None), ("support", None), (None, "Admin"), ("sales", "(no role)")):
            out = await get(range_, agent=agent, role=role)
            assert out["ok"], out
            truth = Truth(events, NOW, range_, agent, "" if role == "(no role)" else role)
            check(out["insights"], truth, range_, filtered=bool(agent or role))
    # and the same, written the other way round and in one go, gives the same numbers
    other = uuid.uuid4()
    await apply(list(reversed(events)), pid=other)
    a, b = (await get("7d"))["insights"], (await get("7d", pid=other))["insights"]
    for x in (a, b):
        x.pop("generatedAt")
    assert a == b


@pytest.mark.asyncio
async def test_zero_filled_range_and_no_data_messages(db):
    from services import agent_insights_keys as keys

    out = await get("24h")
    assert out == {"ok": False, "reason": "No key yet: create one on this page and add it to your app, then its first chats appear here within seconds."}
    async with async_session() as s:
        await keys.create_or_rotate(s, PID, None)
    out = await get("24h")
    assert out["ok"] is False and out["reason"].startswith("No events yet")
    await apply([turn(1, NOW - timedelta(days=20))])
    h = (await get("24h"))["insights"]            # there are events, but none in the last day: zeros, not an error
    assert h["totals"]["turns"] == 0 and len(h["series"]) == 25 and all(p["turns"] == 0 for p in h["series"])
    assert h["tips"][0]["id"] == "no-data" and h["freshness"]["lastEventAt"] == iso(NOW - timedelta(days=20))
    month = (await get("30d"))["insights"]
    assert month["totals"]["turns"] == 1 and len(month["series"]) == 31 and sum(p["turns"] for p in month["series"]) == 1


@pytest.mark.asyncio
async def test_a_bad_range_is_a_plain_sentence(db):
    async with async_session() as s:
        out = await summary.build_summary(s, PID, range_="5y", now=NOW)
    assert out["ok"] is False and "1h, 24h, 7d, 30d or 90d" in out["reason"]


@pytest.mark.asyncio
async def test_top_twenty_users_and_top_twelve_roles(db):
    events, i = [], 0
    for u in range(30):                                  # user u sends u+1 turns
        for _ in range(u + 1):
            events.append(turn(i, NOW - timedelta(minutes=30 + i % 20), user=u, role=f"role-{u}"))
            i += 1
    await apply(events)
    ins = (await get("7d"))["insights"]
    top = ins["users"]["top"]
    assert len(top) == 20 and [u["turns"] for u in top] == list(range(30, 10, -1))
    assert top[0]["userKey"] == f"{29:032x}" and top[0]["role"] == "role-29"
    roles = ins["users"]["byRole"]
    assert len(roles) == 12 and roles[0]["role"] == "role-29" and roles[0]["users"] == 1 and roles[0]["turns"] == 30
    assert ins["users"]["active"] == 30


@pytest.mark.asyncio
async def test_freshness_live_numbers_and_the_series_money(db):
    from services import agent_insights_keys as keys

    async with async_session() as s:
        await keys.create_or_rotate(s, PID, None)
    events = [turn(i, NOW - timedelta(seconds=40 * i), user=i % 5, ms=1000 if i % 2 else 100, status="error" if i == 1 else "ok",
                   inp=1000, out=100) for i in range(30)]          # every 40 s for 20 minutes: 7 turns in each last 5 minutes... checked below
    await apply(events)
    ins = (await get("1h"))["insights"]
    last = max(_dt(e["at"]) for e in events)
    assert ins["freshness"]["lastEventAt"] == iso(last) and ins["freshness"]["lagSeconds"] == (NOW - last).total_seconds()
    five = [e for e in events if _dt(e["at"]) >= store.bucket_dt((NOW - timedelta(minutes=4)).timestamp(), "minute")]
    live = ins["live"]
    assert live["turnsPerMinute"] == round(len(five) / 5, 1)
    assert live["activeUsers5m"] == len({e["userKey"] for e in events if _dt(e["at"]) >= NOW - timedelta(minutes=5)})
    assert live["errorRatePct5m"] == round(100.0 * sum(e["status"] == "error" for e in five) / len(five), 1)
    assert 100 <= live["p95Ms5m"] <= 1500
    # money per point: tokens at the models' average price (here one model, so exact)
    point = next(p for p in ins["series"] if p["turns"] > 1)
    assert point["usd"] == pytest.approx((point["inputTokens"] * 3 + point["outputTokens"] * 15) / 1e6, rel=1e-3)
    assert ins["freshness"]["lagSeconds"] >= 0


@pytest.mark.asyncio
async def test_the_chart_under_the_headline_uses_the_distinct_counters_when_there_is_a_bus_and_says_so(db):
    bus = MemoryBus()
    bus_mod.use_bus(bus)
    events = [turn(i, NOW - timedelta(minutes=10 * (i % 6)), user=i % 7) for i in range(40)]
    async with async_session() as s, s.begin():
        res = await store.apply_events(s, PID, norm(events), now=NOW)
    await bus.hll_add(res.hll)
    ins = (await get("24h"))["insights"]
    assert ins["users"]["approximate"] is True and ins["exact"] is False
    assert sum(p["activeUsers"] for p in ins["series"]) >= 7
    assert max(p["activeUsers"] for p in ins["series"]) == 7
    assert ins["users"]["active"] == 7                     # the headline is still the exact count
    bus_mod.use_bus(None)
    ins = (await get("24h"))["insights"]
    assert ins["users"]["approximate"] is False and ins["exact"] is True and max(p["activeUsers"] for p in ins["series"]) == 7


@pytest.mark.asyncio
async def test_the_role_filter_leaves_handoffs_alone_and_no_role_is_a_role(db):
    await apply([turn(1, NOW - timedelta(minutes=5), role=None, user=1), turn(2, NOW - timedelta(minutes=4), role="Admin", user=2),
                 handoff("conv-1", "open", NOW - timedelta(minutes=3))])
    ins = (await get("24h", role="(no role)"))["insights"]
    assert ins["totals"]["turns"] == 1 and ins["handoffs"]["total"] == 1 and ins["users"]["byRole"][0]["role"] == "(no role)"
    assert (await get("24h", role="Nobody"))["insights"]["totals"]["turns"] == 0


@pytest.mark.asyncio
async def test_window_edges_are_whole_buckets(db):
    # 24h starts at the top of an hour; an event just before it is outside, one just after is inside
    start = window_start(NOW, "24h")
    await apply([turn(1, start - timedelta(seconds=1)), turn(2, start + timedelta(seconds=1))])
    ins = (await get("24h"))["insights"]
    assert ins["totals"]["turns"] == 1 and ins["since"] == iso(start) and ins["series"][0]["t"] == iso(start)

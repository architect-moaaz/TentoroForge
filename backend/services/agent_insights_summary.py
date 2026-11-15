"""What the Insights page asks for: a summary built ONLY from the rollup tables, so it costs the same however many turns happened.

The numbers are added up from counters (turns, tokens, errors, thumbs, latency histograms) for the buckets inside the range. The v1
"raw" shape the page already understands is built from them and passed through ``services.agent_insights.enrich`` (cost, quality,
tips), then the stream-only extras are added: granularity, freshness, live strip, series, users.

Windows start on a bucket edge (a 24-hour view starts at the top of an hour, a 7-day view at midnight UTC) so a sum of buckets is exactly
what is shown and nothing is half counted. ``since`` says where the window really starts.

What costs what on the request:
* the headline numbers, series, models, tools, roles, handoffs and per-day people are sums over the rollup buckets of the range, or one
  counter per day: their cost follows the NUMBER OF BUCKETS (at most a few hundred), not users or turns;
* the people numbers that cannot be added from counters (the top list, different people in the window, new and returning, people per role)
  are read from the worker's cache by key (``agent_insights_people``), with ``users.topAsOf`` saying when they were worked out. A request
  that finds no usable row works them out once inside a short statement timeout and, if that is too slow, answers without them
  (empty top list, ``topAsOf`` null, flagged approximate) and leaves a placeholder for the worker;
* the people-per-hour chart and the live strip's people use HyperLogLog counters in Redis (one merge of a few keys); with no Redis they
  are counted from the person table or the raw events up to a fixed cap and flagged approximate beyond it.

Where the exactness stops, and what the page is told:
* the people numbers are exact as of ``topAsOf``; for a view shorter than a day the per-day figures and the top list cover whole UTC days
  (``users.dayAligned``);
* the people-per-hour chart and the live people count are HyperLogLog (error under 1%): ``users.approximate`` and ``exact: false``;
* the handoff statuses ignore the role filter (a handoff belongs to a conversation, not to a role).
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from typing import Any

from sqlalchemy import and_, distinct, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_insights import (
    COUNTER_COLUMNS, LATENCY_COLUMNS, MODEL_TABLES, ROLLUP_TABLES, TOOL_TABLES, AgentInsightKey, agent_insight_dropped,
    agent_insight_active_daily, agent_insight_problems, agent_insight_users, agent_insight_users_daily, agent_turn_events,
)
from services import agent_insights as v1
from services import agent_insights_bus as bus_mod
from services import agent_insights_keys as keys
from services import agent_insights_people as people_mod
from services.agent_insights_store import BUCKET_SECONDS, aware, bucket_dt, floor_ts, hll_key, percentile_from_hist, utcnow

#: range -> (length, granularity of the series, days to tell `enrich` about)
RANGES: dict[str, tuple[timedelta, str, int]] = {
    "1h": (timedelta(hours=1), "minute", 1),
    "24h": (timedelta(hours=24), "hour", 1),
    "7d": (timedelta(days=7), "hour", 7),
    "30d": (timedelta(days=30), "day", 30),
    "90d": (timedelta(days=90), "day", 90),
}
NO_ROLE = "(no role)"
TOP_USERS = 20
TOP_ROLES = 12
#: Without Redis, the people-per-hour chart is counted from the raw events only up to this many turns in the range.
RAW_DISTINCT_MAX_TURNS = 20_000

_SUM_COLUMNS = (*COUNTER_COLUMNS, "handoff_resolve_min_sum")


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return aware(dt).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _window(now: datetime, range_: str) -> tuple[datetime, str]:
    length, grain, _days = RANGES[range_]
    edge = "day" if range_ in ("7d", "30d", "90d") else grain
    return bucket_dt((now - length).timestamp(), edge), grain


def _sums(table, *names: str):
    return [func.coalesce(func.sum(table.c[n]), 0).label(n) for n in names]


def _pct(count: float, of: float) -> float | None:
    return round(100.0 * count / of, 1) if of > 0 else None


def _avg_price(models: list[dict[str, Any]]) -> tuple[float, float] | None:
    """Dollars per million tokens (in, out) averaged over the models used, weighted by tokens; None when any used model has no price
    (the same rule ``enrich`` uses for a day's cost), so a figure is never made up."""
    table = v1.price_table()
    prices = []
    for m in models:
        p = v1.price_for(m["model"], table)
        if p is None:
            return None
        prices.append((m, p))
    if not prices:
        return None
    tin, tout = sum(m["inputTokens"] for m, _ in prices), sum(m["outputTokens"] for m, _ in prices)
    pin = sum(m["inputTokens"] * p[0] for m, p in prices) / tin if tin else 0.0
    pout = sum(m["outputTokens"] * p[1] for m, p in prices) / tout if tout else 0.0
    return pin, pout


def _usd(tokens_in: int, tokens_out: int, price: tuple[float, float] | None, *, any_tokens: bool) -> float | None:
    if price is None:
        return None if any_tokens else 0.0
    return round((tokens_in * price[0] + tokens_out * price[1]) / 1_000_000, 6)


async def build_summary(db: AsyncSession, project_id: uuid.UUID, *, range_: str = "24h", agent_id: str | None = None,
                        role: str | None = None, now: datetime | None = None, use_cache: bool = False) -> dict[str, Any]:
    """``{"ok": True, "insights": ...}`` or ``{"ok": False, "reason": <one plain sentence>}``. ``use_cache`` reads the people numbers (top users,
    different people, people per role) from the worker's cache, as the route does; off, they are counted here, in full (exact, and as slow
    as there are people: for tests and small apps)."""
    if range_ not in RANGES:
        return {"ok": False, "reason": "The range must be one of 1h, 24h, 7d, 30d or 90d."}
    now = now or utcnow()
    agent_id = (agent_id or "").strip() or None
    role = None if role is None or not role.strip() else ("" if role.strip() == NO_ROLE else role.strip())
    _length, grain, days = RANGES[range_]
    since, grain = _window(now, range_)

    day_t = ROLLUP_TABLES["day"]
    has_data = (await db.execute(select(day_t.c.bucket).where(day_t.c.project_id == project_id).limit(1))).first() is not None
    if not has_data:
        if await keys.active_key(db, project_id) is None:
            return {"ok": False, "reason": "No key yet: create one on this page and add it to your app, then its first chats appear here within seconds."}
        return {"ok": False, "reason": "No events yet: the key is ready, but your app has not sent anything. Talk to the assistant in the app and check again in a few seconds."}

    await _flush_local()

    t, mt, tt = ROLLUP_TABLES[grain], MODEL_TABLES[grain], TOOL_TABLES[grain]

    def where(table, *, with_role: bool = True, since_: datetime = since):
        cond = [table.c.project_id == project_id, table.c.bucket >= since_]
        if agent_id:
            cond.append(table.c.agent_id == agent_id)
        if with_role and role is not None:
            cond.append(table.c.role == role)
        return and_(*cond)

    # --- headline counters, one row per bucket -----------------------------------------------------------------
    rows = (await db.execute(select(t.c.bucket, *_sums(t, *_SUM_COLUMNS)).where(where(t)).group_by(t.c.bucket).order_by(t.c.bucket))).all()
    by_bucket = {aware(r.bucket): r for r in rows}
    tot = {c: sum(float(getattr(r, c)) for r in rows) for c in _SUM_COLUMNS}
    turns = int(tot["turns"])
    hist = [int(tot[c]) for c in LATENCY_COLUMNS]

    # --- models, tools, roles ------------------------------------------------------------------------------------
    mrows = (await db.execute(select(mt.c.role, mt.c.model, *_sums(mt, "turns", "input_tokens", "output_tokens"))
                              .where(where(mt)).group_by(mt.c.role, mt.c.model))).all()
    models: dict[str, dict[str, Any]] = {}
    role_models: dict[str, dict[str, dict[str, int]]] = {}
    for r in mrows:
        name = r.model or "unknown"
        m = models.setdefault(name, {"model": name, "turns": 0, "inputTokens": 0, "outputTokens": 0})
        m["turns"] += int(r.turns)
        m["inputTokens"] += int(r.input_tokens)
        m["outputTokens"] += int(r.output_tokens)
        rm = role_models.setdefault(r.role, {}).setdefault(name, {"model": name, "inputTokens": 0, "outputTokens": 0})
        rm["inputTokens"] += int(r.input_tokens)
        rm["outputTokens"] += int(r.output_tokens)
    trows = (await db.execute(select(tt.c.tool, *_sums(tt, "calls", "errors", "ms_sum")).where(where(tt)).group_by(tt.c.tool)
                              .order_by(func.sum(tt.c.calls).desc()).limit(50))).all()
    tools = [{"name": r.tool, "calls": int(r.calls), "errors": int(r.errors), "avgMs": (int(r.ms_sum) / int(r.calls)) if int(r.calls) else None} for r in trows]
    role_rows = (await db.execute(select(t.c.role, *_sums(t, "turns", "input_tokens", "output_tokens", "up", "down"))
                                  .where(where(t)).group_by(t.c.role))).all()

    # --- by day (the v1 charts), problems, handoffs --------------------------------------------------------------
    by_day: list[dict[str, Any]] = []
    if range_ in ("7d", "30d", "90d"):
        if grain == "day":
            day_rows = rows
        else:
            day_rows = (await db.execute(select(day_t.c.bucket, *_sums(day_t, "turns", "input_tokens", "output_tokens", "errors", "up", "down"))
                                         .where(where(day_t)).group_by(day_t.c.bucket).order_by(day_t.c.bucket))).all()
        by_day = [{"day": aware(r.bucket).date().isoformat(), "turns": int(r.turns), "inputTokens": int(r.input_tokens),
                   "outputTokens": int(r.output_tokens), "errors": int(r.errors), "up": int(r.up), "down": int(r.down)} for r in day_rows]
    pc = [agent_insight_problems.c.project_id == project_id, agent_insight_problems.c.at >= since]
    if agent_id:
        pc.append(agent_insight_problems.c.agent_id == agent_id)
    if role is not None:
        pc.append(agent_insight_problems.c.role == role)
    problems = [{"conversationId": r.conversation_id, "at": _iso(r.at), "message": r.message or "", "reason": r.reason, "detail": r.detail or ""}
                for r in (await db.execute(select(agent_insight_problems).where(and_(*pc))
                                           .order_by(agent_insight_problems.c.at.desc()).limit(50))).all()]
    hc = [t.c.project_id == project_id, t.c.bucket >= since, t.c.role == ""]
    if agent_id:
        hc.append(t.c.agent_id == agent_id)
    h = (await db.execute(select(*_sums(t, "handoff_total", "handoff_open", "handoff_claimed", "handoff_resolved", "handoff_resolve_n",
                                        "handoff_resolve_min_sum")).where(and_(*hc)))).one()
    handoffs = {"total": int(h.handoff_total), "open": int(h.handoff_open), "claimed": int(h.handoff_claimed),
                "resolved": int(h.handoff_resolved),
                "avgResolveMinutes": (float(h.handoff_resolve_min_sum) / int(h.handoff_resolve_n)) if int(h.handoff_resolve_n) else None}

    # --- people --------------------------------------------------------------------------------------------------
    people = await people_mod.for_summary(db, project_id, range_, since, now, agent_id, role, use_cache=use_cache)
    users = {**people, "activeByDay": await _active_by_day(db, project_id, since, now, agent_id, role)}

    raw = {
        "generatedAt": _iso(now), "days": days, "agentId": agent_id, "since": _iso(since),
        "firstTurnAt": _iso((await db.execute(select(agent_insight_users.c.first_seen_at).where(agent_insight_users.c.project_id == project_id)
                                              .order_by(agent_insight_users.c.first_seen_at).limit(1))).scalar()),
        "totals": {"conversations": int(tot["conversations"]), "turns": turns, "users": users["active"],
                   "inputTokens": int(tot["input_tokens"]), "outputTokens": int(tot["output_tokens"]),
                   "toolCalls": int(tot["tool_calls"]), "toolErrors": int(tot["tool_errors"]), "blocked": int(tot["blocked"]),
                   "errors": int(tot["errors"]), "handedOff": int(tot["handed_off"]), "rated": int(tot["up"] + tot["down"]),
                   "up": int(tot["up"]), "down": int(tot["down"])},
        "latencyMs": {"p50": percentile_from_hist(hist, 0.5), "p95": percentile_from_hist(hist, 0.95),
                      "avg": (tot["ms_sum"] / turns) if turns else None},
        "byDay": by_day,
        "byModel": sorted(models.values(), key=lambda m: -m["turns"]),
        "tools": tools, "problems": problems, "handoffs": handoffs,
    }
    out = v1.enrich(raw, days)

    # --- the stream-only extras ----------------------------------------------------------------------------------
    price = _avg_price(out["cost"]["byModel"])
    any_tokens = raw["totals"]["inputTokens"] + raw["totals"]["outputTokens"] > 0
    active_by_bucket, approximate = await _active_per_bucket(db, project_id, grain, since, now, agent_id, role, by_bucket, users, turns)
    series = []
    size = BUCKET_SECONDS[grain]
    ts = floor_ts(since.timestamp(), grain)
    end = floor_ts(now.timestamp(), grain)
    while ts <= end:
        b = datetime.fromtimestamp(ts, timezone.utc)
        r = by_bucket.get(b)
        i, o = (int(r.input_tokens), int(r.output_tokens)) if r else (0, 0)
        series.append({"t": _iso(b), "turns": int(r.turns) if r else 0, "errors": int(r.errors) if r else 0, "inputTokens": i,
                       "outputTokens": o, "usd": _usd(i, o, price, any_tokens=bool(i or o)), "activeUsers": active_by_bucket.get(ts, 0)})
        ts += size

    by_role = []
    for r in sorted(role_rows, key=lambda r: (-int(r.turns), r.role))[:TOP_ROLES]:
        rmodels = list(role_models.get(r.role, {}).values())
        table = v1.price_table()
        if rmodels and all(v1.price_for(m["model"], table) for m in rmodels):
            # exact per model, not at the average price
            usd = round(sum(v1._usd(m["inputTokens"], m["outputTokens"], v1.price_for(m["model"], table)) for m in rmodels), 6)
        else:
            usd = 0.0 if not (int(r.input_tokens) or int(r.output_tokens)) else None
        by_role.append({"role": r.role or NO_ROLE, "users": users["roleUsers"].get(r.role, 0), "turns": int(r.turns), "usd": usd,
                        "thumbsDownPct": _pct(int(r.down), int(r.up) + int(r.down))})
    top = [{"userKey": u["userKey"], "role": u["role"] or None, "turns": u["turns"], "inputTokens": u["inputTokens"],
            "outputTokens": u["outputTokens"], "usd": _usd(u["inputTokens"], u["outputTokens"], price, any_tokens=bool(u["inputTokens"] or u["outputTokens"])),
            "errors": u["errors"], "thumbsDown": u["thumbsDown"], "lastSeenAt": u["lastSeenAt"]} for u in users["top"]]

    last_event = (await db.execute(select(func.max(AgentInsightKey.last_event_at)).where(AgentInsightKey.project_id == project_id))).scalar()
    last_event = aware(last_event)
    dropped = (await db.execute(select(func.coalesce(func.sum(agent_insight_dropped.c.rejected + agent_insight_dropped.c.rate_limited), 0))
                                .where(and_(agent_insight_dropped.c.project_id == project_id,
                                            agent_insight_dropped.c.hour >= bucket_dt(since.timestamp(), "hour"))))).scalar()

    live, live_approx = await _live(db, project_id, now, agent_id, role)
    approximate = approximate or people["partial"]
    out.update({
        "mode": "stream", "range": range_, "granularity": grain, "since": _iso(since), "until": _iso(now),
        "freshness": {"lastEventAt": _iso(last_event), "lagSeconds": max(0.0, round((now - last_event).total_seconds(), 1)) if last_event else None},
        "exact": not (approximate or live_approx), "droppedEvents": int(dropped or 0),
        "live": live,
        "series": series,
        "users": {"active": users["active"], "newUsers": users["new"], "returning": max(0, users["active"] - users["new"]),
                  "approximate": approximate, "dayAligned": range_ in ("1h", "24h"),
                  "activeByDay": users["activeByDay"], "byRole": by_role, "top": top, "topAsOf": people["topAsOf"]},
    })
    return {"ok": True, "insights": out}


async def _flush_local() -> None:
    """Counts this process is still holding in memory (events turned away) are written first, so the page never lags its own backend."""
    from services import agent_insights_ingest as ingest

    try:
        await ingest.DROPPED.flush()
        await keys.flush_touches()
    except Exception:  # noqa: BLE001 — the summary is still right apart from the last few seconds of these two counts
        pass


async def _active_by_day(db: AsyncSession, pid: uuid.UUID, since: datetime, now: datetime, agent_id: str | None, role: str | None) -> list[dict[str, Any]]:
    """Different people per day: one counter per (agent or all, role or all, day), so this reads one row per day."""
    ad = agent_insight_active_daily
    per_day = {r.day: int(r.users) for r in (await db.execute(select(ad.c.day, ad.c.users).where(and_(
        ad.c.project_id == pid, ad.c.day >= since.date(), ad.c.agent_id == (agent_id or "*"), ad.c.role == ("*" if role is None else role))))).all()}
    days, d = [], since.date()
    while d <= now.date():
        days.append({"day": d.isoformat(), "active": per_day.get(d, 0)})
        d += timedelta(days=1)
    return days


async def _active_per_bucket(db: AsyncSession, pid: uuid.UUID, grain: str, since: datetime, now: datetime, agent_id: str | None,
                             role: str | None, by_bucket: dict, users: dict[str, Any], turns: int) -> tuple[dict[int, int], bool]:
    """People per bucket for the series: ({bucket epoch: count}, approximate)."""
    if grain == "day":
        return {int(datetime.combine(date.fromisoformat(d["day"]), dtime.min, tzinfo=timezone.utc).timestamp()): d["active"]
                for d in users["activeByDay"]}, False
    if not by_bucket:
        return {}, False
    bus = await bus_mod.get_bus()
    if bus is not None:
        t = ROLLUP_TABLES[grain]
        cond = [t.c.project_id == pid, t.c.bucket >= since]
        if agent_id:
            cond.append(t.c.agent_id == agent_id)
        if role is not None:
            cond.append(t.c.role == role)
        combos = (await db.execute(select(t.c.bucket, t.c.agent_id, t.c.role).where(and_(*cond)).where(t.c.turns > 0))).all()
        per: dict[int, list[str]] = {}
        for r in combos:
            b = int(aware(r.bucket).timestamp())
            per.setdefault(b, []).append(hll_key(str(pid), r.agent_id, r.role, grain, b))
        order = sorted(per)
        try:
            counts = await bus.hll_counts([per[b] for b in order])
            return dict(zip(order, counts)), True
        except Exception:  # noqa: BLE001 — Redis went away between the two calls: fall through to the database
            await bus_mod.drop_bus()
    if turns > RAW_DISTINCT_MAX_TURNS:
        return {}, True
    raw = agent_turn_events
    sqlite = db.get_bind().dialect.name != "postgresql"
    fmt = "%Y-%m-%d %H:00:00" if grain == "hour" else "%Y-%m-%d %H:%M:00"
    # (Postgres cuts an hour in the SERVER's time zone, which is not always whole hours from UTC: cut in UTC)
    bucket_expr = func.strftime(fmt, raw.c.at) if sqlite else func.date_trunc(grain, func.timezone("UTC", raw.c.at))
    cond = [raw.c.project_id == pid, raw.c.at >= since]
    if agent_id:
        cond.append(raw.c.agent_id == agent_id)
    if role is not None:
        cond.append(raw.c.role == role)
    out: dict[int, int] = {}
    for r in (await db.execute(select(bucket_expr.label("b"), func.count(distinct(raw.c.user_key)).label("n")).where(and_(*cond)).group_by(bucket_expr))).all():
        b = datetime.strptime(r.b, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if isinstance(r.b, str) else aware(r.b)
        out[int(b.timestamp())] = int(r.n)
    return out, False


async def _live(db: AsyncSession, pid: uuid.UUID, now: datetime, agent_id: str | None, role: str | None) -> tuple[dict[str, Any], bool]:
    """The last five minutes: how busy, how many people, how many replies fail, how slow. Returns (numbers, people counted approximately).
    The people count is five minute-counters merged in Redis (error under 1%), so it costs the same at any traffic; with no Redis it is
    counted from the person table or the raw events, capped to a fixed amount of work."""
    t = ROLLUP_TABLES["minute"]
    start = bucket_dt(now.timestamp() - 4 * 60, "minute")
    cond = [t.c.project_id == pid, t.c.bucket >= start]
    if agent_id:
        cond.append(t.c.agent_id == agent_id)
    if role is not None:
        cond.append(t.c.role == role)
    r = (await db.execute(select(*_sums(t, "turns", "errors", *LATENCY_COLUMNS)).where(and_(*cond)))).one()
    turns = int(r.turns)
    people, approx = 0, False
    bus = await bus_mod.get_bus()
    if bus is not None and turns:
        combos = (await db.execute(select(t.c.bucket, t.c.agent_id, t.c.role).where(and_(*cond)).where(t.c.turns > 0))).all()
        try:
            people = (await bus.hll_counts([[hll_key(str(pid), c.agent_id, c.role, "minute", int(aware(c.bucket).timestamp())) for c in combos]]))[0]
            approx = True
        except Exception:  # noqa: BLE001
            await bus_mod.drop_bus()
            bus = None
    if bus is None and turns:
        if agent_id is None and role is None:
            u = agent_insight_users
            capped = select(literal(1)).select_from(u).where(and_(u.c.project_id == pid, u.c.last_seen_at >= now - timedelta(minutes=5))).limit(50_000).subquery()
            people = (await db.execute(select(func.count()).select_from(capped))).scalar() or 0
            approx = people >= 50_000
        elif turns <= RAW_DISTINCT_MAX_TURNS:
            raw = agent_turn_events
            rc = [raw.c.project_id == pid, raw.c.at >= now - timedelta(minutes=5)]
            if agent_id:
                rc.append(raw.c.agent_id == agent_id)
            if role is not None:
                rc.append(raw.c.role == role)
            people = (await db.execute(select(func.count(distinct(raw.c.user_key))).where(and_(*rc)))).scalar() or 0
        else:
            people, approx = min(turns, 50_000), True           # an upper bound, said so
    return ({"turnsPerMinute": round(turns / 5, 1), "activeUsers5m": int(people), "errorRatePct5m": _pct(int(r.errors), turns),
             "p95Ms5m": percentile_from_hist([int(getattr(r, c)) for c in LATENCY_COLUMNS], 0.95)}, approx)

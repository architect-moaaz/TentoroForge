"""The people half of the insights summary: top users, how many different people (new and returning), people per role.

These cannot be added up from counters the way turns and tokens can (a person active on five days is one person, and the top list needs a
sort over everybody), so their cost follows the number of people and days, not the number of buckets. They therefore never run on the
summary request. The worker works them out in the background and the summary READS the result by key:

* one row per view somebody has opened in the last day: (project, agent or all, role or all, range) in ``agent_insight_people_cache``,
  with when it was worked out (the summary reports it as ``users.topAsOf``);
* the worker refreshes a row every 30 s (1h and 24h views) or 5 min (7d, 30d, 90d), but only if its project has had events since the
  last refresh (or the row is old enough that the window itself has slid on), and works each project's views one after the other;
* the sums run over WEEKLY rows plus the few days before the first whole week (``agent_insight_users_weekly`` is written beside the daily
  rows), so a 90-day list is about thirteen weeks and a handful of days, not ninety days;
* a request that finds no (or a long-dead) row works it out ONCE, inside a short statement timeout. If that is too slow it answers with
  an empty top list and ``topAsOf: null`` and leaves a placeholder for the worker, rather than making the page wait.

The numbers a refresh produces are exact for the moment it ran.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, distinct, func, select, text, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_insights import (
    AgentInsightKey, agent_insight_people_cache, agent_insight_users, agent_insight_users_daily, agent_insight_users_weekly,
)
from services.agent_insights_store import aware, bucket_dt, utcnow

logger = logging.getLogger(__name__)

TOP_USERS = 20
#: How often a view is refreshed when its project has news.
REFRESH_SECONDS = {"1h": 30.0, "24h": 30.0, "7d": 300.0, "30d": 300.0, "90d": 300.0}
#: A row older than this many refresh intervals is not trusted by the summary (the worker must be down): it is worked out again, bounded.
MAX_AGE_INTERVALS = 6
#: A quiet project's row is still refreshed once this many intervals have passed, because the window slides on even with no events.
QUIET_REFRESH_INTERVALS = 10
#: How long a view is kept up to date after somebody last asked for it.
WANTED_FOR = timedelta(days=1)
#: The statement timeouts for working a view out on a request: the counts (an index count, quick) and the top list (a sum that grows with
#: the project, so it gets little time: it is the worker's job).
REQUEST_TIMEOUT_MS = 200
REQUEST_TOP_TIMEOUT_MS = 100
ALL = "*"

RANGE_LENGTH = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}


def window_start(now: datetime, range_: str) -> datetime:
    """Where a range's window starts: the same bucket edge the summary uses (a minute, an hour or a UTC midnight)."""
    edge = "minute" if range_ == "1h" else "hour" if range_ == "24h" else "day"
    return bucket_dt((now - RANGE_LENGTH[range_]).timestamp(), edge)


def _dialect(db: AsyncSession) -> str:
    return db.get_bind().dialect.name


def _first_week(since_day: date) -> date:
    """The first Monday on or after ``since_day``: from there the sums use whole weekly rows."""
    return since_day + timedelta(days=(7 - since_day.weekday()) % 7)


def _person_rows(pid: uuid.UUID, since_day: date, agent: str | None, role: str | None, cols: list[str]):
    """The weekly rows from the first whole week on, plus the daily rows before it, as one table of (person, counters): never more than
    thirteen weeks and six days of rows for the longest range. Weekly rows add all agents together, so a view of ONE agent has to use daily
    rows for the whole window."""
    wk, dy = agent_insight_users_weekly, agent_insight_users_daily
    first = _first_week(since_day) if not agent else date.max      # one agent: no weekly rows, the daily rows reach the whole window

    def part(t, cond):
        c = [t.c.project_id == pid, cond]
        if agent and t is dy:
            c.append(t.c.agent_id == agent)
        if role is not None:
            c.append(t.c.role == role)
        return select(*[t.c[x] for x in cols]).where(and_(*c))

    return union_all(part(wk, wk.c.week >= first), part(dy, and_(dy.c.day >= since_day, dy.c.day < first))).subquery()


async def compute_top(db: AsyncSession, pid: uuid.UUID, since_day: date, agent: str | None, role: str | None) -> list[dict[str, Any]]:
    rows = _person_rows(pid, since_day, agent, role, ["user_key", "role", "turns", "input_tokens", "output_tokens", "errors", "down", "last_seen_at"])
    q = (select(rows.c.user_key, func.max(rows.c.role).label("role"), func.sum(rows.c.turns).label("turns"), func.sum(rows.c.input_tokens).label("i"),
                func.sum(rows.c.output_tokens).label("o"), func.sum(rows.c.errors).label("errors"), func.sum(rows.c.down).label("down"),
                func.max(rows.c.last_seen_at).label("last"))
         .group_by(rows.c.user_key).order_by(func.sum(rows.c.turns).desc(), rows.c.user_key).limit(TOP_USERS))
    return [{"userKey": r.user_key, "role": r.role or None, "turns": int(r.turns), "inputTokens": int(r.i), "outputTokens": int(r.o),
             "errors": int(r.errors), "thumbsDown": int(r.down), "lastSeenAt": _iso(r.last)} for r in (await db.execute(q)).all()]


async def compute_counts(db: AsyncSession, pid: uuid.UUID, since: datetime, agent: str | None, role: str | None) -> dict[str, Any]:
    """Different people in the window, how many of them are new, and people per role."""
    u = agent_insight_users
    if agent is None:
        # all agents: the one-row-per-person table (a person's latest role is the role filter); exact to the second
        c = [u.c.project_id == pid]
        if role is not None:
            c.append(u.c.role == role)
        active = (await db.execute(select(func.count()).select_from(u).where(and_(*c, u.c.last_seen_at >= since)))).scalar() or 0
        new = (await db.execute(select(func.count()).select_from(u).where(and_(*c, u.c.first_seen_at >= since)))).scalar() or 0
        by_role = {r.role: int(r.n) for r in (await db.execute(
            select(u.c.role, func.count().label("n")).where(and_(*c, u.c.last_seen_at >= since)).group_by(u.c.role))).all()}
        return {"active": int(active), "new": int(new), "roleUsers": by_role}
    rows = _person_rows(pid, since.date(), agent, role, ["user_key", "role"])
    active = (await db.execute(select(func.count(distinct(rows.c.user_key))))).scalar() or 0
    new = (await db.execute(select(func.count(distinct(rows.c.user_key))).select_from(
        rows.join(u, and_(u.c.project_id == pid, u.c.user_key == rows.c.user_key))).where(u.c.first_seen_at >= since))).scalar() or 0
    by_role = {r.role: int(r.n) for r in (await db.execute(
        select(rows.c.role, func.count(distinct(rows.c.user_key)).label("n")).group_by(rows.c.role))).all()}
    return {"active": int(active), "new": int(new), "roleUsers": by_role}


async def compute_people(db: AsyncSession, pid: uuid.UUID, since: datetime, agent: str | None, role: str | None) -> dict[str, Any]:
    """Everything the summary needs about people, worked out in full (no time limit: this is what the worker runs)."""
    return {**await compute_counts(db, pid, since, agent, role), "top": await compute_top(db, pid, since.date(), agent, role)}


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else aware(dt).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# the cache
# ---------------------------------------------------------------------------

def _key(agent: str | None, role: str | None) -> tuple[str, str]:
    return agent or ALL, ALL if role is None else role


async def _read(db: AsyncSession, pid: uuid.UUID, range_: str, agent: str | None, role: str | None):
    t = agent_insight_people_cache
    a, r = _key(agent, role)
    return (await db.execute(select(t).where(and_(t.c.project_id == pid, t.c.agent_id == a, t.c.role == r, t.c.range == range_)))).first()


async def _write(db: AsyncSession, pid: uuid.UUID, range_: str, agent: str | None, role: str | None, *, payload: dict[str, Any] | None,
                 now: datetime, compute_ms: int | None, wanted: bool = True) -> None:
    """Store a computed payload, or (payload None) just register the view so the worker will work it out. ``wanted`` says somebody asked
    for it just now (a refresh by the worker is not somebody asking: it must not keep an abandoned view alive)."""
    t = agent_insight_people_cache
    a, r = _key(agent, role)
    ins = (pg_insert if _dialect(db) == "postgresql" else sqlite_insert)(t)
    values = {"project_id": pid, "agent_id": a, "role": r, "range": range_, "wanted_at": now}
    set_ = {"wanted_at": now} if wanted else {}
    if payload is not None:
        values.update(payload=payload, computed_at=now, compute_ms=compute_ms)
        set_.update(payload=payload, computed_at=now, compute_ms=compute_ms)
    await db.execute(ins.on_conflict_do_update(index_elements=["project_id", "agent_id", "role", "range"], set_=set_), values)


async def _bounded(db: AsyncSession, ms: int, work):
    """Run ``work()`` inside a statement timeout (Postgres; elsewhere there is no limit). Returns (done, result): not done means it timed out."""
    if _dialect(db) != "postgresql":
        return True, await work()
    try:
        async with db.begin_nested():
            await db.execute(text("SELECT set_config('statement_timeout', :v, true)"), {"v": str(ms)})
            out = await work()
            await db.execute(text("SELECT set_config('statement_timeout', '0', true)"))
            return True, out
    except Exception as e:  # noqa: BLE001
        if "statement timeout" in str(e).lower() or "canceling statement" in str(e).lower():
            return False, None
        raise


_last_touch: dict[tuple, float] = {}


async def for_summary(db: AsyncSession, pid: uuid.UUID, range_: str, since: datetime, now: datetime, agent: str | None, role: str | None,
                      *, use_cache: bool) -> dict[str, Any]:
    """The people numbers for a summary: ``{active, new, roleUsers, top, topAsOf, partial}``. ``partial`` is true when some part could not
    be worked out in time and was left out (the top list empty, the counts then only a lower bound)."""
    if not use_cache:
        return {**await compute_people(db, pid, since, agent, role), "topAsOf": _iso(now), "partial": False}
    row = await _read(db, pid, range_, agent, role)
    age_limit = REFRESH_SECONDS[range_] * MAX_AGE_INTERVALS
    if row is not None and row.payload is not None and row.computed_at is not None and (now - aware(row.computed_at)).total_seconds() <= age_limit:
        k = (str(pid), range_, agent, role)
        if time.monotonic() - _last_touch.get(k, -1e9) > 60:      # keep the worker refreshing this view: one small write a minute at most
            _last_touch[k] = time.monotonic()
            await _write(db, pid, range_, agent, role, payload=None, now=now, compute_ms=None)
            await db.commit()
        return {**row.payload, "topAsOf": _iso(row.computed_at), "partial": False}
    # nothing usable yet: work it out once, with a short limit on each step
    t0 = time.perf_counter()
    done, counts = await _bounded(db, REQUEST_TIMEOUT_MS, lambda: compute_counts(db, pid, since, agent, role))
    top_done, top = (False, None)
    if done:
        top_done, top = await _bounded(db, REQUEST_TOP_TIMEOUT_MS, lambda: compute_top(db, pid, since.date(), agent, role))
    if done and top_done:
        payload = {**counts, "top": top}
        await _write(db, pid, range_, agent, role, payload=payload, now=now, compute_ms=int((time.perf_counter() - t0) * 1000))
        await db.commit()
        return {**payload, "topAsOf": _iso(now), "partial": False}
    await _write(db, pid, range_, agent, role, payload=None, now=now, compute_ms=None)   # leave a placeholder: the worker fills it in
    await db.commit()
    return {**(counts or {"active": 0, "new": 0, "roleUsers": {}}), "top": [], "topAsOf": None, "partial": True}


# ---------------------------------------------------------------------------
# the worker's refresh
# ---------------------------------------------------------------------------

async def refresh_due(session_factory, *, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
    """Work out every wanted view that is due. A view is due when it has never been worked out, or its project has had events since and its
    interval (30 s or 5 min) has passed, or it is so old that the window has slid on. Returns what it did and what it cost."""
    now = now or utcnow()
    t = agent_insight_people_cache
    k = AgentInsightKey
    async with session_factory() as s:
        wanted = (await s.execute(select(t.c.project_id, t.c.agent_id, t.c.role, t.c.range, t.c.computed_at).where(t.c.wanted_at >= now - WANTED_FOR)
                                  .order_by(t.c.project_id))).all()
        applied = {r.project_id: aware(r.last_applied_at) for r in (await s.execute(
            select(k.project_id, func.max(k.last_applied_at).label("last_applied_at")).group_by(k.project_id))).all()}
    done: list[dict[str, Any]] = []
    top_memo: dict[tuple, list[dict[str, Any]]] = {}
    for w in wanted:
        age = None if w.computed_at is None else (now - aware(w.computed_at)).total_seconds()
        interval = REFRESH_SECONDS[w.range]
        news = applied.get(w.project_id) is not None and (w.computed_at is None or applied[w.project_id] > aware(w.computed_at))
        if not (force or age is None or (news and age >= interval) or age >= interval * QUIET_REFRESH_INTERVALS):
            continue
        agent = None if w.agent_id == ALL else w.agent_id
        role = None if w.role == ALL else w.role
        since = window_start(now, w.range)
        t0 = time.perf_counter()
        try:
            async with session_factory() as s:
                if _dialect(s) == "postgresql":      # this sums up to a million rows in the background: let the sort stay in memory
                    await s.execute(text("SELECT set_config('work_mem', '64MB', true)"))
                counts = await compute_counts(s, w.project_id, since, agent, role)
                # 1h and 24h views start on the same UTC day, so they share one sum
                memo = (w.project_id, agent, role, since.date())
                if memo not in top_memo:
                    top_memo[memo] = await compute_top(s, w.project_id, since.date(), agent, role)
                await _write(s, w.project_id, w.range, agent, role, payload={**counts, "top": top_memo[memo]}, now=now,
                             compute_ms=int((time.perf_counter() - t0) * 1000), wanted=False)
                await s.commit()
        except Exception:  # noqa: BLE001
            logger.warning("[insights] could not refresh the people list of %s %s", w.project_id, w.range, exc_info=True)
            continue
        done.append({"project": str(w.project_id), "range": w.range, "agent": w.agent_id, "role": w.role, "ms": round((time.perf_counter() - t0) * 1000)})
    return {"refreshed": len(done), "views": done}

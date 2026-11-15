"""The writer behind the agent insights: turns a batch of events into rows and counters, exactly once.

``apply_events`` is the only place events become numbers. It is called by the worker (events read from the stream) and, when Redis is
down, by the ingest route itself, and it must give the same numbers however many times a batch is delivered and in whatever order
batches arrive. How:

* the raw row is inserted with ``ON CONFLICT DO NOTHING ... RETURNING``: only the events that were really NEW come back, and only
  those are counted. A re-sent or re-delivered event inserts nothing and so adds nothing;
* every counter is changed by ADDING a delta (``turns = turns + 3``), never by writing a total, so two workers cannot overwrite each
  other, and a batch is applied in one transaction: all of it or none of it;
* the counters are keyed by the time the event HAPPENED (its ``at``), so a late event lands in the right minute, hour and day;
* a rating belongs to its turn's bucket and replaces the turn's earlier rating: the difference is added (up -> down is up -1, down +1).
  A rating that arrives before its turn waits in ``agent_insight_pending_ratings`` and is applied when the turn is inserted (or by the
  sweep if the turn was inserted by another worker a moment later);
* one project's batches are applied one at a time (a Postgres advisory lock held for the transaction), which is what makes the
  "turn and its rating arrive in two workers at once" case safe, and it also means two workers can never deadlock on a counter row.

Events reach here already checked and shortened by ``agent_insights_ingest`` (see ``normalize_event`` there for the short key names).
"""
from __future__ import annotations

import logging
import re
import uuid
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import and_, bindparam, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_insights import (
    COUNTER_COLUMNS, FLOAT_COLUMNS, GRAIN_RETENTION_HOURS, GRAINS, LATENCY_BUCKETS, LATENCY_EDGES_MS, MODEL_TABLES, ROLLUP_TABLES,
    TOOL_TABLES, AgentInsightKey, agent_insight_dropped, agent_insight_handoffs, agent_insight_pending_ratings,
    agent_insight_active_daily, agent_insight_people_cache, agent_insight_problems, agent_insight_user_days, agent_insight_users,
    agent_insight_users_daily, agent_insight_users_weekly, agent_turn_events,
)

logger = logging.getLogger(__name__)

BUCKET_SECONDS = {"minute": 60, "hour": 3600, "day": 86400}
RAW_RETENTION_DAYS = 30
USERS_DAILY_RETENTION_DAYS = 120
USERS_RETENTION_DAYS = 400
DROPPED_RETENTION_DAYS = 90
PENDING_RATING_HOLD = timedelta(hours=1)
#: The newest problem turns kept per project (the page shows 50).
PROBLEMS_PER_PROJECT = 200
#: How long a distinct-people counter lives, and how old a bucket may be and still get one (the minute ones feed the last-hour chart,
#: the hour ones the 24-hour and 7-day charts, which reach back to the start of the day 7 days ago).
HLL_TTL_SECONDS = {"minute": 3 * 3600, "hour": 9 * 86400}
HLL_MAX_AGE_SECONDS = {"minute": 2 * 3600, "hour": 8 * 86400 + 3600}
RANK = {"open": 0, "claimed": 1, "resolved": 2}
_CHUNK = 400
_PARTITION_RE = re.compile(r"^agent_turn_events_p(\d{8})$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back without a time zone; everything here is UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def floor_ts(ts: float, grain: str) -> int:
    size = BUCKET_SECONDS[grain]
    return int(ts) // size * size


def bucket_dt(ts: float, grain: str) -> datetime:
    return datetime.fromtimestamp(floor_ts(ts, grain), timezone.utc)


def latency_bucket(ms: int) -> int:
    """Which histogram bucket a reply of ``ms`` milliseconds counts in (the first whose upper edge it does not pass)."""
    return bisect_left(LATENCY_EDGES_MS, ms)


def percentile_from_hist(hist: list[int], q: float) -> int | None:
    """The ``q`` (0..1) percentile of the replies in a histogram, in ms, by straight-line interpolation inside the bucket it falls in.
    Accurate to one bucket width (about 40%); None when there are no replies."""
    total = sum(hist)
    if total <= 0:
        return None
    rank = q * total
    seen = 0.0
    for i, n in enumerate(hist):
        if n and seen + n >= rank:
            lower = 0 if i == 0 else LATENCY_EDGES_MS[i - 1]
            if i >= len(LATENCY_EDGES_MS):
                return lower  # slower than the last edge: all we can say is "at least this"
            upper = LATENCY_EDGES_MS[i]
            return int(round(lower + (upper - lower) * min(1.0, max(0.0, (rank - seen) / n))))
        seen += n
    return LATENCY_EDGES_MS[-1]


def hll_key(project: str, agent: str, role: str, grain: str, bucket_epoch: int) -> str:
    return f"forge:hll:{project}:{grain}:{bucket_epoch}:{agent}:{role}"


def _dialect(session: AsyncSession) -> str:
    return session.get_bind().dialect.name


def _insert(session: AsyncSession, table):
    return (pg_insert if _dialect(session) == "postgresql" else sqlite_insert)(table)


async def lock_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Hold this project's writer lock until the transaction ends (Postgres; SQLite has one writer anyway)."""
    if _dialect(session) == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 7))"), {"k": f"forge-insights:{project_id}"})


# ---------------------------------------------------------------------------
# bulk upsert
# ---------------------------------------------------------------------------

_PG_TYPE_CACHE: dict[tuple[str, str], str] = {}


def _pg_array_type(table, col: str) -> str:
    """The Postgres element type for a column, used to send a whole column of values as one array parameter."""
    k = (table.name, col)
    if k not in _PG_TYPE_CACHE:
        t = table.c[col].type
        kind = type(t).__name__.lower()
        if "string" in kind or "text" in kind or "json" in kind:
            _PG_TYPE_CACHE[k] = "text"   # JSON travels as text and is cast back to jsonb in the SELECT
        else:
            from sqlalchemy.dialects import postgresql

            _PG_TYPE_CACHE[k] = t.compile(dialect=postgresql.dialect())
    return _PG_TYPE_CACHE[k]


def _is_json(table, col: str) -> bool:
    return "json" in type(table.c[col].type).__name__.lower()


async def _pg_bulk(session: AsyncSession, table, rows: list[dict[str, Any]], key: list[str], *, add: Iterable[str] = (),
                   least: Iterable[str] = (), greatest: Iterable[str] = (), follow: tuple[str, list[str]] | None = None,
                   replace: Iterable[str] = (), returning: tuple[str, ...] = (), chunk: int = 4000) -> list[tuple]:
    """The Postgres form of the bulk insert: each COLUMN is sent as one array and expanded with ``unnest``. The statement is the same
    text whatever the number of rows, so it is compiled once, and a thousand rows cost a few dozen parameters, not tens of thousands."""
    import json as _json

    cols = list(rows[0].keys())
    q = lambda name: '"' + name + '"'  # noqa: E731
    tn = q(table.name)
    select_list = ", ".join(f"CAST(u.{q(c)} AS jsonb)" if _is_json(table, c) else f"u.{q(c)}" for c in cols)
    unnest = ", ".join(f"CAST(:c{i} AS {_pg_array_type(table, c)}[])" for i, c in enumerate(cols))
    sets = [f"{q(c)} = {tn}.{q(c)} + excluded.{q(c)}" for c in add]
    sets += [f"{q(c)} = LEAST({tn}.{q(c)}, excluded.{q(c)})" for c in least]
    sets += [f"{q(c)} = GREATEST({tn}.{q(c)}, excluded.{q(c)})" for c in greatest]
    if follow:
        by, fcols = follow
        sets += [f"{q(c)} = CASE WHEN excluded.{q(by)} >= {tn}.{q(by)} THEN excluded.{q(c)} ELSE {tn}.{q(c)} END" for c in fcols]
    sets += [f"{q(c)} = excluded.{q(c)}" for c in replace]
    conflict = f"ON CONFLICT ({', '.join(q(k) for k in key)}) " + (f"DO UPDATE SET {', '.join(sets)}" if sets else "DO NOTHING")
    sql = (f"INSERT INTO {tn} ({', '.join(q(c) for c in cols)}) SELECT {select_list} FROM unnest({unnest}) AS u({', '.join(q(c) for c in cols)}) "
           f"{conflict}" + (f" RETURNING {', '.join(q(c) for c in returning)}" if returning else ""))
    stmt = text(sql)
    out: list[tuple] = []
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        params = {}
        for j, c in enumerate(cols):
            vals = [r[c] for r in part]
            params[f"c{j}"] = [None if v is None else _json.dumps(v) for v in vals] if _is_json(table, c) else vals
        res = await session.execute(stmt, params)
        if returning:
            out.extend(tuple(r) for r in res)
    return out


async def _upsert(session: AsyncSession, table, rows: list[dict[str, Any]], key: list[str], *, add: Iterable[str] = (),
                  least: Iterable[str] = (), greatest: Iterable[str] = (), follow: tuple[str, list[str]] | None = None,
                  replace: Iterable[str] = (), chunk: int = _CHUNK) -> None:
    """INSERT the rows, and where one already exists change it by: ADDING ``add`` columns, keeping the smaller of ``least`` and the
    larger of ``greatest``, taking ``follow``'s columns from whichever side has the later value in ``follow``'s first column, or
    overwriting ``replace`` columns. Every row in one call must have a different key (a Postgres rule for this form of upsert):
    callers group first."""
    if not rows:
        return
    rows = sorted(rows, key=lambda r: tuple(r[k] for k in key))  # the same order every time: no lock-order surprises between processes
    if _dialect(session) == "postgresql":
        await _pg_bulk(session, table, rows, key, add=add, least=least, greatest=greatest, follow=follow, replace=replace)
        return
    stmt = _insert(session, table)
    ex = stmt.excluded
    set_: dict[str, Any] = {c: table.c[c] + ex[c] for c in add}
    for c in least:
        set_[c] = case((ex[c] < table.c[c], ex[c]), else_=table.c[c])
    for c in greatest:
        set_[c] = case((ex[c] > table.c[c], ex[c]), else_=table.c[c])
    if follow:
        by, cols = follow
        for c in cols:
            set_[c] = case((ex[by] >= table.c[by], ex[c]), else_=table.c[c])
    for c in replace:
        set_[c] = ex[c]
    stmt = stmt.on_conflict_do_update(index_elements=key, set_=set_) if set_ else stmt.on_conflict_do_nothing(index_elements=key)
    for i in range(0, len(rows), chunk):
        await session.execute(stmt, rows[i:i + chunk])


async def _insert_new(session: AsyncSession, table, rows: list[dict[str, Any]], key: list[str], returning: str | tuple[str, ...]) -> set[Any]:
    """INSERT ... ON CONFLICT DO NOTHING and say which rows were really inserted (their ``returning`` column, or a tuple of columns):
    the rows that already existed come back as nothing. This is how a repeated event is told from a new one."""
    if not rows:
        return set()
    cols = (returning,) if isinstance(returning, str) else tuple(returning)
    if _dialect(session) == "postgresql":
        got = await _pg_bulk(session, table, rows, key, returning=cols)
    else:
        stmt = _insert(session, table).on_conflict_do_nothing(index_elements=key).returning(*[table.c[c] for c in cols])
        got = []
        for i in range(0, len(rows), _CHUNK):
            got.extend(tuple(r) for r in await session.execute(stmt, rows[i:i + _CHUNK]))
    return {r[0] for r in got} if isinstance(returning, str) else {tuple(r) for r in got}


# ---------------------------------------------------------------------------
# what a batch adds up to
# ---------------------------------------------------------------------------

@dataclass
class _Acc:
    """The deltas a batch makes, grouped by row, before any of them is written."""
    now: datetime
    rollup: dict[str, dict[tuple, Counter]] = field(default_factory=lambda: {g: defaultdict(Counter) for g in GRAINS})
    models: dict[str, dict[tuple, Counter]] = field(default_factory=lambda: {g: defaultdict(Counter) for g in GRAINS})
    tools: dict[str, dict[tuple, Counter]] = field(default_factory=lambda: {g: defaultdict(Counter) for g in GRAINS})
    udaily: dict[tuple, dict[str, Any]] = field(default_factory=dict)
    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    hll: dict[tuple, set] = field(default_factory=lambda: defaultdict(set))
    max_at: float = 0.0
    _bk: dict[int, tuple[tuple[str, datetime], ...]] = field(default_factory=dict)

    def buckets(self, at: float) -> tuple[tuple[str, datetime], ...]:
        """The (grain, bucket start) pairs an event at ``at`` is counted in, leaving out grains that no longer keep so old a bucket.
        Events of one minute share the answer, so it is worked out once per minute."""
        minute = int(at) // 60
        hit = self._bk.get(minute)
        if hit is None:
            hit = self._bk[minute] = tuple((g, b) for g in GRAINS if self.fresh(b := bucket_dt(at, g), g))
        return hit

    def fresh(self, bucket: datetime, grain: str) -> bool:
        """Buckets older than the grain's retention are not written: the housekeeping would only delete them."""
        return bucket >= self.now - timedelta(hours=GRAIN_RETENTION_HOURS[grain])

    def bump_rollup(self, at: float, agent: str, role: str, delta: dict[str, float]) -> None:
        for grain, b in self.buckets(at):
            row = self.rollup[grain][(b, agent, role)]
            for k, v in delta.items():
                row[k] += v

    def bump_user_day(self, at: float, agent: str, user: str, role: str, delta: dict[str, int]) -> None:
        day = datetime.fromtimestamp(floor_ts(at, "day"), timezone.utc).date()
        entry = self.udaily.get((day, agent, user))
        if entry is None:
            entry = self.udaily[(day, agent, user)] = {"c": Counter(), "first": at, "last": at, "role": role, "role_at": at}
        for k, v in delta.items():
            entry["c"][k] += v
        entry["first"] = min(entry["first"], at)
        entry["last"] = max(entry["last"], at)
        if at >= entry["role_at"]:
            entry["role"], entry["role_at"] = role, at

    def add_turn(self, project: str, ev: dict[str, Any], rating: int | None) -> None:
        at, agent, role, user = ev["at"], ev["a"], ev["r"], ev["u"]
        status = ev["s"]
        delta: dict[str, float] = {
            "turns": 1, "errors": status == "error", "blocked": status == "blocked", "handed_off": ev["h"],
            "conversations": ev["n"] == 1, "input_tokens": ev["i"], "output_tokens": ev["o"], "tool_calls": ev["tc"],
            "tool_errors": ev["te"], "ms_sum": ev["ms"], "up": rating == 1, "down": rating == -1,
            f"lat_{latency_bucket(ev['ms'])}": 1,
        }
        delta = {k: int(v) for k, v in delta.items() if v}
        self.bump_rollup(at, agent, role, delta)
        for grain, b in self.buckets(at):
            m = self.models[grain][(b, agent, role, ev["m"])]
            m["turns"] += 1
            m["input_tokens"] += ev["i"]
            m["output_tokens"] += ev["o"]
            for name, ok, ms in ev["tl"]:
                t = self.tools[grain][(b, agent, role, name)]
                t["calls"] += 1
                t["errors"] += 0 if ok else 1
                t["ms_sum"] += ms
        self.bump_user_day(at, agent, user, role, {k: v for k, v in {
            "turns": 1, "input_tokens": ev["i"], "output_tokens": ev["o"], "errors": int(status == "error"),
            "up": int(rating == 1), "down": int(rating == -1)}.items() if v})
        u = self.users.get(user)
        if u is None:
            self.users[user] = {"first": at, "last": at, "role": role, "role_at": at}
        else:
            u["first"], u["last"] = min(u["first"], at), max(u["last"], at)
            if at >= u["role_at"]:
                u["role"], u["role_at"] = role, at
        for grain in ("minute", "hour"):
            self.hll[(agent, role, grain, floor_ts(at, grain))].add(user)
        self.max_at = max(self.max_at, at)


@dataclass
class ApplyResult:
    new_turns: int = 0
    duplicate_turns: int = 0
    ratings_applied: int = 0
    ratings_held: int = 0
    handoffs_changed: int = 0
    max_at: float = 0.0
    #: (redis key, seconds to live, members) for the worker to add after the transaction commits
    hll: list[tuple[str, int, list[str]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# apply a batch
# ---------------------------------------------------------------------------

async def apply_events(session: AsyncSession, project_id: uuid.UUID | str, events: list[dict[str, Any]], *,
                       now: datetime | None = None) -> ApplyResult:
    """Apply one project's events inside the caller's transaction (which the caller commits). Safe to repeat: see the module notes."""
    pid = uuid.UUID(str(project_id))
    now = now or utcnow()
    await lock_project(session, pid)
    acc = _Acc(now=now)
    res = ApplyResult()

    # one event per id (the first one in the batch), then split by kind
    seen: set[str] = set()
    turns: list[dict[str, Any]] = []
    ratings: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    for ev in events:
        kind = ev["t"]
        if kind == "turn":
            if ev["id"] in seen:
                res.duplicate_turns += 1
                continue
            seen.add(ev["id"])
            turns.append(ev)
        elif kind == "rating":
            ratings.append(ev)
        elif kind == "handoff":
            handoffs.append(ev)

    problems_added = False
    if turns:
        problems_added = await _apply_turns(session, pid, turns, acc, res, now)
    if ratings:
        problems_added |= await _apply_ratings(session, pid, ratings, acc, res, now)
    if handoffs:
        await _apply_handoffs(session, pid, handoffs, acc, res)
        acc.max_at = max([acc.max_at] + [h["at"] for h in handoffs])

    await _flush(session, pid, acc)
    if problems_added:
        await _trim_problems(session, pid)
    if acc.max_at:
        res.max_at = acc.max_at
        col = AgentInsightKey.last_event_at
        top = to_dt(acc.max_at)
        # last_applied_at (when this was written, not when the events happened) is how the people-list refresh knows the project has news
        await session.execute(update(AgentInsightKey).where(and_(AgentInsightKey.project_id == pid, AgentInsightKey.revoked_at.is_(None)))
                              .values(last_event_at=case((or_(col.is_(None), col < top), top), else_=col), last_applied_at=now))
    for (agent, role, grain, bucket), users in acc.hll.items():
        if bucket < now.timestamp() - HLL_MAX_AGE_SECONDS[grain]:
            continue
        res.hll.append((hll_key(str(pid), agent, role, grain, bucket), HLL_TTL_SECONDS[grain], sorted(users)))
    return res


async def _apply_turns(session: AsyncSession, pid: uuid.UUID, turns: list[dict[str, Any]], acc: _Acc, res: ApplyResult,
                       now: datetime) -> bool:
    raw = agent_turn_events
    # A thumbs that came before its turn is waiting: it is part of the turn from the start.
    pending: dict[str, Any] = {}
    ids = [t["id"] for t in turns]
    for i in range(0, len(ids), _CHUNK):
        q = select(agent_insight_pending_ratings.c.turn_id, agent_insight_pending_ratings.c.rating, agent_insight_pending_ratings.c.at,
                   agent_insight_pending_ratings.c.note).where(and_(agent_insight_pending_ratings.c.project_id == pid,
                                                                    agent_insight_pending_ratings.c.turn_id.in_(ids[i:i + _CHUNK])))
        for r in (await session.execute(q)).all():
            pending[r.turn_id] = r

    rows = []
    for ev in turns:
        p = pending.get(ev["id"])
        rows.append({
            "project_id": pid, "event_id": ev["id"], "at": to_dt(ev["at"]), "received_at": now, "agent_id": ev["a"],
            "conversation_id": ev["c"], "user_key": ev["u"], "role": ev["r"], "env": ev["e"], "model": ev["m"],
            "input_tokens": ev["i"], "output_tokens": ev["o"], "ms": ev["ms"], "status": ev["s"], "tool_calls": ev["tc"],
            "tool_errors": ev["te"], "tools": [{"name": n, "ok": bool(ok), "ms": ms} for n, ok, ms in ev["tl"]] or None,
            "handed_off": bool(ev["h"]), "turn_number": ev["n"], "rating": p.rating if p else None,
            "rating_at": aware(p.at) if p else None, "rating_note": p.note if p else None,
            "problem": ({"reason": ev["p"][0], "message": ev["p"][1], "detail": ev["p"][2]} if ev["p"] else None),
        })
    new_ids: set[str] = await _insert_new(session, raw, rows, ["project_id", "event_id", "at"], "event_id")

    problem_rows = []
    for ev in turns:
        if ev["id"] not in new_ids:
            res.duplicate_turns += 1
            continue
        res.new_turns += 1
        p = pending.get(ev["id"])
        rating = p.rating if p else None
        acc.add_turn(str(pid), ev, rating)
        if ev["p"]:
            problem_rows.append(_problem_row(pid, ev["id"], ev["at"], ev["a"], ev["c"], ev["r"], ev["p"][0], ev["p"][1], ev["p"][2], "turn"))
        elif rating == -1:
            problem_rows.append(_problem_row(pid, ev["id"], ev["at"], ev["a"], ev["c"], ev["r"], "thumbs_down", None,
                                             pending[ev["id"]].note, "rating"))
    used = [i for i in new_ids if i in pending]
    for i in range(0, len(used), _CHUNK):
        await session.execute(delete(agent_insight_pending_ratings).where(and_(
            agent_insight_pending_ratings.c.project_id == pid, agent_insight_pending_ratings.c.turn_id.in_(used[i:i + _CHUNK]))))
    if problem_rows:
        await _upsert(session, agent_insight_problems, problem_rows, ["project_id", "turn_id"])
    return bool(problem_rows)


def _problem_row(pid, turn_id, at, agent, conv, role, reason, message, detail, source) -> dict[str, Any]:
    return {"project_id": pid, "turn_id": turn_id, "at": to_dt(at), "agent_id": agent, "conversation_id": conv, "role": role,
            "reason": reason, "message": message, "detail": detail, "source": source}


async def _apply_ratings(session: AsyncSession, pid: uuid.UUID, ratings: list[dict[str, Any]], acc: _Acc, res: ApplyResult,
                         now: datetime) -> bool:
    """Attach each rating to its turn (the latest one per turn wins), or hold it if the turn has not arrived."""
    latest: dict[str, dict[str, Any]] = {}
    for ev in ratings:
        cur = latest.get(ev["tid"])
        if cur is None or ev["at"] >= cur["at"]:
            latest[ev["tid"]] = ev
    raw = agent_turn_events
    found: dict[str, Any] = {}
    tids = list(latest)
    for i in range(0, len(tids), _CHUNK):
        q = select(raw.c.event_id, raw.c.at, raw.c.agent_id, raw.c.role, raw.c.user_key, raw.c.conversation_id, raw.c.rating,
                   raw.c.rating_at).where(and_(raw.c.project_id == pid, raw.c.event_id.in_(tids[i:i + _CHUNK])))
        for r in (await session.execute(q)).all():
            found[r.event_id] = r

    updates: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    add_problems: list[dict[str, Any]] = []
    drop_problems: list[str] = []
    for tid, ev in latest.items():
        row = found.get(tid)
        if row is None:
            held.append({"project_id": pid, "turn_id": tid, "rating": ev["v"], "at": to_dt(ev["at"]), "note": ev["nt"], "received_at": now})
            res.ratings_held += 1
            continue
        cur_at = aware(row.rating_at)
        if cur_at is not None and to_dt(ev["at"]) < cur_at:
            continue  # an older thumbs that arrived late: the newer one already stands
        old, new = row.rating, ev["v"]
        updates.append({"b_p": pid, "b_e": tid, "b_at": row.at, "b_rating": new, "b_rat": to_dt(ev["at"]), "b_note": ev["nt"]})
        res.ratings_applied += 1
        if old == new:
            continue
        d_up = int(new == 1) - int(old == 1)
        d_down = int(new == -1) - int(old == -1)
        turn_at = aware(row.at).timestamp()
        delta = {k: v for k, v in (("up", d_up), ("down", d_down)) if v}
        acc.bump_rollup(turn_at, row.agent_id, row.role, delta)
        acc.bump_user_day(turn_at, row.agent_id, row.user_key, row.role, delta)
        if new == -1:
            add_problems.append(_problem_row(pid, tid, turn_at, row.agent_id, row.conversation_id, row.role, "thumbs_down", None,
                                             ev["nt"], "rating"))
        elif old == -1:
            drop_problems.append(tid)
    if updates:
        await session.execute(
            update(raw).where(and_(raw.c.project_id == bindparam("b_p"), raw.c.event_id == bindparam("b_e"), raw.c.at == bindparam("b_at")))
            .values(rating=bindparam("b_rating"), rating_at=bindparam("b_rat"), rating_note=bindparam("b_note")), updates)
    if held:
        await _upsert(session, agent_insight_pending_ratings, held, ["project_id", "turn_id"], greatest=["at"],
                      follow=("at", ["rating", "note"]))
    if add_problems:
        await _upsert(session, agent_insight_problems, add_problems, ["project_id", "turn_id"])
    for i in range(0, len(drop_problems), _CHUNK):
        await session.execute(delete(agent_insight_problems).where(and_(
            agent_insight_problems.c.project_id == pid, agent_insight_problems.c.source == "rating",
            agent_insight_problems.c.turn_id.in_(drop_problems[i:i + _CHUNK]))))
    # a thumbs that found its turn no longer needs to wait
    done = [t for t in tids if t in found]
    for i in range(0, len(done), _CHUNK):
        await session.execute(delete(agent_insight_pending_ratings).where(and_(
            agent_insight_pending_ratings.c.project_id == pid, agent_insight_pending_ratings.c.turn_id.in_(done[i:i + _CHUNK]))))
    return bool(add_problems)


def _handoff_contribution(opened_at: datetime, status: str, resolve_minutes: float | None) -> tuple[float, dict[str, float]]:
    c: dict[str, float] = {"handoff_total": 1, f"handoff_{status}": 1}
    if status == "resolved" and resolve_minutes is not None:
        c["handoff_resolve_n"] = 1
        c["handoff_resolve_min_sum"] = float(resolve_minutes)
    return aware(opened_at).timestamp(), c


async def _apply_handoffs(session: AsyncSession, pid: uuid.UUID, events: list[dict[str, Any]], acc: _Acc, res: ApplyResult) -> None:
    """A conversation's handoff has ONE state (open, claimed or resolved: the latest event by time wins). The counters change only by
    what that state changes, so repeating an event, or sending them out of order, ends in the same numbers."""
    by_conv: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        by_conv[(ev["a"], ev["c"])].append(ev)
    h = agent_insight_handoffs
    existing: dict[tuple[str, str], Any] = {}
    convs = sorted({c for _a, c in by_conv})
    for i in range(0, len(convs), _CHUNK):
        q = select(h).where(and_(h.c.project_id == pid, h.c.conversation_id.in_(convs[i:i + _CHUNK])))
        for r in (await session.execute(q)).all():
            existing[(r.agent_id, r.conversation_id)] = r
    rows = []
    for (agent, conv), evs in by_conv.items():
        old = existing.get((agent, conv))
        if old is not None:
            opened, status, status_at, rm = aware(old.opened_at).timestamp(), old.status, aware(old.status_at).timestamp(), old.resolve_minutes
        else:
            opened, status, status_at, rm = None, None, None, None
        for ev in sorted(evs, key=lambda e: (e["at"], RANK[e["s"]])):
            opened = ev["at"] if opened is None else min(opened, ev["at"])
            if status is None or (ev["at"], RANK[ev["s"]]) >= (status_at, RANK[status]):
                status, status_at, rm = ev["s"], ev["at"], ev["rm"]
        if old is not None and (to_dt(opened), status, to_dt(status_at), rm) == (aware(old.opened_at), old.status, aware(old.status_at), old.resolve_minutes):
            continue
        res.handoffs_changed += 1
        if old is not None:
            at, c = _handoff_contribution(old.opened_at, old.status, old.resolve_minutes)
            acc.bump_rollup(at, agent, "", {k: -v for k, v in c.items()})
        at, c = _handoff_contribution(to_dt(opened), status, rm)
        acc.bump_rollup(at, agent, "", c)
        rows.append({"project_id": pid, "agent_id": agent, "conversation_id": conv, "opened_at": to_dt(opened), "status": status,
                     "status_at": to_dt(status_at), "resolve_minutes": rm})
    await _upsert(session, h, rows, ["project_id", "agent_id", "conversation_id"],
                  replace=["opened_at", "status", "status_at", "resolve_minutes"])


async def _flush(session: AsyncSession, pid: uuid.UUID, acc: _Acc) -> None:
    """Write everything the batch added up to, table by table, each in a fixed order."""
    for grain in GRAINS:
        rows = []
        for (b, agent, role), c in acc.rollup[grain].items():
            if not any(c.values()):
                continue
            rows.append({"project_id": pid, "bucket": b, "agent_id": agent, "role": role,
                         **{col: int(c.get(col, 0)) for col in COUNTER_COLUMNS},
                         **{col: float(c.get(col, 0.0)) for col in FLOAT_COLUMNS}})
        await _upsert(session, ROLLUP_TABLES[grain], rows, ["project_id", "bucket", "agent_id", "role"],
                      add=[*COUNTER_COLUMNS, *FLOAT_COLUMNS], chunk=150)
        mrows = [{"project_id": pid, "bucket": b, "agent_id": a, "role": r, "model": m, "turns": c["turns"],
                  "input_tokens": c["input_tokens"], "output_tokens": c["output_tokens"]}
                 for (b, a, r, m), c in acc.models[grain].items()]
        await _upsert(session, MODEL_TABLES[grain], mrows, ["project_id", "bucket", "agent_id", "role", "model"],
                      add=["turns", "input_tokens", "output_tokens"])
        trows = [{"project_id": pid, "bucket": b, "agent_id": a, "role": r, "tool": t, "calls": c["calls"], "errors": c["errors"],
                  "ms_sum": c["ms_sum"]} for (b, a, r, t), c in acc.tools[grain].items()]
        await _upsert(session, TOOL_TABLES[grain], trows, ["project_id", "bucket", "agent_id", "role", "tool"],
                      add=["calls", "errors", "ms_sum"])
    urows = [{"project_id": pid, "day": day, "agent_id": agent, "user_key": user, "role": e["role"],
              **{k: e["c"].get(k, 0) for k in ("turns", "input_tokens", "output_tokens", "errors", "up", "down")},
              "first_seen_at": to_dt(e["first"]), "last_seen_at": to_dt(e["last"])}
             for (day, agent, user), e in acc.udaily.items()]
    await _count_active_days(session, pid, urows)
    await _upsert(session, agent_insight_users_daily, urows, ["project_id", "day", "agent_id", "user_key"],
                  add=["turns", "input_tokens", "output_tokens", "errors", "up", "down"], least=["first_seen_at"],
                  greatest=["last_seen_at"], follow=("last_seen_at", ["role"]))
    # the same counters by week (all agents together), so a long top list is weeks plus a few days (see agent_insights_people)
    weeks: dict[tuple, dict[str, Any]] = {}
    for r in urows:
        wk = (r["day"] - timedelta(days=r["day"].weekday()), r["user_key"])
        w = weeks.get(wk)
        if w is None:
            weeks[wk] = {"project_id": pid, "week": wk[0], "user_key": wk[1], "role": r["role"], "turns": r["turns"],
                         "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"], "errors": r["errors"], "up": r["up"],
                         "down": r["down"], "last_seen_at": r["last_seen_at"]}
        else:
            for k in ("turns", "input_tokens", "output_tokens", "errors", "up", "down"):
                w[k] += r[k]
            if r["last_seen_at"] >= w["last_seen_at"]:
                w["role"], w["last_seen_at"] = r["role"], r["last_seen_at"]
    await _upsert(session, agent_insight_users_weekly, list(weeks.values()), ["project_id", "week", "user_key"],
                  add=["turns", "input_tokens", "output_tokens", "errors", "up", "down"], greatest=["last_seen_at"],
                  follow=("last_seen_at", ["role"]))
    prows = [{"project_id": pid, "user_key": user, "role": e["role"], "first_seen_at": to_dt(e["first"]), "last_seen_at": to_dt(e["last"])}
             for user, e in acc.users.items()]
    await _upsert(session, agent_insight_users, prows, ["project_id", "user_key"], least=["first_seen_at"], greatest=["last_seen_at"],
                  follow=("last_seen_at", ["role"]))


async def _count_active_days(session: AsyncSession, pid: uuid.UUID, urows: list[dict[str, Any]]) -> None:
    """Keep "different people per day" as counters. A person-day is NEW only if its row did not exist, which the insert-or-ignore says
    exactly, so repeating a batch adds nothing. Counted four ways so any filter is one lookup: (agent or all agents) x (role or all roles)."""
    if not urows:
        return
    by_day_user: dict[tuple, dict[str, Any]] = {}
    for r in urows:
        cur = by_day_user.get((r["day"], r["user_key"]))
        if cur is None or r["last_seen_at"] >= cur["last_seen_at"]:
            by_day_user[(r["day"], r["user_key"])] = r
    new_days = await _insert_new(session, agent_insight_user_days,
                                 [{"project_id": pid, "day": d, "user_key": u} for d, u in by_day_user],
                                 ["project_id", "day", "user_key"], ("day", "user_key"))
    # the per-agent rows are made here empty (their counters are added after), which tells which person-days are new for that agent
    skeleton = [{"project_id": pid, "day": r["day"], "agent_id": r["agent_id"], "user_key": r["user_key"], "role": r["role"],
                 "first_seen_at": r["first_seen_at"], "last_seen_at": r["last_seen_at"]} for r in urows]
    new_agent_days = await _insert_new(session, agent_insight_users_daily, skeleton,
                                       ["project_id", "day", "agent_id", "user_key"], ("day", "agent_id", "user_key"))
    counts: Counter = Counter()
    for day, user in new_days:
        role = by_day_user[(day, user)]["role"]
        counts[(day, "*", role)] += 1
        counts[(day, "*", "*")] += 1
    for r in urows:
        if (r["day"], r["agent_id"], r["user_key"]) in new_agent_days:
            counts[(r["day"], r["agent_id"], r["role"])] += 1
            counts[(r["day"], r["agent_id"], "*")] += 1
    await _upsert(session, agent_insight_active_daily,
                  [{"project_id": pid, "day": d, "agent_id": a, "role": ro, "users": n} for (d, a, ro), n in counts.items()],
                  ["project_id", "day", "agent_id", "role"], add=["users"])


async def _trim_problems(session: AsyncSession, pid: uuid.UUID) -> None:
    p = agent_insight_problems
    keep_beyond = select(p.c.turn_id).where(p.c.project_id == pid).order_by(p.c.at.desc(), p.c.turn_id).offset(PROBLEMS_PER_PROJECT)
    await session.execute(delete(p).where(and_(p.c.project_id == pid, p.c.turn_id.in_(keep_beyond))))


# ---------------------------------------------------------------------------
# held thumbs
# ---------------------------------------------------------------------------

async def sweep_pending_ratings(session_factory, *, now: datetime | None = None) -> int:
    """Apply held thumbs whose turn has since arrived (a turn and its rating can be read by two workers at the same moment, and then the
    rating is held although the turn is a moment from existing). Returns how many were applied."""
    now = now or utcnow()
    p = agent_insight_pending_ratings
    async with session_factory() as s:
        projects = [r[0] for r in (await s.execute(select(p.c.project_id).distinct())).all()]
    done = 0
    for pid in projects:
        async with session_factory() as s, s.begin():
            await lock_project(s, pid)
            rows = (await s.execute(select(p).where(p.c.project_id == pid).limit(2000))).all()
            events = [{"t": "rating", "id": f"held-{r.turn_id}", "at": aware(r.at).timestamp(), "tid": r.turn_id, "v": r.rating,
                       "nt": r.note} for r in rows]
            acc, res = _Acc(now=now), ApplyResult()
            problems = await _apply_ratings(s, pid, events, acc, res, now)
            await _flush(s, pid, acc)
            if problems:
                await _trim_problems(s, pid)
            done += res.ratings_applied
    return done


# ---------------------------------------------------------------------------
# retention
# ---------------------------------------------------------------------------

async def _is_partitioned(session: AsyncSession) -> bool:
    if _dialect(session) != "postgresql":
        return False
    r = await session.execute(text("SELECT 1 FROM pg_partitioned_table pt JOIN pg_class c ON c.oid = pt.partrelid "
                                   "WHERE c.relname = 'agent_turn_events'"))
    return r.first() is not None


async def ensure_partitions(session: AsyncSession, *, today: date | None = None, back: int = RAW_RETENTION_DAYS, ahead: int = 7) -> list[str]:
    """Make sure each UTC day from ``back`` days ago to ``ahead`` days on has its partition of the raw table. A day that cannot be made
    (the default partition already holds rows for it) is logged and left: its events stay in the default partition, still correct,
    just removed by arrival date instead of by day."""
    if not await _is_partitioned(session):
        return []
    today = today or utcnow().date()
    have = {m.group(1) for (n,) in (await session.execute(text(
        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent "
        "WHERE p.relname = 'agent_turn_events'"))).all() if (m := _PARTITION_RE.match(n))}
    made = []
    for offset in range(-back, ahead + 1):
        day = today + timedelta(days=offset)
        if f"{day:%Y%m%d}" in have:
            continue
        nxt = day + timedelta(days=1)
        try:
            async with session.begin_nested():
                await session.execute(text(
                    f"CREATE TABLE IF NOT EXISTS agent_turn_events_p{day:%Y%m%d} PARTITION OF agent_turn_events "
                    f"FOR VALUES FROM ('{day} 00:00:00+00') TO ('{nxt} 00:00:00+00')"))
            made.append(f"{day}")
        except Exception as e:  # noqa: BLE001
            logger.warning("[insights] could not make the partition for %s: %s", day, e)
    return made


async def housekeeping(session_factory, *, now: datetime | None = None) -> dict[str, Any]:
    """Retention. Raw events 30 days (whole day partitions dropped), minute rollups 48 hours, hour rollups 90 days, day rollups 400 days,
    per-person-per-day rows 120 days, held thumbs 1 hour. Runs in one process at a time (a Postgres advisory lock). Returns what it did."""
    now = now or utcnow()
    out: dict[str, Any] = {}
    async with session_factory() as s, s.begin():
        if _dialect(s) == "postgresql":
            got = (await s.execute(text("SELECT pg_try_advisory_xact_lock(hashtextextended('forge-insights-housekeeping', 7))"))).scalar()
            if not got:
                return {"skipped": "another process is doing it"}
        out["partitions_made"] = await ensure_partitions(s, today=now.date())
        raw_cut = now - timedelta(days=RAW_RETENTION_DAYS)
        if await _is_partitioned(s):
            dropped = []
            for (name,) in (await s.execute(text(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent "
                    "WHERE p.relname = 'agent_turn_events'"))).all():
                m = _PARTITION_RE.match(name)
                if m and datetime.strptime(m.group(1), "%Y%m%d").date() < raw_cut.date():
                    await s.execute(text(f"DROP TABLE IF EXISTS {name}"))
                    dropped.append(name)
            out["partitions_dropped"] = dropped
            # events dated outside every day partition live in the default one: those go by arrival date
            await s.execute(text("DELETE FROM agent_turn_events_default WHERE received_at < :c"), {"c": raw_cut})
        else:
            r = await s.execute(delete(agent_turn_events).where(agent_turn_events.c.received_at < raw_cut))
            out["raw_rows_deleted"] = r.rowcount
        for grain in GRAINS:
            cut = now - timedelta(hours=GRAIN_RETENTION_HOURS[grain])
            for table in (ROLLUP_TABLES[grain], MODEL_TABLES[grain], TOOL_TABLES[grain]):
                await s.execute(delete(table).where(table.c.bucket < cut))
        await s.execute(delete(agent_insight_users_daily).where(
            agent_insight_users_daily.c.day < (now - timedelta(days=USERS_DAILY_RETENTION_DAYS)).date()))
        await s.execute(delete(agent_insight_users).where(
            agent_insight_users.c.last_seen_at < now - timedelta(days=USERS_RETENTION_DAYS)))
        await s.execute(delete(agent_insight_users_weekly).where(
            agent_insight_users_weekly.c.week < (now - timedelta(days=USERS_DAILY_RETENTION_DAYS + 10)).date()))
        await s.execute(delete(agent_insight_people_cache).where(agent_insight_people_cache.c.wanted_at < now - timedelta(days=1)))
        await s.execute(delete(agent_insight_user_days).where(
            agent_insight_user_days.c.day < (now - timedelta(days=USERS_DAILY_RETENTION_DAYS)).date()))
        await s.execute(delete(agent_insight_active_daily).where(
            agent_insight_active_daily.c.day < (now - timedelta(days=GRAIN_RETENTION_HOURS["day"] // 24)).date()))
        await s.execute(delete(agent_insight_problems).where(agent_insight_problems.c.at < now - timedelta(days=90)))
        await s.execute(delete(agent_insight_dropped).where(agent_insight_dropped.c.hour < now - timedelta(days=DROPPED_RETENTION_DAYS)))
        r = await s.execute(delete(agent_insight_pending_ratings).where(
            agent_insight_pending_ratings.c.received_at < now - PENDING_RATING_HOLD))
        out["held_ratings_expired"] = r.rowcount
    return out

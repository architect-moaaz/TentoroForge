"""Load test and capacity proof for the push-and-rollup agent insights.

It plays the part of many apps: N distinct users, spread over roles, agents, models and tools, send turns at a target rate; some turns get
a thumbs (a few changed later, a few sent BEFORE their turn), some conversations are handed to a person. Everything goes through the REAL
`POST /api/insights/ingest` route in realistic batches. The generator keeps the right answer as it goes (counters, not rows). When the
sending is over it waits for the worker to drain, asks the summary, and COMPARES every number to the right answer, then prints the
ingest latency, the rate it actually achieved, how far the worker fell behind, how long it took to catch up, and how long the summary took.

Two ways to run it:

  in-process   (default) imports the backend's FastAPI app and talks to it over an in-memory transport, with the worker running beside it.
               Pick the database with --database-url (a scratch Postgres is the meaningful one; omit it for a temporary SQLite file).
  against URL  --base-url https://host --key fik_... --project-id <uuid> --bearer <builder token>
               sends to a running platform and reads the summary route with the builder's token (no worker control, so no --kill-worker).

Examples (from the backend folder):
  python -m tools.insights_load_test --users 50000 --rate 2000 --duration 60 \\
      --database-url postgresql+asyncpg://scratch@127.0.0.1:5599/loadtest1 --create-schema
  python -m tools.insights_load_test --rate 500 --duration 20 --duplicates
  python -m tools.insights_load_test --rate 500 --duration 20 --kill-worker --consumers 1

`--create-schema` builds the insights tables in the database you named, and is refused unless its name starts with "loadtest": this tool
never writes into a database that could be anyone's real data. Exit status 0 only when every comparison matches.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import heapq
import json
import os
import random
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROLES = ["Admin", "Agent", "Manager", "Viewer", None]
AGENTS = ["support", "sales", "onboarding"]
MODELS = [("claude-sonnet-4-5", 60), ("claude-haiku-4-5", 35), (None, 5)]
TOOLS = ["lookup_order", "refund", "search_docs", "create_ticket", "send_email"]
HANDOFF_RANK = {"open": 0, "claimed": 1, "resolved": 2}


def iso_ms(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Truth:
    """The right answer, kept as counters while events are generated (so 100,000+ turns cost almost no memory)."""

    def __init__(self) -> None:
        self.turns = self.errors = self.blocked = self.handed_off = self.conversations = 0
        self.input_tokens = self.output_tokens = self.tool_calls = self.tool_errors = 0
        self.users: set[str] = set()
        self.by_role: dict[str, Counter] = defaultdict(Counter)
        self.by_model: dict[str, Counter] = defaultdict(Counter)
        self.tools: dict[str, Counter] = defaultdict(Counter)
        self.by_hour: dict[int, Counter] = defaultdict(Counter)
        self.by_minute: dict[int, Counter] = defaultdict(Counter)
        self.by_day: dict[str, Counter] = defaultdict(Counter)
        self.per_user: Counter = Counter()
        self.rated: dict[str, tuple[float, int, str, str, int]] = {}  # turn id -> (rating at, value, role, day, hour)
        self.turn_info: dict[str, tuple[str, str, int]] = {}            # only for turns that get rated: role, day, hour
        self.handoff_events: dict[tuple[str, str], list[tuple[float, str, float | None]]] = defaultdict(list)
        self.events_sent = 0
        self.first_ts: dict[str, float] = {}      # each person's first and last turn time: who was active and who was new in any window
        self.last_ts: dict[str, float] = {}
        self.day_role: Counter = Counter()        # (day, role) -> turns
        self.day_users: dict[str, set] = defaultdict(set)   # day -> people (kept for live days); history days use day_active_count
        self.day_active_count: dict[str, int] = {}

    def turn(self, ev: dict[str, Any], at: datetime, *, track: bool = True) -> None:
        self.turns += 1
        self.errors += ev["status"] == "error"
        self.blocked += ev["status"] == "blocked"
        self.handed_off += ev["handedOff"]
        self.conversations += ev["turnNumber"] == 1
        self.input_tokens += ev["inputTokens"]
        self.output_tokens += ev["outputTokens"]
        self.tool_calls += ev["toolCalls"]
        self.tool_errors += ev["toolErrors"]
        self.users.add(ev["userKey"])
        self.per_user[ev["userKey"]] += 1
        role = ev["role"] or ""
        r = self.by_role[role]
        r["turns"] += 1
        r["in"] += ev["inputTokens"]
        r["out"] += ev["outputTokens"]
        m = self.by_model[ev["model"] or "unknown"]
        m["turns"] += 1
        m["in"] += ev["inputTokens"]
        m["out"] += ev["outputTokens"]
        for t in ev["tools"]:
            c = self.tools[t["name"]]
            c["calls"] += 1
            c["errors"] += not t["ok"]
        ts = int(at.timestamp())
        hour, minute, day = ts // 3600 * 3600, ts // 60 * 60, at.date().isoformat()
        for table, key in ((self.by_hour, hour), (self.by_minute, minute), (self.by_day, day)):
            c = table[key]
            c["turns"] += 1
            c["errors"] += ev["status"] == "error"
            c["in"] += ev["inputTokens"]
            c["out"] += ev["outputTokens"]
        uk = ev["userKey"]
        if uk not in self.first_ts or ts < self.first_ts[uk]:
            self.first_ts[uk] = ts
        if ts > self.last_ts.get(uk, 0):
            self.last_ts[uk] = ts
        self.day_role[(day, role)] += 1
        if track:
            self.turn_info[ev["id"]] = (role, day, hour)
            self.day_users[day].add(uk)

    def rate(self, turn_id: str, value: int, at: datetime) -> None:
        cur = self.rated.get(turn_id)
        if cur is None or at.timestamp() >= cur[0]:
            self.rated[turn_id] = (at.timestamp(), value, "", "", 0)

    def handoff(self, ev: dict[str, Any], at: datetime) -> None:
        self.handoff_events[(ev["agentId"], ev["conversationId"])].append((at.timestamp(), ev["status"], ev["resolveMinutes"]))

    def finish(self) -> None:
        self.up = sum(1 for tid, v in self.rated.items() if v[1] == 1 and tid in self.turn_info)
        self.down = sum(1 for tid, v in self.rated.items() if v[1] == -1 and tid in self.turn_info)
        self.role_down: Counter = Counter()
        self.role_up: Counter = Counter()
        for tid, v in self.rated.items():
            if tid in self.turn_info:
                (self.role_down if v[1] == -1 else self.role_up)[self.turn_info[tid][0]] += 1
        self.handoffs: Counter = Counter()
        for evs in self.handoff_events.values():
            last = max(evs, key=lambda e: (e[0], HANDOFF_RANK[e[1]]))
            self.handoffs["total"] += 1
            self.handoffs[last[1]] += 1


class Generator:
    """Makes the events. Deterministic for a seed (except the wall-clock times, which are when they are made)."""

    def __init__(self, users: int, seed: int, rate_pct: float, handoff_pct: float) -> None:
        self.rng = random.Random(seed)
        self.users = users
        self.perm = list(range(users))
        self.rng.shuffle(self.perm)
        self.n = 0
        self.conv_seen: Counter = Counter()
        self.rate_pct, self.handoff_pct = rate_pct, handoff_pct
        self.truth = Truth()
        self.delayed: list[tuple[float, int, dict[str, Any], datetime]] = []  # (due, tiebreak, event, event time)
        self.seq = 0
        self.model_pool = [m for m, w in MODELS for _ in range(w)]

    def _user(self) -> int:
        # half the turns walk through everybody once (so a run with enough turns really touches every user), half are skewed to a few heavy users
        if self.rng.random() < 0.5:
            return self.perm[self.n % self.users]
        return min(self.users - 1, int(self.rng.paretovariate(1.2) * self.users / 40)) if self.rng.random() < 0.5 else self.rng.randrange(self.users)

    def turn(self, at: datetime) -> list[dict[str, Any]]:
        rng = self.rng
        i = self.n
        self.n += 1
        u = self._user()
        status = rng.choices(["ok", "error", "blocked"], [93, 4, 3])[0]
        model = None if status == "blocked" else rng.choice(self.model_pool)
        tools = [{"name": rng.choice(TOOLS), "ok": rng.random() > 0.1, "ms": rng.randrange(5, 800)} for _ in range(rng.choice([0, 0, 1, 1, 2, 3]))]
        conv = f"conv-{u}-{rng.randrange(4)}"
        self.conv_seen[conv] += 1
        ev = {
            "type": "turn", "id": f"lt-{i:09d}", "at": iso_ms(at), "agentId": AGENTS[rng.randrange(len(AGENTS))], "conversationId": conv,
            "userKey": f"{u:024x}", "role": ROLES[u % len(ROLES)], "env": "production", "model": model,
            "inputTokens": 0 if status == "blocked" else rng.randrange(200, 4000), "outputTokens": 0 if status == "blocked" else rng.randrange(20, 900),
            "ms": int(rng.lognormvariate(6.8, 0.9)), "status": status, "toolCalls": len(tools), "toolErrors": sum(not t["ok"] for t in tools),
            "tools": tools, "handedOff": rng.random() < 0.04, "turnNumber": self.conv_seen[conv],
            "problem": {"reason": "error", "message": "boom", "detail": None} if status == "error" else None,
        }
        at_trunc = datetime.strptime(ev["at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        self.truth.turn(ev, at_trunc)
        out = [ev]
        if rng.random() < self.rate_pct:
            first = rng.choice([1, -1])
            self._later(rng.random() * 0.4 if rng.random() < 0.05 else 1 + rng.random() * 7, self._rating(ev, first, 0, at_trunc))
            if rng.random() < 0.2:
                self._later(8 + rng.random() * 4, self._rating(ev, -first, 1, at_trunc))
        if rng.random() < self.handoff_pct:
            for step, (status_, delay, minutes) in enumerate((("open", 0.5, None), ("claimed", 3, None), ("resolved", 6, round(rng.uniform(2, 40), 1)))):
                if step == 2 and rng.random() < 0.3:
                    break
                self._later(delay, {"type": "handoff", "id": f"lh-{i:09d}-{step}", "at": "", "agentId": ev["agentId"], "conversationId": conv,
                                    "status": status_, "resolveMinutes": minutes})
        return out

    def history_turn(self, u: int, at: datetime, number: int, conv: str) -> dict[str, Any]:
        """One turn of the seeded history: a plain turn (no thumbs, no handoff, no problem text), recorded in the truth without per-turn bookkeeping."""
        rng = self.rng
        status = rng.choices(["ok", "error", "blocked"], [93, 4, 3])[0]
        model = None if status == "blocked" else rng.choice(self.model_pool)
        tools = [{"name": rng.choice(TOOLS), "ok": rng.random() > 0.1, "ms": rng.randrange(5, 800)}] if rng.random() < 0.4 else []
        ev = {
            "type": "turn", "id": f"lh-{self.n:09d}", "at": iso_ms(at), "agentId": AGENTS[rng.randrange(len(AGENTS))], "conversationId": conv,
            "userKey": f"{u:024x}", "role": ROLES[u % len(ROLES)], "env": "production", "model": model,
            "inputTokens": 0 if status == "blocked" else rng.randrange(200, 4000), "outputTokens": 0 if status == "blocked" else rng.randrange(20, 900),
            "ms": int(rng.lognormvariate(6.8, 0.9)), "status": status, "toolCalls": len(tools), "toolErrors": sum(not t["ok"] for t in tools),
            "tools": tools, "handedOff": rng.random() < 0.04, "turnNumber": number, "problem": None,
        }
        self.n += 1
        self.truth.turn(ev, datetime.strptime(ev["at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc), track=False)
        return ev

    def _rating(self, turn_ev: dict[str, Any], value: int, n: int, turn_at: datetime) -> dict[str, Any]:
        return {"type": "rating", "id": f"lr-{turn_ev['id'][3:]}-{n}", "at": "", "turnId": turn_ev["id"], "rating": value, "note": None}

    def _later(self, seconds: float, ev: dict[str, Any]) -> None:
        self.seq += 1
        heapq.heappush(self.delayed, (time.time() + seconds, self.seq, ev, datetime.now(timezone.utc)))

    def due(self, now: float, everything: bool = False) -> list[dict[str, Any]]:
        """Delayed events (thumbs, handoff steps) whose time has come; they take their time from the moment they are released."""
        out = []
        while self.delayed and (everything or self.delayed[0][0] <= now):
            _due, _s, ev, _made = heapq.heappop(self.delayed)
            at = datetime.now(timezone.utc)
            ev["at"] = iso_ms(at)
            at_trunc = datetime.strptime(ev["at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            if ev["type"] == "rating":
                self.truth.rate(ev["turnId"], ev["rating"], at_trunc)
            else:
                self.truth.handoff(ev, at_trunc)
            out.append(ev)
        return out


async def seed_history(a: argparse.Namespace, gen: Generator, pid: uuid.UUID, now: datetime, session_factory, store,
                       record: list | None = None, checkpoint=None) -> dict[str, Any]:
    """Fill the days before today with ``--daily-active`` people a day (about 1.1 turns each) straight into the rollup and person tables.

    The events are checked and shortened by the route's own ``normalize_event`` and added up by the writer's own ``_Acc.add_turn`` and
    ``_flush``, so the rows are exactly what ``apply_events`` would write for them; what is skipped is only the raw event rows (nothing the
    summary reads) and the problem feed. tests/services/test_agent_insights_people.py proves the two give identical tables."""
    from services import agent_insights_ingest as ingest_mod

    rng = random.Random(a.seed + 99)
    day0 = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    active = min(a.daily_active, a.users)
    t_start = time.time()
    seeded = 0
    pending: list[dict[str, Any]] = []

    async def flush() -> None:
        nonlocal pending
        if not pending:
            return
        async with session_factory() as s, s.begin():
            await store.lock_project(s, pid)
            acc = store._Acc(now=now)
            for ev in pending:
                acc.add_turn(str(pid), ev, None)
            await store._flush(s, pid, acc)
        pending = []

    # newest day first, so that after 30 and 60 days the data looks like a project with that much history (the ranges all end today)
    for back in range(1, a.seed_history_days):
        day_start = day0 - timedelta(days=back)
        population = rng.sample(range(a.users), active) if active < a.users else range(a.users)
        gen.truth.day_active_count[day_start.date().isoformat()] = active
        for u in population:
            for number in range(1, (2 if rng.random() < 0.1 else 1) + 1):
                at = day_start + timedelta(seconds=rng.random() * 86399)
                wire = gen.history_turn(u, at, number, f"conv-{u}-{back}")
                pending.append(ingest_mod.normalize_event(wire, now.timestamp()))
                if record is not None:
                    record.append(pending[-1])
                seeded += 1
            if len(pending) >= a.seed_chunk:
                await flush()
        await flush()
        done = back
        if checkpoint is not None and done in a.checkpoint_days:
            await checkpoint(done)
        if done % 5 == 0 or back == a.seed_history_days - 1:
            rate = seeded / max(time.time() - t_start, 1e-9)
            print(f"  seeded day {done}/{a.seed_history_days - 1}: {seeded} turns so far, {rate:.0f} turns/s", flush=True)
    return {"turns": seeded, "seconds": time.time() - t_start}


async def measure_ranges(pid: uuid.UUID, session_factory, summary_mod, people_mod, label: str) -> None:
    """Time the summary for each range COLD (no cache row), what the worker pays to refresh each view, WARM, and the old in-request full count."""
    from sqlalchemy import delete as _delete

    from models.agent_insights import agent_insight_people_cache as pc

    ranges = ("1h", "24h", "7d", "30d", "90d")
    async with session_factory() as s:
        await s.execute(_delete(pc))
        await s.commit()
    cold, partial = {}, {}
    for r in ranges:
        t0 = time.perf_counter()
        async with session_factory() as s:
            out = await summary_mod.build_summary(s, pid, range_=r, use_cache=True)
        cold[r] = (time.perf_counter() - t0) * 1000
        partial[r] = out["insights"]["users"]["topAsOf"] is None
    done = await people_mod.refresh_due(session_factory, force=True)
    refresh = {v["range"]: v["ms"] for v in done["views"]}
    warm, full = {}, {}
    for r in ranges:
        times = []
        for _ in range(4):
            t0 = time.perf_counter()
            async with session_factory() as s:
                await summary_mod.build_summary(s, pid, range_=r, use_cache=True)
            times.append((time.perf_counter() - t0) * 1000)
        warm[r] = sorted(times[1:])[1]                      # median of the last three (the first call pays for statement set-up)
        t0 = time.perf_counter()
        async with session_factory() as s:
            await summary_mod.build_summary(s, pid, range_=r, use_cache=False)
        full[r] = (time.perf_counter() - t0) * 1000
    print(f"\n== summary request time, {label} ==")
    print(f"  {'range':<6}{'COLD (no cache) ms':>20}{'WARM ms':>10}{'worker refresh ms':>20}{'full count in-request ms (old way)':>38}")
    for r in ranges:
        print(f"  {r:<6}{cold[r]:>20.0f}{warm[r]:>10.0f}{refresh.get(r, 0):>20}{full[r]:>38.0f}{'  (answered without the top list)' if partial[r] else ''}", flush=True)


async def measure_existing(session_factory, summary_mod, people_mod) -> int:
    """Time the summary on a database that already holds seeded history (no seeding, no live run), and check the people numbers against
    brute force over the DAILY person rows, which are independent of the weekly sums and of the cache."""
    from sqlalchemy import func, select, text

    from models.agent_insights import agent_insight_users_daily as ud
    from models.agent_insights import agent_insight_users_weekly as wk

    async with session_factory() as s:
        pid = (await s.execute(text("select project_id from agent_insight_keys limit 1"))).scalar()
        days = (await s.execute(select(func.count()).select_from(ud).where(ud.c.project_id == pid))).scalar()
        weeks = (await s.execute(select(func.count()).select_from(wk).where(wk.c.project_id == pid))).scalar()
        daily_turns = (await s.execute(select(func.sum(ud.c.turns)).where(ud.c.project_id == pid))).scalar()
        weekly_turns = (await s.execute(select(func.sum(wk.c.turns)).where(wk.c.project_id == pid))).scalar()
    print(f"person-day rows {days}, person-week rows {weeks}; turns in daily rows {daily_turns}, in weekly rows {weekly_turns}")
    bad = 0 if daily_turns == weekly_turns else 1
    await measure_ranges(pid, session_factory, summary_mod, people_mod, f"existing history ({days} person-days)")
    for r in ("7d", "30d", "90d"):
        async with session_factory() as s:
            g = (await summary_mod.build_summary(s, pid, range_=r, use_cache=True))["insights"]
            since = datetime.fromisoformat(g["since"].replace("Z", "+00:00"))
            brute = (await s.execute(select(ud.c.user_key, func.sum(ud.c.turns).label("n")).where((ud.c.project_id == pid) & (ud.c.day >= since.date()))
                                     .group_by(ud.c.user_key).order_by(func.sum(ud.c.turns).desc(), ud.c.user_key).limit(20))).all()
            per_day = {d.isoformat(): int(n) for d, n in (await s.execute(select(ud.c.day, func.count(func.distinct(ud.c.user_key))).where(
                (ud.c.project_id == pid) & (ud.c.day >= since.date())).group_by(ud.c.day))).all()}
            distinct = (await s.execute(select(func.count(func.distinct(ud.c.user_key))).where((ud.c.project_id == pid) & (ud.c.day >= since.date())))).scalar()
        ok_top = [(b.user_key, int(b.n)) for b in brute] == [(u["userKey"], u["turns"]) for u in g["users"]["top"]]
        ok_days = {d["day"]: d["active"] for d in g["users"]["activeByDay"] if d["active"]} == per_day
        ok_active = g["users"]["active"] == distinct
        print(f"{r}: top 20 == brute force over daily rows: {ok_top}; people per day == brute force: {ok_days}; different people == brute force: {ok_active}")
        bad += (not ok_top) + (not ok_days) + (not ok_active)
    print("RESULT:", "ALL PEOPLE NUMBERS MATCH BRUTE FORCE" if not bad else f"{bad} MISMATCH(ES)")
    return 1 if bad else 0


def pct(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


async def main_async(a: argparse.Namespace) -> int:
    in_process = not a.base_url
    consumers: list[Any] = []
    bus = None
    pid = uuid.uuid4()
    key = a.key
    engine_note = ""

    if in_process:
        if a.database_url:
            os.environ["DATABASE_URL"] = a.database_url
        else:
            # A file, not ":memory:": an in-memory SQLite database is ONE shared connection, and the worker, the request and the
            # chores would then commit and roll back each other's half-finished transactions.
            import tempfile as _tf

            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_tf.mkdtemp(prefix='loadtest-sqlite-')).as_posix()}/insights.db"
        os.environ["FORGE_INSIGHTS_WORKER"] = "0"
        os.environ.setdefault("SECRET_KEY", "loadtest")
        os.environ.setdefault("ANTHROPIC_API_KEY", "loadtest")
        os.environ["RATE_LIMIT_REQUESTS_PER_MINUTE"] = "100000000"
        os.environ["RATE_LIMIT_BURST"] = "100000000"
        import tempfile

        os.environ.setdefault("FORGE_OUTPUT_BASE", tempfile.mkdtemp(prefix="forge-loadtest-"))
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import dotenv

        dotenv.load_dotenv = lambda *args, **kwargs: False
        # SQLite has no JSONB/INET: the tests' shim, repeated, lets the whole model set be imported
        from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

        SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "TEXT"
        SQLiteTypeCompiler.visit_INET = lambda self, type_, **kw: "TEXT"
        SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"

        import models  # noqa: F401
        from database import Base, async_session, engine
        from services import agent_insights_bus as bus_mod
        from services import agent_insights_ingest as ingest_mod
        from services import agent_insights_keys as keys_mod
        from services import agent_insights_summary as summary_mod
        from services import agent_insights_worker as worker_mod

        dialect = engine.dialect.name
        engine_note = dialect
        await _prepare_schema(engine, Base, dialect, a)
        if a.bus == "memory":
            bus = bus_mod.MemoryBus()
            bus_mod.use_bus(bus)
        elif a.bus == "redis":
            bus_mod.reset_bus()
            bus = await bus_mod.get_bus()
            if bus is None:
                print("No Redis answered at REDIS_URL: use --bus memory or --bus none.")
                return 2
        else:
            bus_mod.use_bus(None)
        if a.measure_existing:
            from services import agent_insights_people as people_me

            return await measure_existing(async_session, summary_mod, people_me)
        if dialect == "postgresql" and a.create_schema:
            from sqlalchemy import text as _text

            async with engine.begin() as conn:  # the stub projects table this run made: one row for the project the key belongs to
                await conn.execute(_text("INSERT INTO projects (id) VALUES (:p)"), {"p": pid})
        async with async_session() as s:
            key, _prefix = await keys_mod.create_or_rotate(s, pid, None)
        ingest_mod.RATE_LIMITER = ingest_mod.KeyRateLimiter(rate=1e9, burst=1e9)  # this test measures the route, not the per-key limit
        import httpx
        from main import app

        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://loadtest", timeout=120)
        url = "/api/insights/ingest"

        def new_consumer(name: str):
            return worker_mod.InsightsWorker(consumer=name, block_ms=200, stale_ms=a.stale_ms, read_count=a.read_count)

        async def start_consumers(tag: str) -> None:
            if bus is None:
                return
            for k in range(a.consumers):
                w = new_consumer(f"lt-{tag}-{k}")
                consumers.append(w)
                w._stopping.clear()
                w._tasks = [asyncio.create_task(w._consume_loop(), name=f"consume-{tag}-{k}"),
                            asyncio.create_task(w._chores_loop(), name=f"chores-{tag}-{k}"),
                            asyncio.create_task(w._people_loop(), name=f"people-{tag}-{k}")] if k == 0 else \
                           [asyncio.create_task(w._consume_loop(), name=f"consume-{tag}-{k}")]

        if not a.hold_worker:
            await start_consumers("a")
    else:
        import httpx

        if not key:
            print("--key is needed with --base-url")
            return 2
        client = httpx.AsyncClient(base_url=a.base_url.rstrip("/"), timeout=120)
        url = "/api/insights/ingest"
        bus_mod = ingest_mod = summary_mod = worker_mod = None  # noqa: F841

        async def start_consumers(tag: str) -> None:
            return

    gen = Generator(a.users, a.seed, a.rating_pct, a.handoff_pct)
    seeded: dict[str, Any] | None = None
    now_dt = datetime.now(timezone.utc)
    if a.seed_history_days > 90:
        print("--seed-history-days counts today too and the platform accepts events up to 90 days old: use at most 90 (89 days of history)")
        return 2
    if a.seed_history_days:
        if not in_process:
            print("--seed-history-days needs the in-process mode with --database-url")
            return 2
        from services import agent_insights_store as store_seed

        print(f"seeding {a.seed_history_days - 1} days of history, {min(a.daily_active, a.users)} active people a day ...")
        async def checkpoint(days: int) -> None:
            from services import agent_insights_people as people_cp

            await measure_ranges(pid, async_session, summary_mod, people_cp, f"after {days} days of history ({min(a.daily_active, a.users) * days} person-days)")

        seeded = await seed_history(a, gen, pid, now_dt, async_session, store_seed, checkpoint=checkpoint)
        print(f"seeded {seeded['turns']} turns in {seeded['seconds']:.0f}s")
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    stats = {"lat": [], "ok_events": 0, "dups": 0, "rejected": 0, "retries": 0, "r429": 0, "r503": 0, "failed": 0, "sent_requests": 0, "bytes": 0}
    recent_bodies: list[bytes] = []
    rng = random.Random(a.seed + 1)

    async def sender() -> None:
        while True:
            body = await queue.get()
            if body is None:
                queue.task_done()
                return
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = body
            if a.gzip:
                payload = gzip.compress(body, 1)
                headers["Content-Encoding"] = "gzip"
            for attempt in range(60):
                t0 = time.perf_counter()
                try:
                    r = await client.post(url, content=payload, headers=headers)
                except Exception as e:  # noqa: BLE001
                    stats["failed"] += 1
                    print("request failed:", e)
                    await asyncio.sleep(0.5)
                    continue
                stats["lat"].append((time.perf_counter() - t0) * 1000)
                stats["sent_requests"] += 1
                stats["bytes"] += len(payload)
                if r.status_code == 202:
                    j = r.json()
                    stats["ok_events"] += j["accepted"]
                    stats["dups"] += j["duplicates"]
                    stats["rejected"] += j["rejectedCount"]
                    break
                if r.status_code in (429, 503):
                    stats["r429" if r.status_code == 429 else "r503"] += 1
                    stats["retries"] += 1
                    await asyncio.sleep(float(r.headers.get("retry-after", "1")))
                    continue
                print("unexpected answer", r.status_code, r.text[:200])
                stats["failed"] += 1
                break
            queue.task_done()

    senders = [asyncio.create_task(sender()) for _ in range(a.senders)]

    backlog_samples: list[tuple[float, int, int, int]] = []   # (time, stream entries waiting, turns applied, turns generated)
    applied_total = lambda: sum(w.applied_events for w in consumers)  # noqa: E731

    async def sampler() -> None:
        while True:
            depth = await bus.depth(0) if bus is not None else 0
            backlog_samples.append((time.time(), depth, applied_total(), gen.truth.turns))
            await asyncio.sleep(1.0)

    sampler_task = asyncio.create_task(sampler()) if bus is not None else None

    async def killer() -> None:
        await asyncio.sleep(a.duration * 0.4)
        print(f"[{time.strftime('%H:%M:%S')}] KILLING the worker(s) mid-run (cancelled in the middle of whatever they were doing)")
        for w in consumers:
            w._stopping.set()
            for t in w._tasks:
                t.cancel()
            await asyncio.gather(*w._tasks, return_exceptions=True)
        killed_applied[0] = applied_total()
        await asyncio.sleep(a.kill_gap)
        print(f"[{time.strftime('%H:%M:%S')}] restarting the worker(s)")
        await start_consumers("b")

    killed_applied = [0]
    kill_task = asyncio.create_task(killer()) if a.kill_worker and in_process and bus is not None else None
    if a.kill_worker and kill_task is None:
        print("--kill-worker needs the in-process mode with a stream (--bus memory or redis)")

    # ---- send ---------------------------------------------------------------------------------------------------
    print(f"sending ~{a.rate}/s for {a.duration}s from {a.users} users ({engine_note or 'url'}, bus={a.bus if in_process else 'n/a'}, batch={a.batch}, senders={a.senders})")
    t_start = time.time()
    produced = 0
    pending_events: list[dict[str, Any]] = []
    batches = 0

    async def flush(final: bool = False) -> None:
        nonlocal pending_events, batches
        while len(pending_events) >= a.batch or (final and pending_events):
            chunk, pending_events = pending_events[:a.batch], pending_events[a.batch:]
            body = json.dumps({"schema": 1, "events": chunk}).encode()
            batches += 1
            await queue.put(body)
            if a.duplicates:
                recent_bodies.append(body)
                if len(recent_bodies) > 300:
                    recent_bodies.pop(0)
                if rng.random() < 0.15 and len(recent_bodies) > 3:
                    await queue.put(rng.choice(recent_bodies))           # re-send of an earlier request, as a retrying app would

    tick = 0.05
    while True:
        now = time.time()
        elapsed = now - t_start
        if elapsed >= a.duration:
            break
        want = int(elapsed * a.rate) - produced
        for _ in range(max(0, want)):
            pending_events.extend(gen.turn(datetime.now(timezone.utc) - timedelta(milliseconds=rng.randrange(0, 1000))))
            produced += 1
        pending_events.extend(gen.due(now))
        await flush()
        await asyncio.sleep(max(0.0, tick - (time.time() - now)))
    pending_events.extend(gen.due(time.time(), everything=True))
    await flush(final=True)
    for _ in senders:
        await queue.put(None)
    await asyncio.gather(*senders)
    t_sent = time.time()
    if in_process and a.hold_worker:
        await start_consumers("a")        # only now: the backlog built while nobody was reading is what the workers are timed on
    send_seconds = t_sent - t_start

    # ---- wait for the worker -----------------------------------------------------------------------------------
    drain_seconds = 0.0
    if bus is not None:
        if kill_task:
            await kill_task
        deadline = time.time() + a.drain_timeout
        while time.time() < deadline and await bus.depth(0) > 0:
            await asyncio.sleep(0.25)
        drain_seconds = time.time() - t_sent
        if await bus.depth(0) > 0:
            print("WARNING: the worker did not drain the stream in time")
        # held thumbs whose turn is applied by another consumer a moment later are swept every few seconds
        await asyncio.sleep(0.5)
    if in_process:
        from services import agent_insights_store as store_mod

        for _ in range(3):
            await store_mod.sweep_pending_ratings(async_session)
        await ingest_mod.DROPPED.flush()
        await keys_mod.flush_touches()
    if sampler_task:
        sampler_task.cancel()
    gen.truth.finish()
    truth = gen.truth

    # ---- ask the summary ----------------------------------------------------------------------------------------
    results: list[tuple[str, Any, Any, bool]] = []
    timings: dict[str, float] = {}
    insights: dict[str, dict[str, Any]] = {}

    async def fetch(range_: str) -> dict[str, Any] | None:
        t0 = time.perf_counter()
        if in_process:
            async with async_session() as s:
                out = await summary_mod.build_summary(s, pid, range_=range_, use_cache=True)
        else:
            if not (a.project_id and a.bearer):
                return None
            r = await client.get(f"/api/projects/{a.project_id}/agent-definitions/insights/summary", params={"range": range_},
                                 headers={"Authorization": f"Bearer {a.bearer}"})
            out = r.json()
        timings[range_] = (time.perf_counter() - t0) * 1000
        if not out.get("ok"):
            print("summary said:", out)
            return None
        return out["insights"]

    summary_first: dict[str, float] = {}
    if not in_process and a.project_id and a.bearer:
        # a remote worker is not ours to watch: wait until the summary has caught up with what was sent
        deadline = time.time() + a.drain_timeout
        while time.time() < deadline:
            got = await fetch("24h")
            if got and got["totals"]["turns"] >= truth.turns:
                break
            await asyncio.sleep(1.0)
        drain_seconds = time.time() - t_sent
    ranges5 = ("1h", "24h", "7d", "30d", "90d")
    cold_ms: dict[str, float] = {}
    cold_partial: dict[str, bool] = {}
    refresh_ms: dict[str, int] = {}
    uncached_ms: dict[str, float] = {}
    if in_process:
        from sqlalchemy import delete as _delete

        from models.agent_insights import agent_insight_people_cache as _people_cache
        from services import agent_insights_people as people_mod

        async with async_session() as s_:
            await s_.execute(_delete(_people_cache))
            await s_.commit()
        for r_ in ranges5:                                # COLD: no cache row yet; the request works it out inside its short limit or answers without
            t0 = time.perf_counter()
            async with async_session() as s_:
                out_ = await summary_mod.build_summary(s_, pid, range_=r_, use_cache=True)
            cold_ms[r_] = (time.perf_counter() - t0) * 1000
            cold_partial[r_] = out_["insights"]["users"]["topAsOf"] is None
        done_ = await people_mod.refresh_due(async_session, force=True)   # what the worker pays to work every view out
        for v_ in done_["views"]:
            refresh_ms[v_["range"]] = v_["ms"]
        for r_ in ranges5:                                # for reference: the same numbers counted in full inside the request (the old way)
            t0 = time.perf_counter()
            async with async_session() as s_:
                await summary_mod.build_summary(s_, pid, range_=r_, use_cache=False)
            uncached_ms[r_] = (time.perf_counter() - t0) * 1000
    for rng_name in ranges5:
        got = await fetch(rng_name)
        if got:
            insights[rng_name] = got
            await fetch(rng_name)                        # the first call also pays for connection setup; the second is the steady cost
            summary_first[rng_name] = timings[rng_name]

    def cmp(name: str, expected: Any, got: Any, tol: float = 0.0) -> None:
        ok = (got == expected) if not tol else (abs(got - expected) <= tol * max(1, expected))
        results.append((name, expected, got, ok))

    ins = insights.get("24h") if not seeded else None
    if ins:
        t = ins["totals"]
        cmp("turns", truth.turns, t["turns"])
        cmp("input tokens", truth.input_tokens, t["inputTokens"])
        cmp("output tokens", truth.output_tokens, t["outputTokens"])
        cmp("errors", truth.errors, t["errors"])
        cmp("blocked", truth.blocked, t["blocked"])
        cmp("ok (turns - errors - blocked)", truth.turns - truth.errors - truth.blocked, t["turns"] - t["errors"] - t["blocked"])
        cmp("handed off", truth.handed_off, t["handedOff"])
        cmp("conversations", truth.conversations, t["conversations"])
        cmp("tool calls", truth.tool_calls, t["toolCalls"])
        cmp("tool errors", truth.tool_errors, t["toolErrors"])
        cmp("thumbs up", truth.up, t["up"])
        cmp("thumbs down", truth.down, t["down"])
        cmp("distinct users (exact; allowed 1%)", len(truth.users), ins["users"]["active"], tol=0.01)
        cmp("distinct users (exact match)", len(truth.users), ins["users"]["active"])
        roles = {r["role"]: r for r in ins["users"]["byRole"]}
        for role, c in sorted(truth.by_role.items()):
            name = role or "(no role)"
            cmp(f"turns of role {name}", c["turns"], roles.get(name, {}).get("turns"))
        cmp("tokens by model", {m: (c["turns"], c["in"], c["out"]) for m, c in truth.by_model.items() if c["in"] or c["out"]},
            {m["model"]: (m["turns"], m["inputTokens"], m["outputTokens"]) for m in ins["byModel"]})
        cmp("tool calls by tool", {k: (c["calls"], c["errors"]) for k, c in truth.tools.items()}, {x["name"]: (x["calls"], x["errors"]) for x in ins["tools"]})
        cmp("series (hourly) turns sum", truth.turns, sum(p["turns"] for p in ins["series"]))
        cmp("series (hourly) per bucket", {k: c["turns"] for k, c in truth.by_hour.items()},
            {int(datetime.fromisoformat(p["t"].replace("Z", "+00:00")).timestamp()): p["turns"] for p in ins["series"] if p["turns"]})
        cmp("handoffs total/open/claimed/resolved", (truth.handoffs["total"], truth.handoffs["open"], truth.handoffs["claimed"], truth.handoffs["resolved"]),
            (ins["handoffs"]["total"], ins["handoffs"]["open"], ins["handoffs"]["claimed"], ins["handoffs"]["resolved"]))
        for role, c in sorted(truth.by_role.items()):
            name = role or "(no role)"
            rated = truth.role_up[role] + truth.role_down[role]
            want = round(100.0 * truth.role_down[role] / rated, 1) if rated else None
            cmp(f"thumbs-down % of role {name}", want, roles.get(name, {}).get("thumbsDownPct"))
        cmp("freshness has a last event", True, ins["freshness"]["lastEventAt"] is not None)
        cmp("dropped events", stats["rejected"], ins["droppedEvents"])
    m1 = insights.get("1h") if not seeded else None
    if m1:
        cmp("1h: minute series sum", truth.turns, sum(p["turns"] for p in m1["series"]))
        cmp("1h: minute series per bucket", {k: c["turns"] for k, c in truth.by_minute.items()},
            {int(datetime.fromisoformat(p["t"].replace("Z", "+00:00")).timestamp()): p["turns"] for p in m1["series"] if p["turns"]})
    for rng_name in ("7d", "30d", "90d"):
        g = insights.get(rng_name) if not seeded else None
        if g:
            cmp(f"{rng_name}: turns", truth.turns, g["totals"]["turns"])
            cmp(f"{rng_name}: byDay sums", (truth.turns, truth.input_tokens, truth.output_tokens),
                (sum(d["turns"] for d in g["byDay"]), sum(d["inputTokens"] for d in g["byDay"]), sum(d["outputTokens"] for d in g["byDay"])))
            cmp(f"{rng_name}: series (daily) turns sum", truth.turns, sum(p["turns"] for p in g["series"]))
            if rng_name == "7d":
                top = sorted(truth.per_user.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
                cmp("7d: top 20 users by turns", [(k, v) for k, v in top], [(u["userKey"], u["turns"]) for u in g["users"]["top"]])
            cmp(f"{rng_name}: distinct users", len(truth.users), g["users"]["active"])

    if seeded:
        # With history the whole run is not inside one window, so each range is checked against the truth tables for ITS window.
        from sqlalchemy import func as _func, select as _select

        from models.agent_insights import agent_insight_users_daily as _ud

        for rng_name, g in insights.items():
            since = datetime.fromisoformat(g["since"].replace("Z", "+00:00"))
            grain = g["granularity"]
            table = {"minute": truth.by_minute, "hour": truth.by_hour}.get(grain)
            if table is not None:
                want = [sum(c[k] for ts_, c in table.items() if ts_ >= since.timestamp()) for k in ("turns", "in", "out", "errors")]
            else:
                want = [sum(c[k] for d_, c in truth.by_day.items() if d_ >= since.date().isoformat()) for k in ("turns", "in", "out", "errors")]
            t = g["totals"]
            cmp(f"{rng_name}: turns / tokens in / out / errors", tuple(want), (t["turns"], t["inputTokens"], t["outputTokens"], t["errors"]))
            cmp(f"{rng_name}: series turns sum", want[0], sum(p["turns"] for p in g["series"]))
            ts0 = since.timestamp()
            cmp(f"{rng_name}: different people", sum(1 for v in truth.last_ts.values() if v >= ts0), g["users"]["active"])
            cmp(f"{rng_name}: new people", sum(1 for v in truth.first_ts.values() if v >= ts0), g["users"]["newUsers"])
            if rng_name in ("7d", "30d", "90d"):
                days = {d["day"]: d["active"] for d in g["users"]["activeByDay"]}
                want_days = {d: (truth.day_active_count.get(d) if d in truth.day_active_count else len(truth.day_users.get(d, ())))
                             for d in days}
                cmp(f"{rng_name}: people per day (all days)", {d: v for d, v in want_days.items() if v}, {d: v for d, v in days.items() if v})
                roles = {r_["role"]: r_["turns"] for r_ in g["users"]["byRole"]}
                want_roles = Counter()
                for (d_, role_), n_ in truth.day_role.items():
                    if d_ >= since.date().isoformat():
                        want_roles[role_ or "(no role)"] += n_
                cmp(f"{rng_name}: turns per role", dict(want_roles), roles)
            cmp(f"{rng_name}: top list was worked out (topAsOf set)", True, g["users"]["topAsOf"] is not None)
            if in_process and rng_name in ("7d", "30d", "90d"):
                async with async_session() as s_:   # brute force over the DAILY rows, independent of the weekly sums and the cache
                    brute = (await s_.execute(_select(_ud.c.user_key, _func.sum(_ud.c.turns).label("n")).where(
                        (_ud.c.project_id == pid) & (_ud.c.day >= since.date())).group_by(_ud.c.user_key)
                        .order_by(_func.sum(_ud.c.turns).desc(), _ud.c.user_key).limit(20))).all()
                cmp(f"{rng_name}: top 20 users (vs brute force over daily rows)", [(r_.user_key, int(r_.n)) for r_ in brute],
                    [(u["userKey"], u["turns"]) for u in g["users"]["top"]])

    # ---- report -------------------------------------------------------------------------------------------------
    lat = sorted(stats["lat"])
    sent_turns = truth.turns - (seeded["turns"] if seeded else 0)
    print()
    print("=" * 78)
    print(f"{'check':<46}{'expected':>14}{'got':>14}  result")
    bad = 0
    for name, exp, got, ok in results:
        bad += not ok
        e = str(exp) if len(str(exp)) < 13 else str(exp)[:10] + "..."
        g = str(got) if len(str(got)) < 13 else str(got)[:10] + "..."
        print(f"{name:<46}{e:>14}{g:>14}  {'ok' if ok else 'MISMATCH'}")
    print("=" * 78)
    achieved = sent_turns / send_seconds if send_seconds else 0
    print(f"turns generated and shipped: {sent_turns}  (+ ratings/handoffs: {stats['ok_events'] + stats['dups'] - sent_turns} accepted extra)")
    print(f"distinct users: {len(truth.users)}   requests: {stats['sent_requests']}  batch size: {a.batch}  gzip: {a.gzip}")
    print(f"offered rate: {a.rate}/s   achieved: {achieved:.0f} turns/s over {send_seconds:.1f}s   ({(stats['ok_events'] + stats['dups']) / max(send_seconds, 1e-9):.0f} events/s incl. ratings)")
    print(f"ingest latency ms  p50 {pct(lat, 0.5):.1f}   p90 {pct(lat, 0.9):.1f}   p99 {pct(lat, 0.99):.1f}   max {lat[-1] if lat else float('nan'):.1f}   (n={len(lat)})")
    print(f"answers: 202 accepted events={stats['ok_events']} duplicates reported={stats['dups']} rejected={stats['rejected']}  429s={stats['r429']}  503s={stats['r503']}  failed={stats['failed']}")
    if bus is not None:
        peak = max((d for _t, d, _a, _g in backlog_samples), default=0)
        lag_events = max(((made - ap) for _t, _d, ap, made in backlog_samples), default=0)
        print(f"worker: consumers={a.consumers}  peak backlog {peak} stream entries (~{peak * a.batch} events)  most turns generated-but-not-yet-applied at any moment (includes requests still waiting to be sent): {lag_events}  "
              f"drain after last request: {drain_seconds:.1f}s")
        if a.hold_worker and drain_seconds > 0:
            print(f"worker drain throughput (workers started after all sending): {(stats['ok_events'] + stats['dups']) / drain_seconds:.0f} events/s")
        if kill_task:
            print(f"worker was killed mid-run (had applied {killed_applied[0]} new turns) and restarted after {a.kill_gap}s")
    if cold_ms:
        print()
        print("summary request time by range:")
        print(f"  {'range':<6}{'COLD (no cache) ms':>20}{'WARM ms':>10}{'worker refresh ms':>20}{'full count in-request ms (old way)':>38}")
        for r_ in ranges5:
            note = "  (answered without the top list)" if cold_partial.get(r_) else ""
            print(f"  {r_:<6}{cold_ms[r_]:>20.0f}{summary_first.get(r_, float('nan')):>10.0f}{refresh_ms.get(r_, 0):>20}{uncached_ms[r_]:>38.0f}{note}")
        print("  (the 1h and 24h views share one sum, so the second of them shows less refresh time)")
    else:
        for rng_name, ms in summary_first.items():
            print(f"summary query {rng_name:>4}: {ms:.0f} ms (warm)")
    if in_process:
        async with async_session() as s:
            from sqlalchemy import func, select
            from models.agent_insights import ROLLUP_TABLES, agent_insight_users_daily, agent_turn_events

            raw_n = (await s.execute(select(func.count()).select_from(agent_turn_events))).scalar()
            minute_n = (await s.execute(select(func.count()).select_from(ROLLUP_TABLES["minute"]))).scalar()
            ud_n = (await s.execute(select(func.count()).select_from(agent_insight_users_daily))).scalar()
        print(f"rows: raw events {raw_n}, minute rollup rows {minute_n}, per-user-per-day rows {ud_n}")
        cmp_raw = raw_n == truth.turns - (seeded["turns"] if seeded else 0)
        print(f"raw rows equal turns shipped: {'yes' if cmp_raw else 'NO'}")
        bad += not cmp_raw
    print("RESULT:", "ALL NUMBERS MATCH GROUND TRUTH" if not bad else f"{bad} MISMATCH(ES)")
    if a.report:
        Path(a.report).write_text(json.dumps({"checks": [{"name": n, "ok": ok} for n, _e, _g, ok in results], "achieved_turns_per_s": achieved,
                                              "latency_ms": {"p50": pct(lat, .5), "p99": pct(lat, .99)}, "drain_s": drain_seconds,
                                              "summary_ms": summary_first}, indent=1))

    for w in consumers:
        w._stopping.set()
        for t in w._tasks:
            t.cancel()
        await asyncio.gather(*w._tasks, return_exceptions=True)
    await client.aclose()
    return 1 if bad else 0


async def _prepare_schema(engine, Base, dialect: str, a: argparse.Namespace) -> None:
    """Build the insights tables in a scratch database. Refused unless the database's name starts with "loadtest" (or it is in-memory SQLite)."""
    from sqlalchemy import text

    insight_tables = [t for n, t in Base.metadata.tables.items() if "insight" in n or n == "agent_turn_events"]
    if dialect == "sqlite":
        async with engine.begin() as conn:
            await conn.run_sync(lambda cn: Base.metadata.create_all(cn, tables=insight_tables))
        return
    name = engine.url.database or ""
    if not a.create_schema:
        return
    if not name.startswith("loadtest"):
        raise SystemExit(f"Refusing --create-schema: the database '{name}' does not start with 'loadtest', so it might be somebody's real data.")
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    mig_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "ai1022_agent_insights_stream.py"
    spec = importlib.util.spec_from_file_location("ai1022", mig_path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    def build(cn):
        for t in reversed(insight_tables):
            t.drop(cn, checkfirst=True)
        cn.execute(text("DROP TABLE IF EXISTS agent_turn_events CASCADE"))
        cn.execute(text("CREATE TABLE IF NOT EXISTS projects (id uuid PRIMARY KEY)"))   # the key table's foreign key needs something to point at
        Base.metadata.create_all(cn, tables=[t for t in insight_tables if t.name != "agent_turn_events"])
        with Operations.context(MigrationContext.configure(cn)):
            mig._create_events_table()  # the real migration's partitioned table, the one production gets

    async with engine.begin() as conn:
        await conn.run_sync(build)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--users", type=int, default=50_000, help="distinct users (default 50000)")
    p.add_argument("--rate", type=float, default=2000, help="turns per second to offer (default 2000)")
    p.add_argument("--duration", type=float, default=60, help="seconds of sending (default 60)")
    p.add_argument("--batch", type=int, default=100, help="events per request (an app sends up to 100 a second; default 100)")
    p.add_argument("--senders", type=int, default=4, help="requests in flight at once (default 4)")
    p.add_argument("--gzip", action="store_true", help="gzip the request bodies")
    p.add_argument("--duplicates", action="store_true", help="also re-send about 15%% of the requests, as retrying apps do")
    p.add_argument("--kill-worker", action="store_true", help="stop the worker(s) abruptly 40%% into the run and restart them --kill-gap seconds later")
    p.add_argument("--kill-gap", type=float, default=8.0)
    p.add_argument("--hold-worker", action="store_true", help="start the worker(s) only after all sending is done: times the ingest route alone, then the worker alone")
    p.add_argument("--stale-ms", type=int, default=3000, help="idle time before another worker takes over an unfinished entry (production: 30000)")
    p.add_argument("--consumers", type=int, default=2, help="worker consumers (the backend runs 2 processes; default 2)")
    p.add_argument("--read-count", type=int, default=40, help="stream entries a worker takes per pass")
    p.add_argument("--bus", choices=["memory", "redis", "none"], default="memory",
                   help="in-process mode: in-memory stream (default), real Redis from REDIS_URL, or none (events applied in the request)")
    p.add_argument("--rating-pct", type=float, default=0.08, help="share of turns that get a thumbs (default 0.08)")
    p.add_argument("--handoff-pct", type=float, default=0.02)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--drain-timeout", type=float, default=900)
    p.add_argument("--database-url", help="in-process: the database (default: in-memory SQLite)")
    p.add_argument("--create-schema", action="store_true", help="build the insights tables in --database-url (its name must start with 'loadtest')")
    p.add_argument("--base-url", help="send to a running platform instead of running one in-process")
    p.add_argument("--key", help="the project's ingest key (with --base-url)")
    p.add_argument("--project-id", help="with --base-url: the project, to read the summary route")
    p.add_argument("--bearer", help="with --base-url: a builder's access token, to read the summary route")
    p.add_argument("--seed-history-days", type=int, default=0, help="first fill this many days of history (in-process, needs --database-url)")
    p.add_argument("--daily-active", type=int, default=50_000, help="with --seed-history-days: people active on each seeded day (default 50000)")
    p.add_argument("--checkpoint-days", type=lambda v: [int(x) for x in v.split(",") if x], default=[],
                   help="with --seed-history-days: measure the summary after seeding this many days, e.g. 30,60 (newest days are seeded first)")
    p.add_argument("--measure-existing", action="store_true", help="time the summary on a database that already holds seeded history, and check the people numbers against brute force")
    p.add_argument("--seed-chunk", type=int, default=25_000, help="turns per seeding transaction")
    p.add_argument("--report", help="write a small JSON report here")
    return p.parse_args(argv)


def main() -> None:
    sys.exit(asyncio.run(main_async(parse_args())))


if __name__ == "__main__":
    main()

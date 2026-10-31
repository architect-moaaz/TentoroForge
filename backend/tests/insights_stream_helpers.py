"""Shared pieces for the push-and-rollup insights tests: events as an app sends them, and a brute-force "what should the numbers be".

``Truth`` answers the same questions the summary does, but by looping over the raw events with plain Python, no rollups and no SQL.
If the rollups and this ever disagree, the rollups are wrong (or this is: keep it dull and obvious).
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from services import agent_insights_ingest as ingest

#: A fixed "now" for the tests, in the middle of a minute, an hour and a day so no window edge sits on it.
NOW = datetime(2026, 10, 22, 12, 30, 30, tzinfo=timezone.utc)

ROLES = ["Admin", "Agent", "Manager", None]
MODELS = ["claude-sonnet-4-5", "claude-haiku-4-5"]
TOOLS = ["lookup_order", "refund", "search_docs"]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def user_key(n: int) -> str:
    return f"{n:032x}"


def turn(i: int, at: datetime, *, user: int = 1, agent: str = "support", role: str | None = "Admin", model: str | None = "claude-sonnet-4-5",
         inp: int = 100, out: int = 20, ms: int = 800, status: str = "ok", tools: list[dict] | None = None, handed_off: bool = False,
         turn_number: int = 1, problem: dict | None = None, conv: str | None = None, env: str = "production") -> dict[str, Any]:
    tools = tools or []
    return {
        "type": "turn", "id": f"turn-{i:08d}", "at": iso(at), "agentId": agent, "conversationId": conv or f"conv-{i // 3}",
        "userKey": user_key(user), "role": role, "env": env, "model": model, "inputTokens": inp, "outputTokens": out, "ms": ms,
        "status": status, "toolCalls": len(tools), "toolErrors": sum(1 for t in tools if not t["ok"]), "tools": tools,
        "handedOff": handed_off, "turnNumber": turn_number, "problem": problem,
    }


def rating(turn_i: int, value: int, at: datetime, *, n: int = 0, note: str | None = None) -> dict[str, Any]:
    return {"type": "rating", "id": f"rate-{turn_i:08d}-{n}", "at": iso(at), "turnId": f"turn-{turn_i:08d}", "rating": value, "note": note}


def handoff(conv: str, status: str, at: datetime, *, agent: str = "support", minutes: float | None = None, n: int = 0) -> dict[str, Any]:
    return {"type": "handoff", "id": f"hand-{conv}-{status}-{n}"[:64], "at": iso(at), "agentId": agent, "conversationId": conv, "status": status,
            "resolveMinutes": minutes}


def norm(events: list[dict[str, Any]], now: datetime = NOW) -> list[dict[str, Any]]:
    """The events in their short form, exactly as the ingest route would hand them on (every one must be valid)."""
    return [ingest.normalize_event(e, now.timestamp()) for e in events]


def random_events(rng: random.Random, *, turns: int, users: int, hours: float = 40.0, days_back: float = 0.0, agents: tuple[str, ...] = ("support", "sales"),
                  now: datetime = NOW) -> list[dict[str, Any]]:
    """A mixed batch: turns spread over the last ``hours`` hours (and some up to ``days_back`` days), some errors, tools, handoffs, problems,
    thumbs (some changed later), in shuffled order, with a few duplicates."""
    out: list[dict[str, Any]] = []
    conv_turn: Counter = Counter()
    for i in range(turns):
        age = rng.random() * (days_back * 86400 if days_back and rng.random() < 0.3 else hours * 3600)
        at = now - timedelta(seconds=age)
        u = rng.randrange(users)
        role = ROLES[u % len(ROLES)]
        status = rng.choices(["ok", "error", "blocked"], [90, 6, 4])[0]
        tools = [{"name": rng.choice(TOOLS), "ok": rng.random() > 0.15, "ms": rng.randrange(5, 900)} for _ in range(rng.choice([0, 0, 1, 2, 3]))]
        conv = f"conv-{u}-{rng.randrange(3)}"
        conv_turn[conv] += 1
        problem = {"reason": "error", "message": f"boom {i}", "detail": None} if status == "error" else None
        out.append(turn(i, at, user=u, agent=rng.choice(agents), role=role, model=rng.choice(MODELS + [None]) if status != "blocked" else None,
                        inp=rng.randrange(0, 3000), out=rng.randrange(0, 800), ms=int(rng.lognormvariate(6.5, 1.0)), status=status, tools=tools,
                        handed_off=rng.random() < 0.05, turn_number=1 if conv_turn[conv] == 1 else 2, problem=problem, conv=conv))
    for i in range(0, turns, 5):
        t_at = _dt(out[i]["at"])
        first = rng.choice([1, -1])
        out.append(rating(i, first, t_at + timedelta(seconds=30), n=0))
        if rng.random() < 0.4:
            out.append(rating(i, -first, t_at + timedelta(seconds=90), n=1))
    for c in range(0, 12):
        base = now - timedelta(minutes=15 + rng.random() * (hours * 60 - 15))   # 15 minutes of room for its later steps
        conv = f"conv-h{c}"
        out.append(handoff(conv, "open", base, n=0))
        if rng.random() < 0.7:
            out.append(handoff(conv, "claimed", base + timedelta(minutes=3)))
        if rng.random() < 0.5:
            out.append(handoff(conv, "resolved", base + timedelta(minutes=9), minutes=rng.choice([9.0, 12.5, 30.0])))
    out.extend(rng.sample(out, min(25, len(out))))  # the same events sent twice
    rng.shuffle(out)
    return out


# ---------------------------------------------------------------------------
# brute force
# ---------------------------------------------------------------------------

def window_start(now: datetime, range_: str) -> datetime:
    if range_ == "1h":
        return (now - timedelta(hours=1)).replace(second=0, microsecond=0)
    if range_ == "24h":
        return (now - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    days = {"7d": 7, "30d": 30, "90d": 90}[range_]
    return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Truth:
    """The right answer by looping over every raw event."""

    def __init__(self, events: list[dict[str, Any]], now: datetime = NOW, range_: str = "24h", agent: str | None = None, role: str | None = None) -> None:
        since = window_start(now, range_)
        turns: dict[str, dict[str, Any]] = {}
        for e in events:
            if e["type"] == "turn" and e["id"] not in turns:
                turns[e["id"]] = e
        final: dict[str, tuple[datetime, int]] = {}
        for e in events:
            if e["type"] == "rating" and e["turnId"] in turns:
                cur = final.get(e["turnId"])
                at = _dt(e["at"])
                if cur is None or at >= cur[0]:
                    final[e["turnId"]] = (at, e["rating"])
        sel = [t for t in turns.values() if _dt(t["at"]) >= since and (agent is None or t["agentId"] == agent)
               and (role is None or (t["role"] or "") == role)]
        self.since, self.turns_list = since, sel
        self.turns = len(sel)
        self.errors = sum(t["status"] == "error" for t in sel)
        self.blocked = sum(t["status"] == "blocked" for t in sel)
        self.handed_off = sum(t["handedOff"] for t in sel)
        self.conversations = sum(t["turnNumber"] == 1 for t in sel)
        self.input_tokens = sum(t["inputTokens"] for t in sel)
        self.output_tokens = sum(t["outputTokens"] for t in sel)
        self.tool_calls = sum(t["toolCalls"] for t in sel)
        self.tool_errors = sum(t["toolErrors"] for t in sel)
        self.up = sum(final.get(t["id"], (None, 0))[1] == 1 for t in sel)
        self.down = sum(final.get(t["id"], (None, 0))[1] == -1 for t in sel)
        self.users = {t["userKey"] for t in sel}
        self.by_role: dict[str, Counter] = defaultdict(Counter)
        self.by_model: dict[str, Counter] = defaultdict(Counter)
        self.tools: dict[str, Counter] = defaultdict(Counter)
        self.by_hour: dict[datetime, Counter] = defaultdict(Counter)
        self.by_day: dict[str, Counter] = defaultdict(Counter)
        self.per_user: dict[str, Counter] = defaultdict(Counter)
        for t in sel:
            r = self.by_role[t["role"] or ""]
            r["turns"] += 1
            r["in"] += t["inputTokens"]
            r["out"] += t["outputTokens"]
            r["down"] += final.get(t["id"], (None, 0))[1] == -1
            r["up"] += final.get(t["id"], (None, 0))[1] == 1
            m = self.by_model[t["model"] or "unknown"]
            m["turns"] += 1
            m["in"] += t["inputTokens"]
            m["out"] += t["outputTokens"]
            for tool in t["tools"]:
                c = self.tools[tool["name"]]
                c["calls"] += 1
                c["errors"] += not tool["ok"]
            at = _dt(t["at"])
            h = self.by_hour[at.replace(minute=0, second=0, microsecond=0)]
            h["turns"] += 1
            h["errors"] += t["status"] == "error"
            h["in"] += t["inputTokens"]
            h["out"] += t["outputTokens"]
            d = self.by_day[at.date().isoformat()]
            d["turns"] += 1
            d["errors"] += t["status"] == "error"
            d["in"] += t["inputTokens"]
            d["out"] += t["outputTokens"]
            u = self.per_user[t["userKey"]]
            u["turns"] += 1
            u["in"] += t["inputTokens"]
            u["out"] += t["outputTokens"]
        # handoffs: the latest event per conversation decides; the conversation counts where it first appeared
        self.handoffs = Counter()
        self._resolve: list[float] = []
        by_conv: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for e in events:
            if e["type"] == "handoff" and (agent is None or e["agentId"] == agent):
                by_conv[(e["agentId"], e["conversationId"])].append(e)
        rank = {"open": 0, "claimed": 1, "resolved": 2}
        for evs in by_conv.values():
            opened = min(_dt(e["at"]) for e in evs)
            if opened < since:
                continue
            last = max(evs, key=lambda e: (_dt(e["at"]), rank[e["status"]]))
            self.handoffs["total"] += 1
            self.handoffs[last["status"]] += 1
            if last["status"] == "resolved" and last["resolveMinutes"] is not None:
                self._resolve.append(last["resolveMinutes"])

    @property
    def avg_resolve(self) -> float | None:
        return sum(self._resolve) / len(self._resolve) if self._resolve else None

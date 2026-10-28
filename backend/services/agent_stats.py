"""How each agent is doing: how much it works, what it costs, how often its
work lands, and why it fails — for the super admin's agent dashboard.

Two records, read together over one period:

* the usage ledger (`build_usage.read_ledger`): every model call, by agent —
  calls, spend, tokens, and the time the calls took (`duration_ms`), which is
  how busy the agent was;
* every application's run ledgers (`<app>/.forge/runs/*.jsonl`): each step an
  agent was given (`node:start`), whether it landed (`node:done`) or failed
  (`node:failed`, with why), its retries, the observer's repairs of it and
  what stayed unrepaired, and how long it took. A run that a restart cut off
  counts against the agent whose run it was: a lost turn is Smith's, a lost
  check Tess's, a lost publish Dex's.

Agents are people here (`agent_personas`); work no persona claims is counted
under "other" so the totals still add up.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from services import spending
from services.agent_personas import agent_of, personas

OTHER = "other"
#: A run's own outcome, by what the ledger records, is this agent's.
_RUN_OWNER = {"turn": "smith", "fix": "smith", "heal": "smith", "check": "testing", "publish": "deployment"}
_GENERIC = re.compile(r"^\s*(all|\d+ of) \d+ subjects? failed", re.I)
_NUMBERS = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27}\b|\b[A-Z]+-\d+\b|\d+")


def _reason(text: Any) -> str:
    """A failure reason with its ids and numbers taken out, so the same fault
    on two apps is counted as one."""
    said = " ".join(str(text or "").split())
    said = _NUMBERS.sub("#", said)
    return said[:160] or "(no reason recorded)"


def _blank(agent: str) -> dict[str, Any]:
    p = personas().get(agent, {"name": "Other", "title": "Work no agent claims", "room": "", "intro": ""})
    return {"agent": agent, "name": p["name"], "title": p["title"], "room": p.get("room", ""),
            "calls": 0, "repair_calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
            "busy_ms": 0, "apps": set(), "steps": 0, "done": 0, "failed": 0, "retries": 0, "repairs": 0,
            "unrepaired": 0, "runs_lost": 0, "reviews": 0, "found": 0, "durations_s": [], "failures": Counter()}


def _epoch(at: Any) -> float | None:
    try:
        return time.mktime(time.strptime(str(at)[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (TypeError, ValueError):
        return None


def _day(ts: Any) -> str:
    """`YYYY-MM-DD` (UTC) of a usage row's `ts` — epoch seconds, or a date."""
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))
    except (TypeError, ValueError):
        try:
            at = spending.parse_at(str(ts or ""))
        except ValueError:
            return ""
        return at.strftime("%Y-%m-%d") if at else ""


def _usage(stats: dict[str, dict[str, Any]], rows: Iterable[Mapping[str, Any]], start: float, end: float,
           daily: dict[str, dict[str, float]]) -> None:
    for r in spending.within(rows, start, end):
        agent = agent_of(str(r.get("agent") or "")) or OTHER
        s = stats.setdefault(agent, _blank(agent))
        s["calls"] += 1
        if str(r.get("agent") or "").endswith(":edit"):
            s["repair_calls"] += 1
        cost = spending.cost_of(r)
        s["cost_usd"] += cost
        s["input_tokens"] += int(r.get("input_tokens") or 0)
        s["output_tokens"] += int(r.get("output_tokens") or 0)
        s["busy_ms"] += int(r.get("duration_ms") or 0)
        if r.get("project"):
            s["apps"].add(str(r["project"]))
        day_of = _day(r.get("ts"))
        if day_of:
            day = daily[day_of]
            day["calls"] += 1
            day["cost_usd"] += cost


def _ledgers(stats: dict[str, dict[str, Any]], root: Path, start: float, end: float,
             daily: dict[str, dict[str, float]]) -> None:
    from services.blueprint.run_ledger import ledger_kind
    if not root.is_dir():
        return
    for path in root.glob("*/.forge/runs/*.jsonl"):
        try:
            if path.stat().st_mtime < start:
                continue
            lines = path.read_text("utf-8", "replace").splitlines()
        except OSError:
            continue
        app = path.parent.parent.parent.name
        began: float | None = None
        opened: dict[str, float] = {}
        last, end_event = "", {}
        failed_here: list[tuple[str, str, str]] = []           # (agent, node, reason) — named better at run:end
        last_said: dict[str, str] = {}                         # a step's last retry / unrepaired reason
        any_node = False
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            ev = str(e.get("event") or "")
            last = ev or last
            if ev == "run:start":
                began = _epoch(e.get("at"))
                continue
            if began is None or not (start <= began < end):
                break                                    # a run outside the period, or one with no start
            if ev == "run:end":
                end_event = e
            node = str(e.get("node") or "")
            if not node:
                continue
            any_node = True
            if ev == "observer:verdict":
                o = stats.setdefault("observer", _blank("observer"))
                o["reviews"] += 1
                o["found"] += 0 if e.get("ok") else 1
                o["apps"].add(app)
            agent = agent_of(node) or OTHER
            s = stats.setdefault(agent, _blank(agent))
            ms = float(e.get("elapsedMs") or 0)
            if ev == "node:start":
                s["steps"] += 1
                s["apps"].add(app)
                opened.setdefault(node, ms)
            elif ev == "node:done":
                s["done"] += 1
                if node in opened:
                    s["durations_s"].append(max(0.0, (ms - opened.pop(node)) / 1000))
            elif ev == "node:failed":
                s["failed"] += 1
                failed_here.append((agent, node, str(e.get("reason") or "")))
                opened.pop(node, None)
                daily[time.strftime("%Y-%m-%d", time.gmtime(began))]["failures"] += 1
            elif ev == "node:subject" and e.get("ok") is False and e.get("summary"):
                last_said[node] = str(e["summary"])
            elif ev == "node:retry":
                s["retries"] += 1
                last_said[node] = str(e.get("reason") or last_said.get(node, ""))
            elif ev == "observer:repair":
                s["repairs"] += 1
            elif ev == "observer:unrepaired":
                s["unrepaired"] += 1
                last_said[node] = str(e.get("reason") or last_said.get(node, ""))
        # WHY IT FAILED, IN THE RUN'S OWN WORDS. A fan-out step's failure says
        # only "all N subjects failed"; the run's end names the cause.
        because = end_event.get("failedBecause") if isinstance(end_event.get("failedBecause"), dict) else {}
        for agent, node, said in failed_here:
            said = str(because.get(node) or said)
            if _GENERIC.match(said) and last_said.get(node):
                said = last_said[node]                  # "all 3 subjects failed" says nothing; the last try does
            stats[agent]["failures"][_reason(said)] += 1
        if began is None or not (start <= began < end):
            continue
        owner = _RUN_OWNER.get(ledger_kind(path))
        if owner and not any_node:
            # A turn, a fix, a heal, a publish: the run is the one task.
            s = stats.setdefault(owner, _blank(owner))
            s["steps"] += 1
            s["apps"].add(app)
            if last == "run:end":
                s["done"] += 1
            elif last == "run:crashed":
                s["failed"] += 1
        if owner and last == "run:crashed":
            s = stats.setdefault(owner, _blank(owner))
            s["runs_lost"] += 1
            s["failures"]["cut off by a platform restart"] += 1


def _finish(s: dict[str, Any], span_s: float) -> dict[str, Any]:
    d = sorted(s.pop("durations_s"))
    fails = s.pop("failures")
    finished = s["done"] + s["failed"]
    out = {**s,
           "apps": len(s["apps"]),
           "cost_usd": round(s["cost_usd"], 4),
           "busy_hours": round(s["busy_ms"] / 3_600_000, 2),
           # Share of the period the agent spent in model calls (calls overlap
           # across apps, so a busy agent can exceed 1).
           "utilization": round(s["busy_ms"] / 1000 / span_s, 4) if span_s > 0 else 0.0,
           "success_rate": round(s["done"] / finished, 4) if finished else None,
           "median_s": round(statistics.median(d), 1) if d else None,
           "p90_s": round(d[min(len(d) - 1, int(len(d) * 0.9))], 1) if d else None,
           "cost_per_step_usd": round(s["cost_usd"] / s["done"], 4) if s["done"] else None,
           "top_failures": [{"reason": r, "count": n} for r, n in fails.most_common(5)]}
    out.pop("busy_ms")
    return out


def agent_stats(*, period: str = "month", at: Any = None, root: str | Path | None = None,
                rows: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """`{period, from, to, agents: [...], totals, daily}` — every persona listed,
    idle ones too, busiest first."""
    if root is None:
        from services.project_paths import OUTPUT_ROOT
        root = OUTPUT_ROOT
    if rows is None:
        from services.build_usage import read_ledger
        rows = read_ledger()
    start, end = spending.period_bounds(period, at)
    stats: dict[str, dict[str, Any]] = {a: _blank(a) for a in personas()}
    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0, "failures": 0})
    _usage(stats, rows, start, end, daily)
    _ledgers(stats, Path(root), start, end, daily)
    span = max(1.0, min(end, time.time()) - start)
    agents = [_finish(s, span) for s in stats.values()]
    agents.sort(key=lambda a: (-(a["calls"] + a["steps"]), a["name"]))
    totals = {k: sum(a[k] for a in agents) for k in ("calls", "steps", "done", "failed", "retries", "repairs",
                                                     "unrepaired", "runs_lost", "reviews", "found")}
    totals["cost_usd"] = round(sum(a["cost_usd"] for a in agents), 2)
    totals["busy_hours"] = round(sum(a["busy_hours"] for a in agents), 1)
    finished = totals["done"] + totals["failed"]
    totals["success_rate"] = round(totals["done"] / finished, 4) if finished else None
    totals["active_agents"] = sum(1 for a in agents if a["calls"] or a["steps"])
    return {"period": period, "from": start, "to": end, "agents": agents, "totals": totals,
            "daily": [{"day": d, **{k: round(v, 4) if isinstance(v, float) else v for k, v in daily[d].items()}}
                      for d in sorted(daily)]}


__all__ = ["OTHER", "agent_stats"]

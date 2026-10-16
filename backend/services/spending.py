"""Spend: who spent what, on which application, through which agent — by
day, week, month and year — and whether there is money for what is about
to start.

On 2026-10-10 a $100 top-up read $19 the same morning and nobody could say
where it went: the ledger (`services.build_usage`) knew every call's cost
and the application it was for, but not the person or the organisation,
and nothing stood between "press Build" and an account at zero — a
five-module build sank $14 before the API refused it. This module reads
the same ledger and answers the questions, and gates a build or a turn on
the answers:

- a **report** for a period (`day`, `week`, `month`, `year`, UTC) over a
  scope (the platform, an organisation, a person, an application), split
  by agent, application, person and day;
- a **policy** — what the cockpit keeps in the platform's tables
  (`services.credits`): the credit put on EACH ORGANISATION's account (an
  opening entry, then every top-up and adjustment) and spending limits per
  scope and period — handed in here as a plain mapping, so everything in
  this module is arithmetic over rows and needs no database;
- the **balance** of an organisation — its credit minus everything it
  spent since its first entry — and a **check** before work starts: the
  balance covers what the work is expected to cost, and no limit it falls
  under is reached.

A row's person is the one stamped on it (`build_usage.acting`) when the
row was written; rows written before that carry none and are the
application's owner's. The organisation is the row's, else the application's.

Policy shape::

    {"credits": {"<org id>": [{"at": epoch, "amount": usd, "kind": ..., "note": ..., "by": ...}, ...]},
     "limits": {"platform" | "org:<id>" | "user:<email>" | "project:<short id>": {"day": usd, ...}}}
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

PERIODS = ("day", "week", "month", "year")
#: What a build is taken to cost when the ledger has no builds to go by.
DEFAULT_BUILD_USD = 12.0
#: What one Smith turn is taken to cost.
TURN_USD = 0.6
#: A build the ledger counts as one, for the estimate: at least this many calls.
BUILD_CALLS = 20

PLATFORM = "platform"
SCOPE_KINDS = ("platform", "org", "user", "project")


# --------------------------------------------------------------------------- #
# Periods
# --------------------------------------------------------------------------- #

def period_bounds(period: str, at: datetime | float | None = None) -> tuple[float, float]:
    """``(start, end)`` as epoch seconds of the UTC period containing `at`
    (now by default): the day, the week from Monday, the month, the year."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}, not {period!r}")
    if at is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(at, (int, float)):
        moment = datetime.fromtimestamp(float(at), tz=timezone.utc)
    else:
        moment = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        start, end = day, day + timedelta(days=1)
    elif period == "week":
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=7)
    elif period == "month":
        start = day.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
    else:
        start = day.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
    return start.timestamp(), end.timestamp()


def parse_at(text: str | None) -> datetime | None:
    """``YYYY-MM-DD`` (or a full ISO stamp) as a UTC datetime; None for none."""
    if not text:
        return None
    t = text.strip()
    try:
        if len(t) == 10:
            return datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"not a date: {text!r}") from exc


# --------------------------------------------------------------------------- #
# Rows, attributed
# --------------------------------------------------------------------------- #

def cost_of(row: Mapping[str, Any]) -> float:
    sdk = float(row.get("sdk_cost_usd") or 0.0)
    return sdk if sdk > 0 else float(row.get("est_cost_usd") or 0.0)


def attributed(rows: Iterable[Mapping[str, Any]], projects: Mapping[str, Mapping[str, Any]] | None = None
               ) -> list[dict[str, Any]]:
    """Every row with its `project`, `user` and `org` settled: the user
    stamped on the row, else the application's owner; the org stamped on
    the row, else the application's. `projects` maps an application id to
    ``{"org": ..., "owner": ..., "name": ...}``."""
    projects = projects or {}
    out: list[dict[str, Any]] = []
    for r in rows:
        p = str(r.get("project") or "unknown")
        known = projects.get(p) or {}
        out.append({**r, "project": p,
                    "user": str(r.get("user") or known.get("owner") or ""),
                    "org": str(r.get("org") or known.get("org") or ""),
                    "cost_usd": cost_of(r)})
    return out


def within(rows: Iterable[Mapping[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    return [dict(r) for r in rows if start <= float(r.get("ts") or 0) < end]


def of_scope(rows: Iterable[Mapping[str, Any]], *, org: str = "", user: str = "", project: str = "",
             agent: str = "") -> list[dict[str, Any]]:
    """The rows a scope owns; every filter given must hold. `agent` matches
    the agent exactly or its first part (`page_code` takes
    `page_code:ui_engineer` and `page_code:page_reviewer`)."""
    out = []
    for r in rows:
        if org and str(r.get("org") or "") != org:
            continue
        if user and str(r.get("user") or "") != user:
            continue
        if project and str(r.get("project") or "") != project:
            continue
        if agent:
            name = str(r.get("agent") or "")
            if name != agent and name.split(":", 1)[0] != agent:
                continue
        out.append(dict(r))
    return out


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #

def _bucket() -> dict[str, Any]:
    return {"cost_usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0}


def _add(bucket: dict[str, Any], r: Mapping[str, Any]) -> None:
    bucket["cost_usd"] += float(r.get("cost_usd") or cost_of(r))
    bucket["calls"] += 1
    for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
        bucket[k] += int(r.get(k) or 0)


def _rows_of(groups: dict[str, dict[str, Any]], key: str) -> list[dict[str, Any]]:
    out = [{key: k, **{kk: (round(v, 4) if kk == "cost_usd" else v) for kk, v in b.items()}}
           for k, b in groups.items()]
    out.sort(key=lambda x: x["cost_usd"], reverse=True)
    return out


def report(rows: Iterable[Mapping[str, Any]], *, period: str, at: datetime | float | None = None,
           org: str = "", user: str = "", project: str = "", agent: str = "",
           projects: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """What a scope spent in the period containing `at`: the total, and the
    split by agent, by application, by person, by day (by hour for a day)
    and by model. `agent` narrows to one agent's calls — the drill-down."""
    start, end = period_bounds(period, at)
    mine = of_scope(within(attributed(rows, projects), start, end), org=org, user=user, project=project, agent=agent)
    total = _bucket()
    by_agent: dict[str, dict[str, Any]] = {}
    by_project: dict[str, dict[str, Any]] = {}
    by_user: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_phase: dict[str, dict[str, Any]] = {}
    by_day: dict[str, float] = {}
    by_hour: dict[str, float] = {}
    for r in mine:
        _add(total, r)
        _add(by_agent.setdefault(str(r.get("agent") or "agent"), _bucket()), r)
        _add(by_project.setdefault(str(r["project"]), _bucket()), r)
        _add(by_user.setdefault(str(r.get("user") or "unattributed"), _bucket()), r)
        _add(by_model.setdefault(str(r.get("model") or "unknown"), _bucket()), r)
        _add(by_phase.setdefault(str(r.get("phase") or "unsplit"), _bucket()), r)
        moment = datetime.fromtimestamp(float(r.get("ts") or 0), tz=timezone.utc)
        day = moment.strftime("%Y-%m-%d")
        by_day[day] = by_day.get(day, 0.0) + float(r["cost_usd"])
        hour = moment.strftime("%H:00")
        by_hour[hour] = by_hour.get(hour, 0.0) + float(r["cost_usd"])
    names = projects or {}
    return {
        "period": period,
        "from": datetime.fromtimestamp(start, tz=timezone.utc).isoformat(),
        "to": datetime.fromtimestamp(end, tz=timezone.utc).isoformat(),
        "scope": {"org": org, "user": user, "project": project, "agent": agent},
        "total": {**{k: (round(v, 4) if k == "cost_usd" else v) for k, v in total.items()}},
        "by_agent": _rows_of(by_agent, "agent"),
        "by_project": [{**row, "name": str((names.get(row["project"]) or {}).get("name") or "")}
                       for row in _rows_of(by_project, "project")],
        "by_user": _rows_of(by_user, "user"),
        "by_model": _rows_of(by_model, "model"),
        "by_phase": _rows_of(by_phase, "phase"),
        "by_day": [{"day": d, "cost_usd": round(c, 4)} for d, c in sorted(by_day.items())],
        "by_hour": ([{"hour": h, "cost_usd": round(c, 4)} for h, c in sorted(by_hour.items())]
                    if period == "day" else []),
    }


# --------------------------------------------------------------------------- #
# The policy: credit per organisation, and limits
# --------------------------------------------------------------------------- #

def empty_policy() -> dict[str, Any]:
    return {"credits": {}, "limits": {}}


def scope_key(*, org: str = "", user: str = "", project: str = "") -> str:
    if project:
        return f"project:{project}"
    if user:
        return f"user:{user}"
    if org:
        return f"org:{org}"
    return PLATFORM


def parse_scope(scope: str) -> tuple[str, str]:
    """``(kind, id)`` of a scope key; the platform's id is ''."""
    if scope == PLATFORM:
        return PLATFORM, ""
    kind, sep, ident = scope.partition(":")
    if not sep or kind not in ("org", "user", "project") or not ident:
        raise ValueError(f"not a scope: {scope!r}")
    return kind, ident


def clean_limits(limits: Mapping[str, Any]) -> dict[str, float]:
    """Limits per period as the policy holds them: a period left out, empty
    or zero has no limit; a negative one is refused."""
    clean: dict[str, float] = {}
    for period, amount in limits.items():
        if period not in PERIODS:
            raise ValueError(f"not a period: {period!r}")
        if amount in (None, "", 0, "0", 0.0):
            continue
        value = float(amount)
        if value <= 0:
            raise ValueError(f"a limit is a positive amount, not {amount!r}")
        clean[period] = round(value, 2)
    return clean


def balance(rows: Iterable[Mapping[str, Any]], policy: Mapping[str, Any], *, org: str) -> dict[str, Any]:
    """An organisation's credit minus everything IT spent since its first
    credit entry. `known` is False when no credit was ever recorded for it —
    then there is no balance to speak of, only spend and limits."""
    entries = sorted((policy.get("credits") or {}).get(str(org)) or [], key=lambda c: float(c.get("at") or 0))
    if not entries:
        return {"known": False, "credit_usd": 0.0, "spent_usd": 0.0, "balance_usd": None, "since": None}
    since = float(entries[0].get("at") or 0)
    credit = sum(float(c.get("amount") or 0) for c in entries)
    spent = sum(cost_of(r) for r in rows
                if str(r.get("org") or "") == str(org) and float(r.get("ts") or 0) >= since)
    return {"known": True, "credit_usd": round(credit, 2), "spent_usd": round(spent, 4),
            "balance_usd": round(credit - spent, 4),
            "since": datetime.fromtimestamp(since, tz=timezone.utc).isoformat()}


# --------------------------------------------------------------------------- #
# The check before work starts
# --------------------------------------------------------------------------- #

def estimate_build_usd(rows: Iterable[Mapping[str, Any]], *, days: int = 30, org: str = "") -> float:
    """What a build is expected to cost: the median of the organisation's
    builds from the last `days` (an application's build-phase rows, at least
    `BUILD_CALLS` of them), else the platform's, else `DEFAULT_BUILD_USD`."""
    since = time.time() - days * 86400
    per_app: dict[str, list[float]] = {}
    per_app_org: dict[str, str] = {}
    for r in rows:
        if float(r.get("ts") or 0) < since or str(r.get("phase") or "") != "build":
            continue
        app = str(r.get("project") or "")
        per_app.setdefault(app, []).append(cost_of(r))
        if r.get("org"):
            per_app_org[app] = str(r["org"])
    builds = {app: sum(c) for app, c in per_app.items() if len(c) >= BUILD_CALLS}
    if org:
        own = [v for app, v in builds.items() if per_app_org.get(app) == str(org)]
        if own:
            return round(statistics.median(own), 2)
    return round(statistics.median(builds.values()), 2) if builds else DEFAULT_BUILD_USD


def _said_scope(scope: str, names: Mapping[str, str] | None = None) -> str:
    names = names or {}
    if scope == PLATFORM:
        return "the platform"
    kind, _, ident = scope.partition(":")
    label = names.get(scope) or ident
    return {"org": f"the organisation {label}", "user": f"{label}", "project": f"the application {label}"}.get(kind, scope)


def _said_period(period: str) -> str:
    return {"day": "today", "week": "this week", "month": "this month", "year": "this year"}[period]


def check(rows: Iterable[Mapping[str, Any]], *, estimate: float, org: str = "", user: str = "", project: str = "",
          policy: Mapping[str, Any] | None = None, projects: Mapping[str, Mapping[str, Any]] | None = None,
          names: Mapping[str, str] | None = None, now: float | None = None) -> list[str]:
    """Why the work must not start, in the administrator's terms — empty
    when it may: the organisation's balance (when one is recorded) covers
    `estimate`, and no limit over the platform, the organisation, the person
    or the application is reached in its period."""
    rows = attributed(rows, projects)
    policy = policy or empty_policy()
    now = float(now if now is not None else time.time())
    out: list[str] = []
    if org:
        bal = balance(rows, policy, org=org)
        if bal["known"] and float(bal["balance_usd"] or 0) < estimate:
            out.append(f"{_said_scope(f'org:{org}', names)} holds ${float(bal['balance_usd'] or 0):.2f} and this is "
                       f"expected to cost about ${estimate:.2f} — add credit before it starts")
    scopes = [PLATFORM]
    if org:
        scopes.append(f"org:{org}")
    if user:
        scopes.append(f"user:{user}")
    if project:
        scopes.append(f"project:{project}")
    limits = policy.get("limits") or {}
    for scope in scopes:
        for period, limit in (limits.get(scope) or {}).items():
            if period not in PERIODS or not limit:
                continue
            start, end = period_bounds(period, now)
            kind, _, ident = scope.partition(":")
            spent = sum(float(r["cost_usd"]) for r in of_scope(
                within(rows, start, end),
                org=ident if kind == "org" else "", user=ident if kind == "user" else "",
                project=ident if kind == "project" else ""))
            if spent + estimate > float(limit):
                out.append(f"{_said_scope(scope, names)} has spent ${spent:.2f} {_said_period(period)} of a "
                           f"${float(limit):.2f} limit, and this is expected to cost about ${estimate:.2f}")
    return out


def standing(rows: Iterable[Mapping[str, Any]], *, org: str = "", user: str = "", project: str = "",
             policy: Mapping[str, Any] | None = None, projects: Mapping[str, Mapping[str, Any]] | None = None,
             now: float | None = None) -> dict[str, Any]:
    """Where a scope stands against every limit that covers it, per period:
    what was spent, the limit, what is left — and the organisation's balance
    when the scope names one."""
    rows = attributed(rows, projects)
    policy = policy or empty_policy()
    now = float(now if now is not None else time.time())
    scopes = [PLATFORM] + [s for s in (f"org:{org}" if org else "", f"user:{user}" if user else "",
                                       f"project:{project}" if project else "") if s]
    out = []
    for scope in scopes:
        kind, _, ident = scope.partition(":")
        for period in PERIODS:
            start, end = period_bounds(period, now)
            spent = sum(float(r["cost_usd"]) for r in of_scope(
                within(rows, start, end),
                org=ident if kind == "org" else "", user=ident if kind == "user" else "",
                project=ident if kind == "project" else ""))
            limit = (policy.get("limits") or {}).get(scope, {}).get(period)
            out.append({"scope": scope, "period": period, "spent_usd": round(spent, 4),
                        "limit_usd": float(limit) if limit else None,
                        "left_usd": round(float(limit) - spent, 4) if limit else None})
    return {"balance": balance(rows, policy, org=org) if org else None, "limits": out}


__all__ = ["PERIODS", "PLATFORM", "SCOPE_KINDS", "DEFAULT_BUILD_USD", "TURN_USD", "BUILD_CALLS",
           "period_bounds", "parse_at", "cost_of", "attributed", "within", "of_scope", "report",
           "empty_policy", "scope_key", "parse_scope", "clean_limits", "balance", "estimate_build_usd",
           "check", "standing"]

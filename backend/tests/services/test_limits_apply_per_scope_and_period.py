"""A limit bounds one scope — the platform, an organisation, a person, an
application — for one UTC period, and the check speaks in the
administrator's words. A period left empty or zero has no limit."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services import spending

MONDAY = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
AT = MONDAY.timestamp()
PROJECTS = {"app1": {"org": "org-a", "owner": "asha@example.com", "name": "App One"}}


def row(cost: float, *, when: float = AT, user: str = "asha@example.com") -> dict:
    return {"ts": when, "project": "app1", "agent": "a", "phase": "change", "model": "m",
            "est_cost_usd": cost, "sdk_cost_usd": 0.0, "input_tokens": 1, "output_tokens": 1, "user": user, "org": "org-a"}


def test_periods_are_utc_calendar_periods():
    day = spending.period_bounds("day", MONDAY)
    assert datetime.fromtimestamp(day[0], tz=timezone.utc).isoformat() == "2026-10-12T00:00:00+00:00"
    week = spending.period_bounds("week", MONDAY + __import__("datetime").timedelta(days=3))
    assert datetime.fromtimestamp(week[0], tz=timezone.utc).date().isoformat() == "2026-10-12"
    month = spending.period_bounds("month", MONDAY)
    assert datetime.fromtimestamp(month[1], tz=timezone.utc).date().isoformat() == "2026-11-01"
    with pytest.raises(ValueError):
        spending.period_bounds("fortnight", MONDAY)


def test_each_scope_and_period_is_checked_in_words():
    rows = [row(0.4), row(0.3, when=AT - 86400 * 2), row(0.2, when=AT - 86400 * 40)]
    # Monday: the row from two days ago is last week's; the one from forty
    # days ago is this year's.
    policy = {"credits": {}, "limits": {
        "platform": {"day": 0.5}, "org:org-a": {"week": 0.9}, "user:asha@example.com": {"month": 1.0},
        "project:app1": {"year": 0.8}}}
    why = spending.check(rows, estimate=0.6, org="org-a", user="asha@example.com", project="app1",
                         policy=policy, projects=PROJECTS, names={"org:org-a": "Acme", "project:app1": "App One"},
                         now=AT + 60)
    assert why == [
        "the platform has spent $0.40 today of a $0.50 limit, and this is expected to cost about $0.60",
        "the organisation Acme has spent $0.40 this week of a $0.90 limit, and this is expected to cost about $0.60",
        "asha@example.com has spent $0.70 this month of a $1.00 limit, and this is expected to cost about $0.60",
        "the application App One has spent $0.90 this year of a $0.80 limit, and this is expected to cost about $0.60",
    ]
    # The application's year limit is already past; the other three hold a small turn.
    assert spending.check(rows, estimate=0.05, org="org-a", user="asha@example.com",
                          policy=policy, projects=PROJECTS, now=AT + 60) == []


def test_standing_says_spent_limit_and_what_is_left_per_period():
    rows = [row(0.25)]
    policy = {"credits": {}, "limits": {"org:org-a": {"day": 1.0}}}
    out = spending.standing(rows, org="org-a", policy=policy, projects=PROJECTS, now=AT + 60)
    day = next(r for r in out["limits"] if r["scope"] == "org:org-a" and r["period"] == "day")
    assert day == {"scope": "org:org-a", "period": "day", "spent_usd": 0.25, "limit_usd": 1.0, "left_usd": 0.75}
    week = next(r for r in out["limits"] if r["scope"] == "org:org-a" and r["period"] == "week")
    assert week["limit_usd"] is None and week["spent_usd"] == 0.25
    assert out["balance"]["known"] is False


def test_limits_are_cleaned_and_scopes_parsed():
    assert spending.clean_limits({"day": "2.5", "week": None, "month": 0, "year": ""}) == {"day": 2.5}
    with pytest.raises(ValueError):
        spending.clean_limits({"day": -1})
    with pytest.raises(ValueError):
        spending.clean_limits({"hour": 1})
    assert spending.parse_scope("platform") == ("platform", "")
    assert spending.parse_scope("org:abc") == ("org", "abc")
    with pytest.raises(ValueError):
        spending.parse_scope("team:abc")
    assert spending.scope_key(org="o", user="u") == "user:u" and spending.scope_key() == "platform"

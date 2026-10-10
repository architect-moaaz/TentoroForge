"""Spend is known per person, organisation, application and agent, by day,
week, month and year — and checked before a build or a turn starts.

2026-10-10: a $100 top-up read $19 the same morning; the ledger knew each
call's application and cost but not whose it was, and nothing stood
between "Build" and an account at zero — a five-module build sank $14
before the API refused it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from services import spending as S

T = datetime(2026, 10, 10, 7, 30, tzinfo=timezone.utc).timestamp()      # Saturday
PROJECTS = {"ecom": {"org": "ORG-A", "owner": "admin@example.com", "name": "ecom v1"},
            "hr": {"org": "ORG-A", "owner": "aryan@example.com", "name": "payroll manager"},
            "shop": {"org": "ORG-B", "owner": "iliya@example.com", "name": "E-commerce"}}


def _row(ts, project, agent, cost, *, phase="build", user="", model="claude-sonnet-5"):
    return {"ts": ts, "project": project, "agent": agent, "est_cost_usd": cost, "phase": phase, "user": user,
            "model": model, "input_tokens": 1000, "output_tokens": 500}


ROWS = [
    _row(T - 3600, "ecom", "page_code:ui_engineer", 3.0),                       # today, owner admin
    _row(T - 1800, "ecom", "workflow_steps:workflow", 1.0),
    _row(T - 900, "ecom", "smith", 0.5, phase="change", user="cbp1@test.com"),  # today, stamped person
    _row(T - 86400 * 2, "hr", "page_code:ui_engineer", 4.0),                     # Thursday
    _row(T - 86400 * 6, "shop", "page_code:ui_engineer", 6.0),                   # last Sunday: not this week
    _row(T - 86400 * 40, "shop", "smith", 2.0, phase="change"),                  # August: not this month
]


def test_periods_are_utc_calendar_periods():
    day = S.period_bounds("day", T)
    assert datetime.fromtimestamp(day[0], tz=timezone.utc).isoformat() == "2026-10-10T00:00:00+00:00"
    week = S.period_bounds("week", T)
    assert datetime.fromtimestamp(week[0], tz=timezone.utc).strftime("%a %Y-%m-%d") == "Mon 2026-10-05"
    assert datetime.fromtimestamp(week[1], tz=timezone.utc).strftime("%Y-%m-%d") == "2026-10-12"
    month = S.period_bounds("month", T)
    assert datetime.fromtimestamp(month[1], tz=timezone.utc).strftime("%Y-%m-%d") == "2026-11-01"
    year = S.period_bounds("year", T)
    assert datetime.fromtimestamp(year[0], tz=timezone.utc).strftime("%Y-%m-%d") == "2026-01-01"
    assert S.parse_at("2026-10-10").tzinfo is not None and S.parse_at("") is None
    with pytest.raises(ValueError):
        S.period_bounds("fortnight", T)


def test_a_row_is_the_stamped_persons_else_the_applications_owners():
    rows = S.attributed(ROWS, PROJECTS)
    assert rows[0]["user"] == "admin@example.com" and rows[0]["org"] == "ORG-A"
    assert rows[2]["user"] == "cbp1@test.com" and rows[2]["org"] == "ORG-A", "stamped wins; the org is the app's"
    assert rows[4]["user"] == "iliya@example.com" and rows[4]["org"] == "ORG-B"
    assert S.attributed([_row(T, "gone", "x", 1.0)])[0]["user"] == "" and S.attributed([_row(T, "gone", "x", 1.0)])[0]["org"] == ""


def test_the_report_is_by_period_scope_agent_application_and_person():
    day = S.report(ROWS, period="day", at=T, projects=PROJECTS)
    assert day["total"]["cost_usd"] == 4.5 and day["total"]["calls"] == 3
    assert [r["agent"] for r in day["by_agent"]] == ["page_code:ui_engineer", "workflow_steps:workflow", "smith"]
    assert day["by_project"][0] == {"project": "ecom", "name": "ecom v1", "cost_usd": 4.5, "calls": 3,
                                    "input_tokens": 3000, "output_tokens": 1500, "cache_read_tokens": 0,
                                    "cache_write_tokens": 0}
    assert {r["user"]: r["cost_usd"] for r in day["by_user"]} == {"admin@example.com": 4.0, "cbp1@test.com": 0.5}
    assert {r["phase"]: r["cost_usd"] for r in day["by_phase"]} == {"build": 4.0, "change": 0.5}
    week = S.report(ROWS, period="week", at=T, projects=PROJECTS)
    assert week["total"]["cost_usd"] == 8.5, "Thursday's HR build is this week's; last Sunday's shop is not"
    assert S.report(ROWS, period="month", at=T, projects=PROJECTS)["total"]["cost_usd"] == 14.5
    assert S.report(ROWS, period="year", at=T, projects=PROJECTS)["total"]["cost_usd"] == 16.5
    org_b = S.report(ROWS, period="year", at=T, org="ORG-B", projects=PROJECTS)
    assert org_b["total"]["cost_usd"] == 8.0 and [r["project"] for r in org_b["by_project"]] == ["shop"]
    person = S.report(ROWS, period="year", at=T, user="aryan@example.com", projects=PROJECTS)
    assert person["total"]["cost_usd"] == 4.0
    app = S.report(ROWS, period="day", at=T, project="ecom", projects=PROJECTS)
    assert app["by_day"] == [{"day": "2026-10-10", "cost_usd": 4.5}]
    assert app["by_hour"] == [{"hour": "06:00", "cost_usd": 3.0}, {"hour": "07:00", "cost_usd": 1.5}], "a day is split by hour"
    assert week["by_hour"] == [], "a week is not"
    one = S.report(ROWS, period="year", at=T, agent="page_code", projects=PROJECTS)
    assert one["total"]["cost_usd"] == 13.0 and [r["project"] for r in one["by_project"]] == ["shop", "hr", "ecom"], \
        "the drill-down into one agent: its calls across applications"
    assert S.report(ROWS, period="year", at=T, agent="page_code:ui_engineer", projects=PROJECTS)["total"]["cost_usd"] == 13.0


def test_the_balance_is_credit_recorded_minus_spend_since(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_SPEND_POLICY", str(tmp_path / "spend-policy.json"))
    assert S.balance(ROWS)["known"] is False, "no credit recorded, no balance to speak of"
    S.add_credit(100, note="opening balance", by="m", at=T - 86400 * 3)       # Wednesday
    S.add_credit(50, note="top-up", by="m", at=T - 60)
    bal = S.balance(ROWS)
    assert bal["known"] and bal["credit_usd"] == 150 and bal["spent_usd"] == 8.5 and bal["balance_usd"] == 141.5
    with pytest.raises(ValueError):
        S.add_credit(0)
    saved = json.loads((tmp_path / "spend-policy.json").read_text())
    assert [c["amount"] for c in saved["credits"]] == [100, 50]


def test_limits_are_kept_per_scope_and_period(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_SPEND_POLICY", str(tmp_path / "spend-policy.json"))
    assert S.set_limits("platform", {"day": 40, "month": "500"}) == {"day": 40.0, "month": 500.0}
    assert S.set_limits("org:ORG-A", {"week": 25, "day": ""}) == {"week": 25.0}
    assert S.set_limits("user:admin@example.com", {"day": 5}) == {"day": 5.0}
    assert S.set_limits("project:ecom", {"year": 20}) == {"year": 20.0}
    assert S.set_limits("org:ORG-A", {}) == {} and "org:ORG-A" not in S.read_policy()["limits"]
    with pytest.raises(ValueError):
        S.set_limits("team:x", {"day": 1})
    with pytest.raises(ValueError):
        S.set_limits("platform", {"hour": 1})
    with pytest.raises(ValueError):
        S.set_limits("platform", {"day": -1})
    assert S.scope_key(org="O", user="u", project="p") == "project:p" and S.scope_key(org="O") == "org:O"
    assert S.scope_key() == "platform"


def test_work_is_refused_when_the_balance_or_a_limit_cannot_cover_it(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_SPEND_POLICY", str(tmp_path / "spend-policy.json"))
    ok = S.check(ROWS, estimate=12, org="ORG-A", user="admin@example.com", project="ecom", projects=PROJECTS, now=T)
    assert ok == [], "no credit recorded and no limits: nothing stands in the way"
    S.add_credit(20, at=T - 86400 * 3)                                           # 20 - 8.5 = 11.5 left
    why = S.check(ROWS, estimate=12, org="ORG-A", user="admin@example.com", project="ecom", projects=PROJECTS, now=T)
    assert why == ["the account holds $11.50 and this is expected to cost about $12.00 — add credit before it starts"]
    S.add_credit(100, at=T - 30)
    assert S.check(ROWS, estimate=12, org="ORG-A", user="admin@example.com", project="ecom", projects=PROJECTS, now=T) == []
    S.set_limits("user:admin@example.com", {"day": 5})
    S.set_limits("org:ORG-A", {"week": 20})
    S.set_limits("platform", {"month": 1000})
    why = S.check(ROWS, estimate=12, org="ORG-A", user="admin@example.com", project="ecom", projects=PROJECTS,
                  names={"org:ORG-A": "Tentoro"}, now=T)
    assert why == ["the organisation Tentoro has spent $8.50 this week of a $20.00 limit, and this is expected to cost about $12.00",
                   "admin@example.com has spent $4.00 today of a $5.00 limit, and this is expected to cost about $12.00"]
    assert S.check(ROWS, estimate=0.5, org="ORG-B", user="iliya@example.com", project="shop", projects=PROJECTS, now=T) == [], \
        "another organisation's person is under no limit of theirs"
    where = S.standing(ROWS, org="ORG-A", user="admin@example.com", projects=PROJECTS, now=T)
    assert where["balance"]["balance_usd"] == 111.5
    row = next(r for r in where["limits"] if r["scope"] == "org:ORG-A" and r["period"] == "week")
    assert row == {"scope": "org:ORG-A", "period": "week", "spent_usd": 8.5, "limit_usd": 20.0, "left_usd": 11.5}


def test_a_build_is_expected_to_cost_what_recent_builds_did():
    assert S.estimate_build_usd(ROWS) == S.DEFAULT_BUILD_USD, "no application with a build's worth of calls"
    import time
    now = time.time()
    rows = [_row(now - 100 - i, "a", "x", 0.5) for i in range(30)] + [_row(now - 100 - i, "b", "x", 1.0) for i in range(30)] \
        + [_row(now - 86400 * 60, "old", "x", 9.0) for _ in range(30)]
    assert S.estimate_build_usd(rows) == 22.5, "the median of this month's builds ($15 and $30); an old one does not count"


def test_every_row_written_while_someone_acts_names_them(tmp_path, monkeypatch):
    from services import build_usage
    monkeypatch.setenv("FORGE_USAGE_LOG", str(tmp_path / "usage.jsonl"))
    with build_usage.acting(user="admin@example.com", org="ORG-A"):
        assert build_usage.actor() == {"user": "admin@example.com", "org": "ORG-A"}
        build_usage.record_usage(project="ecom", agent="smith", model="claude-sonnet-5",
                                 usage={"input_tokens": 10, "output_tokens": 5}, kind="smith", phase="change")
    build_usage.record_usage(project="ecom", agent="smith", model="claude-sonnet-5",
                             usage={"input_tokens": 10, "output_tokens": 5}, kind="smith", phase="change")
    rows = [json.loads(l) for l in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert (rows[0]["user"], rows[0]["org"]) == ("admin@example.com", "ORG-A")
    assert (rows[1]["user"], rows[1]["org"]) == ("", ""), "outside anyone's request, nobody's"
    from services.blueprint.executors import RunUsage
    with build_usage.acting(user="cbp1@test.com", org="ORG-B"):
        run = RunUsage.for_app(type("S", (), {"doc": {"application": {"id": "crumb"}}})())
    assert (run.user, run.org) == ("cbp1@test.com", "ORG-B"), "a run takes the actor where it starts"

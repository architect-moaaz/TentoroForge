"""An organisation's balance is its own credit minus its own spend since
its first entry. Signed entries move it; an organisation with no entry has
no balance to speak of; spend before the first entry is reported, never
charged; a row that names no organisation is the application's."""
from __future__ import annotations

import time

from services import spending

NOW = time.time()
ORG_A, ORG_B = "org-a", "org-b"
PROJECTS = {"app1": {"org": ORG_A, "owner": "asha@example.com", "name": "App One"},
            "app2": {"org": ORG_B, "owner": "ravi@example.com", "name": "App Two"}}


def row(project: str, cost: float, *, ago_s: float = 0, user: str = "", org: str = "", phase: str = "build") -> dict:
    return {"ts": NOW - ago_s, "project": project, "agent": "page_code", "phase": phase, "model": "m",
            "est_cost_usd": cost, "sdk_cost_usd": 0.0, "input_tokens": 1, "output_tokens": 1,
            "user": user, "org": org}


def test_the_balance_is_signed_entries_minus_the_orgs_own_spend_since_the_first():
    rows = [row("app1", 2.0, ago_s=3600), row("app1", 1.5, ago_s=60, user="asha@example.com", org=ORG_A),
            row("app2", 9.0, ago_s=60, org=ORG_B)]
    policy = {"credits": {ORG_A: [{"at": NOW - 7200, "amount": 10.0, "kind": "opening"},
                                  {"at": NOW - 10, "amount": -1.0, "kind": "adjustment"}]}, "limits": {}}
    bal = spending.balance(spending.attributed(rows, PROJECTS), policy, org=ORG_A)
    assert bal["known"] and bal["credit_usd"] == 9.0
    assert bal["spent_usd"] == 3.5, "both of A's rows: the one stamped with the org and the one attributed by its app"
    assert bal["balance_usd"] == 5.5
    assert spending.balance(spending.attributed(rows, PROJECTS), policy, org=ORG_B)["known"] is False


def test_spend_before_the_first_entry_is_not_charged():
    rows = [row("app1", 4.0, ago_s=7200), row("app1", 1.0, ago_s=10)]
    policy = {"credits": {ORG_A: [{"at": NOW - 3600, "amount": 5.0}]}, "limits": {}}
    bal = spending.balance(spending.attributed(rows, PROJECTS), policy, org=ORG_A)
    assert bal["spent_usd"] == 1.0 and bal["balance_usd"] == 4.0


def test_attribution_falls_back_to_the_application():
    out = spending.attributed([row("app2", 1.0), row("nowhere", 1.0, user="x@example.com")], PROJECTS)
    assert (out[0]["user"], out[0]["org"]) == ("ravi@example.com", ORG_B)
    assert (out[1]["user"], out[1]["org"]) == ("x@example.com", "")


def test_the_check_refuses_a_known_balance_that_cannot_cover_the_estimate_and_only_that():
    rows = [row("app1", 8.0, ago_s=60)]
    policy = {"credits": {ORG_A: [{"at": NOW - 3600, "amount": 10.0}]}, "limits": {}}
    why = spending.check(rows, estimate=5.0, org=ORG_A, user="asha@example.com", project="app1",
                         policy=policy, projects=PROJECTS, names={f"org:{ORG_A}": "Acme"})
    assert why == ["the organisation Acme holds $2.00 and this is expected to cost about $5.00 — add credit before it starts"]
    assert spending.check(rows, estimate=1.5, org=ORG_A, policy=policy, projects=PROJECTS) == []
    # An organisation with no entry is not refused for a balance nobody recorded.
    assert spending.check(rows, estimate=500.0, org=ORG_B, policy=policy, projects=PROJECTS) == []


def test_the_estimate_prefers_the_organisations_own_builds():
    cheap = [row("app1", 0.1, ago_s=60, org=ORG_A) for _ in range(spending.BUILD_CALLS)]
    dear = [row("app2", 1.0, ago_s=60, org=ORG_B) for _ in range(spending.BUILD_CALLS)]
    assert spending.estimate_build_usd(cheap + dear, org=ORG_A) == 2.0
    assert spending.estimate_build_usd(cheap + dear, org=ORG_B) == 20.0
    assert spending.estimate_build_usd(cheap + dear, org="org-c") == 11.0, "the platform's median when it has none"
    assert spending.estimate_build_usd([], org=ORG_A) == spending.DEFAULT_BUILD_USD

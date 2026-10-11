"""The built application is scored against its domain reference: from the
Blueprint and the checks, and by one reviewer look per role's landing — a
bounded `roles + 1`, never one call per page."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from services.blueprint import domain_score as ds

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Vendor"}],
    "navigation": {"initialRoute": {"Vendor": "/vendor", "Admin": "/admin", "authenticated": "/"}},
    "domainReference": {"domain": "Retail", "subdomain": "Marketplace",
                        "screens": [{"name": "Order book", "forRoles": ["Vendor"]},
                                    {"name": "Payout statement", "forRoles": ["Vendor"]},
                                    {"name": "Dispute centre"}],
                        "processes": [{"name": "Refund an order", "roles": ["Admin"]}],
                        "records": [], "rules": [], "integrations": [], "conventions": ["SKU everywhere"],
                        "declined": [{"kind": "screen", "name": "Dispute centre", "reason": "v2", "by": "owner"}]},
    "pages": [{"id": "PAGE-001", "name": "Vendor Dashboard", "route": "/vendor", "access": "role_restricted",
               "users": ["ROLE-002"], "reference": "Order book"},
              {"id": "PAGE-002", "name": "Payouts", "route": "/payouts", "reference": "Payout statement"},
              {"id": "PAGE-003", "name": "Admin", "route": "/admin", "access": "role_restricted", "users": ["ROLE-001"]},
              {"id": "PAGE-004", "name": "Shop", "route": "/", "access": "public", "entry": True}],
    "workflows": [{"id": "FLOW-001", "name": "Refund an order", "trigger": {"kind": "manual"}}],
    "runtime": {"check": {"pages": 4, "working": 3, "failing": ["/payouts"], "fixed": [], "untried": []},
                "issues": [{"kind": "process", "workflow": "FLOW-001", "name": "Refund an order", "detail": "500"}]},
}


class _Svc:
    doc = json.loads(json.dumps(DOC))


def test_the_blueprint_half_reads_what_the_checks_found():
    green, red = ds.deterministic(DOC)
    assert [g["label"] for g in green] == ["Order book"]
    assert {r["label"]: r["why"] for r in red} == {
        "Payout statement": "answered by /payouts, which does not work yet",
        "Refund an order": "answered by a process that does not run through yet"}
    assert not [x for x in green + red if x["label"] == "Dispute centre"]        # declined: not counted


def test_one_look_per_role_landing_and_the_public_entry(monkeypatch, tmp_path):
    assert [(v["route"], v["as"]) for v in ds.landings(DOC)] == [("/vendor", "Vendor"), ("/admin", "Admin"), ("/", "signed out")]
    calls = []

    def run_shots(app, entries, out, **k):
        assert k == {"probe": False, "states": False}
        out.mkdir(parents=True, exist_ok=True)
        shots = []
        for e in entries:
            f = out / f"{e['id'].replace('::', '-')}.png"
            f.write_bytes(b"png")
            shots.append({"id": e["id"], "file": str(f), "status": 200})
        return shots
    monkeypatch.setattr("services.blueprint.page_review.run_shots", run_shots)
    monkeypatch.setattr("services.blueprint.app_check._entries", lambda app, doc, batch: [{"id": f"{v['page']}::{v['as']}", "route": v["route"]} for v in batch])

    def client(*, system, user, schema, images):
        calls.append((system[:60], json.loads(user.split("for this person:\n", 1)[1])["screens"], images))
        if "Vendor" in system:
            return json.dumps({"score": 6, "missing": [{"item": "Payout statement", "why": "no way to see what is owed"}],
                               "wrong": [{"item": "SKU", "why": "products show ids, not SKUs"}]})
        return json.dumps({"score": 9, "missing": [], "wrong": []})
    out = ds.score_domain(_Svc, str(tmp_path), app=SimpleNamespace(base="http://x"), client=client)
    assert len(calls) == 3                                                       # roles + 1, not pages
    assert [s["name"] for s in calls[0][1]] == ["Order book", "Payout statement"]   # the vendor's screens only
    assert out["total"] == 4 and out["green"] == 1 and out["untried"] == []
    whys = {r["label"]: r["why"] for r in out["red"]}
    assert whys["Payout statement"] == "answered by /payouts, which does not work yet"   # the check's reason stands
    assert whys["SKU"].startswith("not as the field does it for a Vendor on /vendor")


def test_without_a_reference_the_domain_is_untried_not_scored(tmp_path):
    out = ds.score_domain(SimpleNamespace(doc={"pages": []}), str(tmp_path))
    assert out["total"] == 0 and out["red"] == [] and "no domain reference" in out["untried"][0]["why"]

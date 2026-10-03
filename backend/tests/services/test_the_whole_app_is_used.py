"""Every page is used, as every role it is for, before the build says it is done.

The build knew when a page was missing, never when one was wrong: nothing
opened a page unless "Verify & fix" was offered, accepted, and could run —
and on forge-v3 it could not until 2026-10-01. Testers found the admin on the
customers' menu, a child page that 404'd, slots dated 2001, "Phone 1".
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.blueprint import app_check as ac

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Parent"},
              {"id": "ROLE-003", "name": "Doctor"}],
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Child", "table": "children", "labelField": "name",
         "fields": [{"name": "name", "type": "string"}, {"name": "dateOfBirth", "type": "date"}]},
        {"id": "ENTITY-002", "name": "Slot", "table": "slots",
         "fields": [{"name": "startTime", "type": "time"}, {"name": "phone", "type": "string"}]}]},
    "pages": [
        {"id": "PAGE-001", "name": "Sign in", "route": "/login", "pattern": "auth"},
        {"id": "PAGE-002", "name": "My Children", "route": "/children", "users": ["ROLE-002"],
         "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-003", "name": "Slots", "route": "/slots", "users": ["ROLE-002", "ROLE-003"],
         "data": {"primaryEntity": "ENTITY-002"}},
        {"id": "PAGE-004", "name": "Dashboard", "route": "/dashboard"},
        {"id": "PAGE-005", "name": "Old", "route": "/old", "status": "DEPRECATED"},
    ],
}


# --- what the screen shows -------------------------------------------------------

@pytest.mark.parametrize("text,expect", [
    ("Slot 09:00 1 Dec 2001 Book", "dates in 2001"),
    ("Patient a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d booked", "raw record ids"),
    ("Total: NaN · Due Invalid Date", "'Invalid Date', 'NaN'"),
    ("Price: undefined", "'undefined'"),
    ("Application error: a client-side exception has occurred", "the page says"),
    ("Phone 1 · Start Time 3 · Child 2", "placeholder values (Child 2, Phone 1, Start Time 3)"),
])
def test_what_a_person_would_read_as_broken_is_found(text, expect):
    assert any(expect in f for f in ac.screen_findings(text, DOC)), ac.screen_findings(text, DOC)


@pytest.mark.parametrize("text", [
    "My Children · Aya · Born 1 May 2024 · 2 appointments",
    "Table 7 · Order total 1480",              # a number beside a word that is no field
    "Founded in 2001 · Child 2",               # one placeholder alone is not a pattern
])
def test_a_page_that_reads_fine_is_not_flagged(text):
    assert ac.screen_findings(text, DOC) == []


# --- who opens what ----------------------------------------------------------------

def test_each_page_is_opened_as_every_role_it_is_for(monkeypatch):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Admin")
    got = sorted((v["route"], v["as"]) for v in ac.visits(DOC))
    assert got == [("/children", "Parent"), ("/dashboard", "Admin"), ("/login", "signed out"),
                   ("/slots", "Doctor"), ("/slots", "Parent")]


# --- reading what the browser saw ----------------------------------------------------

def _visit(route="/slots", who="Parent"):
    return {"page": "PAGE-003", "route": route, "name": "Slots", "entity": "Slot", "as": who}


def test_every_fact_the_browser_reports_is_a_finding():
    shot = {"status": 200, "landed": "/slots", "text": "Slots 09:00", "errors": ["pageerror: x is not a function"],
            "states": {"empty": {"status": 500, "errors": []}, "missing": {"status": 404, "errors": []}},
            "controls": [{"kind": "button", "label": "Book", "outcome": "workflow-failed", "detail": "HTTP 500"},
                         {"kind": "link", "label": "Back", "outcome": "navigated"}]}
    found = ac.shot_findings(shot, _visit(), DOC)
    assert any("x is not a function" in f for f in found)
    assert any("with nothing to show it breaks" in f for f in found)
    assert any('button "Book" runs a workflow that fails (HTTP 500)' in f for f in found)
    assert not any("Back" in f for f in found) and not any("record that does not exist" in f for f in found)


def test_a_signed_in_person_sent_to_sign_in_and_a_refused_role_are_findings():
    assert any("sends a signed-in Parent to /login" in f
               for f in ac.shot_findings({"status": 200, "landed": "/login"}, _visit(), DOC))
    assert any("HTTP 403 — the role it is for is refused" in f
               for f in ac.shot_findings({"status": 403}, _visit(), DOC))
    assert ac.shot_findings({"skipped": "no record to open"}, _visit(), DOC) == []


def test_pages_are_checked_role_by_role_and_a_swallowed_read_lands_on_its_pages(monkeypatch, tmp_path):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Admin")
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, ref: (f"{ref} (preview)", [{"name": "c"}]))
    batches = []

    def run_shots(app, entries, out, **k):
        batches.append(([e["id"] for e in entries], k))
        return [{"id": e["id"], "status": 200, "landed": e["route"], "text": "ok", "states": {}, "controls": []}
                for e in entries]
    monkeypatch.setattr("services.blueprint.page_review.run_shots", run_shots)
    said = iter([[], ["[forge:swallowed] list Child failed: Unknown entity: Child"]])
    report = ac.check_pages(SimpleNamespace(base="http://x"), DOC, ac.visits(DOC), tmp_path,
                            server_said=lambda: next(said))
    assert {tuple(sorted(ids)) for ids, _k in batches} == {
        ("PAGE-002::Parent", "PAGE-003::Parent"), ("PAGE-003::Doctor",), ("PAGE-004::Admin",), ("PAGE-001::signed out",)}
    assert any(k == {"probe": False, "states": False} for ids, k in batches if ids == ["PAGE-001::signed out"])
    assert report["PAGE-002"]["findings"] == [
        ("Parent", "the server could not read its Child records: "
                   "[forge:swallowed] list Child failed: Unknown entity: Child")]
    assert report["PAGE-003"]["findings"] == [] and report["PAGE-004"]["findings"] == []


# --- the check, its repairs and its record -------------------------------------------

class _Svc:
    def __init__(self, out: Path, doc: dict):
        self.output_dir, self.doc, self.saved = str(out), json.loads(json.dumps(doc)), []

    def save(self):
        self.saved.append(json.loads(json.dumps(self.doc)))


class _App:
    def __init__(self, _root):
        pass

    def __enter__(self):
        return SimpleNamespace(base="http://x")

    def __exit__(self, *a):
        pass


def test_a_failing_page_goes_to_smith_and_is_checked_again(monkeypatch, tmp_path):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Admin")
    monkeypatch.setattr("services.blueprint.app_check.visits",
                        lambda doc: [_visit("/slots", "Parent"), {**_visit("/dashboard", "Admin"), "page": "PAGE-004",
                                                                    "name": "Dashboard"}])
    rounds = []

    def check_pages(app, doc, todo, out_dir, *, server_said):
        rounds.append(sorted(v["route"] for v in todo))
        broken = len(rounds) == 1
        return {v["page"]: {"name": v["name"], "route": v["route"],
                            "findings": [(v["as"], "slots show dates in 2001")] if broken and v["route"] == "/slots" else []}
                for v in todo}
    monkeypatch.setattr(ac, "check_pages", check_pages)
    asks = []
    svc = _Svc(tmp_path, DOC)
    out = ac.check_app(svc, str(tmp_path), app_factory=_App, record=False,
                       run_turn=lambda pid, od, ask, **k: asks.append((ask, k)) or {"answer": "fixed"})
    assert rounds == [["/dashboard", "/slots"], ["/slots"]]          # only the repaired page again
    assert len(asks) == 1 and "as Parent: slots show dates in 2001" in asks[0][0] and asks[0][1]["unattended"]
    assert out == {"pages": 2, "working": 2, "fixed": ["/slots"], "left": [], "touched": []}
    assert svc.doc["runtime"]["check"] == {"pages": 2, "working": 2, "fixed": ["/slots"], "failing": [],
                                           "version": 0}


def test_what_still_fails_is_recorded_by_name(monkeypatch, tmp_path):
    monkeypatch.setattr("services.blueprint.app_check.visits", lambda doc: [_visit()])
    monkeypatch.setattr(ac, "check_pages", lambda app, doc, todo, out_dir, *, server_said: {
        "PAGE-003": {"name": "Slots", "route": "/slots", "findings": [("Parent", "it answers HTTP 500")]}})
    svc = _Svc(tmp_path, DOC)
    out = ac.check_app(svc, str(tmp_path), app_factory=_App, record=False, run_turn=lambda *a, **k: {})
    assert out["working"] == 0 and out["left"][0]["route"] == "/slots"
    runtime = svc.doc["runtime"]
    assert runtime["check"]["failing"] == ["/slots"]
    assert runtime["issues"] == [{"kind": "page_check", "page": "PAGE-003", "name": "Slots", "route": "/slots",
                                  "detail": "as Parent: it answers HTTP 500"}]


def test_the_record_of_the_check_is_declared_in_the_contract():
    import jsonschema
    contract = json.loads((Path(__file__).resolve().parents[2] / "contracts/blueprint.schema.json").read_text())
    runtime = contract["properties"]["runtime"]
    jsonschema.validate({"check": {"pages": 3, "working": 2, "fixed": ["/a"], "failing": ["/b"]}}, runtime)


def test_the_build_uses_the_app_after_its_processes_run():
    src = (Path(__file__).resolve().parents[2] / "routers/blueprint_generate.py").read_text()
    body = src[src.index("def _finish_unfinished_pages"):]
    body = body[:body.index("\ndef ")]
    assert body.index("prove_processes(") < body.index("check_app(")

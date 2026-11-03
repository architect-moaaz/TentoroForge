"""Whole-application checks and the translation sweep (2026-10-31).

What DITANS needed was done by hand because no check asked the whole
question: every process run on a copy, every drawn screen shown by a page,
every drawn word in Arabic, every demo person signing in where they belong,
the look of a whole portal. Each is one `run_checks` now, read like the
build's own checks, and the words are filled by `translate_words`.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.blueprint.service import BlueprintService
from services.smith import app_checks, trials, writes
from services.smith.translate import translate_words


def _drawn_doc() -> dict:
    return {
        "designSources": [{"id": "FIGMA-001", "treatAs": "specification", "frames": [
            {"nodeId": "1:1", "name": "Find talent"}, {"nodeId": "1:2", "name": "Find talent (phone)"},
            {"nodeId": "1:3", "name": "Hiring team hub"}, {"nodeId": "1:4", "name": "Invitation email"}]}],
        "drawnPairs": [{"phone": "1:2", "wide": "1:1"}],
        "pages": [{"id": "P1", "name": "Find talent", "route": "/find-talent", "figmaFrame": "1:1"},
                  {"id": "P2", "name": "Old list", "route": "/old"},
                  {"id": "P3", "name": "Sign in", "route": "/login", "pattern": "auth"}],
    }


def test_drawn_screens_and_screens_are_matched_both_ways():
    out = app_checks.drawing(_drawn_doc())
    red = {r["label"]: r["why"] for r in out["red"]}
    # The phone drawing counts as shown: its desktop twin is.
    assert set(red) == {'drawn screen "Hiring team hub"', 'drawn screen "Invitation email"', "screen Old list (/old)"}
    assert "an email" in red['drawn screen "Invitation email"'] and "retire it" in red["screen Old list (/old)"]
    assert "/find-talent" in out["green"] and out["total"] == 4 + 2           # the sign-in page is not counted
    assert "not built from a drawn design" in app_checks.drawing({"pages": []})["note"]


def test_every_drawn_word_is_asked_in_every_language(monkeypatch):
    import services.drawn.words as words
    doc = {"product": {"locale": "en", "languages": ["en", "ar"], "words": {"ar": {"Find talent": "ابحث عن المواهب"}}},
           "drawnViews": [{"key": "s", "kind": "screen", "name": "S", "code": "x"}]}
    monkeypatch.setattr(words, "shown_words", lambda d: ["Find talent", "Saved searches", "Remote only"])
    out = app_checks.words(doc)
    assert out["red"][0]["label"] == "ar: 2 of 3 words untranslated" and "translate_words" in out["red"][0]["why"]
    lines = trials._check_lines("words", out, holds="languages show every drawn word")
    assert lines[0] == "checks · words: 0 of 1 languages show every drawn word, 1 not right"


def test_the_sweep_fills_the_table_as_one_version(tmp_path, monkeypatch):
    import services.drawn.words as words
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Jobs", domain="hiring")
    svc.doc["product"] = {**(svc.doc.get("product") or {}), "locale": "en", "languages": ["en", "ar"],
                          "words": {"ar": {"Find talent": "ابحث عن المواهب"}}}
    svc.doc["drawnViews"] = [{"key": "s", "kind": "screen", "name": "S", "code": "x"}]
    svc.save()
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(words, "shown_words", lambda d: ["Find talent", "Saved searches", "Remote only"])
    asked = []

    def client(*, system, user, schema):
        asked.append(json.loads(user.split("\n", 1)[1]))
        return SimpleNamespace(text=json.dumps({"words": [{"source": "Saved searches", "text": "عمليات البحث المحفوظة"},
                                                          {"source": "Remote only", "text": "عن بعد فقط"},
                                                          {"source": "Invented", "text": "x"}]}))
    before = svc.doc["version"]
    out = translate_words(str(tmp_path), "ar", client=client)
    assert asked == [["Saved searches", "Remote only"]]
    assert out["applied"] and "Translated 2 words" in out["said"] and "all done" in out["said"]
    doc = BlueprintService.load(output_dir=str(tmp_path)).doc
    assert doc["version"] == before + 1
    assert doc["product"]["words"]["ar"] == {"Find talent": "ابحث عن المواهب", "Saved searches": "عمليات البحث المحفوظة",
                                             "Remote only": "عن بعد فقط"}
    assert json.loads((tmp_path / "app/public/words/ar.json").read_text())["Remote only"] == "عن بعد فقط"
    again = translate_words(str(tmp_path), "ar", client=client)
    assert not again["applied"] and "already translated" in again["finding"]


def test_every_workflow_is_run_and_none_is_repaired(monkeypatch, tmp_path):
    import services.blueprint.process_trials as pt
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Jobs", domain="hiring")
    svc.save()
    doc = {"workflows": [{"id": "FLOW-1", "name": "Apply"}, {"id": "FLOW-2", "name": "Shortlist"},
                         {"id": "FLOW-3", "name": "Nightly", "trigger": {"kind": "schedule"}}]}
    seen = {}

    def prove(svc, output_dir, **kw):
        seen.update(kw)
        assert kw["bench_factory"]("x") is bench
        return {"passed": ["Apply"], "left": [{"name": "Shortlist", "reason": "step 2: no such column"}], "untried": []}
    monkeypatch.setattr(pt, "prove_processes", prove)
    bench = object()
    out = app_checks.workflows(bench, doc, str(tmp_path))
    assert seen["rounds"] == 0 and seen["record"] is False and seen["only"] == {"FLOW-1", "FLOW-2"}
    assert out["total"] == 2 and out["red"] == [{"label": "Shortlist", "why": "step 2: no such column"}]
    app_checks.workflows(bench, doc, str(tmp_path), ["shortlist"])
    assert seen["only"] == {"FLOW-2"}


def test_every_demo_person_signs_in_belongs_and_lands(monkeypatch):
    import services.blueprint.account_model as am
    import services.blueprint.page_review as pr
    import services.blueprint.projection as proj
    monkeypatch.setattr(am, "demo_logins", lambda d: [("admin@example.com", "Admin"), ("recruiter@example.com", "Recruiter"),
                                                      ("agency.user@example.com", "Agency User"),
                                                      ("candidate@example.com", "Candidate")])
    monkeypatch.setattr(proj, "tenancy_policy", lambda d: {"kind": "organisation", "memberRoles": ["Recruiter", "Agency User"]})
    sessions = {"admin@example.com": {"user": {"role": "Admin"}}, "recruiter@example.com": {"user": {"role": "Recruiter"}},
                "agency.user@example.com": {"user": {"role": "Agency User"}}, "candidate@example.com": {}}

    class Opener:
        def open(self, url, timeout=0):
            return SimpleNamespace(geturl=lambda: "http://x/home", status=200)
    monkeypatch.setattr(app_checks, "_sign_in", lambda base, email, pw: (sessions[email], Opener()))
    monkeypatch.setattr(pr, "_query", lambda app, sql: [[""]] if "agency" in sql else [["org-1"]])
    bench = SimpleNamespace(app=lambda: SimpleNamespace(base="http://x"))
    out = app_checks.logins(bench, {})
    red = {r["label"]: r["why"] for r in out["red"]}
    assert set(red) == {"Agency User (agency.user@example.com)", "Candidate (candidate@example.com)"}
    assert "belongs to no organisation" in red["Agency User (agency.user@example.com)"]
    assert "cannot sign in" in red["Candidate (candidate@example.com)"]
    assert "Recruiter (recruiter@example.com) → /home" in out["green"]


def test_a_portal_is_looked_at_in_one_call(monkeypatch):
    import services.blueprint.page_review as pr
    monkeypatch.setattr(trials, "_entry", lambda bench, doc, r, as_: (None, {"route": r}, "x"))
    calls = []

    def shots(app, entries, out, **kw):
        calls.append((len(entries), kw))
        return [{"route": e["route"], "look": {"noHand": [{"label": "Find talent", "where": "frame", "n": 1}]}
                 if e["route"] == "/a" else {}} for e in entries]
    monkeypatch.setattr(pr, "run_shots", shots)
    bench = SimpleNamespace(app=lambda: None, output_dir="/tmp/x")
    lines = app_checks.looks(bench, {}, [f"/{c}" for c in "abcdefghijklmn"], "")
    assert calls == [(12, {"probe": False, "states": False, "look": True})]
    assert lines[0] == "checks · looks: 11 of 12 screens measure right"
    assert any("arrow" in l for l in lines) and "2 more screens were not measured" in lines[-1]


def test_run_checks_offers_the_new_kinds():
    said, args = next((d, a) for n, d, a in trials.TRIALS if n == "run_checks")
    for kind in ("`workflows`", "`drawing`", "`words`", "`logins`", "`newcomers`", "`looks`"):
        assert kind in said
    assert args["workflows"] == "array"
    with pytest.raises(ValueError, match="workflows, drawing, words, logins, newcomers, looks"):
        trials.run_checks(SimpleNamespace(), {}, "nope", [], [], "")
    assert any(n == "translate_words" for n, _d, _a in writes.WRITES)


def test_a_newcomers_walk_reads_what_the_server_render_threw():
    """DITANS QA (2026-11-02): the jobs screen answered 200 and drew "not found"
    later; the CV builder crashed inside a 200. Both travel in the page's stream."""
    from services.smith.app_checks import _thrown
    page = ('2a:E{\\"digest\\":\\"NEXT_HTTP_ERROR_FALLBACK;404\\",\\"name\\":\\"Error\\",\\"message\\":\\"x\\"}'
            '3b:E{\\"digest\\":\\"2487021552\\",\\"name\\":\\"TypeError\\",\\"message\\":\\"Cannot read\\"}'
            '4c:E{\\"digest\\":\\"\\",\\"name\\":\\"Error\\",\\"message\\":\\"ENOENT\\"}')
    thrown = _thrown(page)
    assert ("NEXT_HTTP_ERROR_FALLBACK;404", "Error", "x") in thrown
    assert ("2487021552", "TypeError", "Cannot read") in thrown
    assert ("", "Error", "ENOENT") in thrown          # caught: no digest, not a crash

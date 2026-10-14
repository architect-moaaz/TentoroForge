"""A check that fails on its own account says "could not try", never "does
not work" — and nothing is sent to repair for it.

ECom L2 (2026-10-11): ten of sixteen pages the app check sent to Smith had
failed only because the check's screenshot script timed out
(`page_shots.mjs:154`); each repair was a twelve-step unattended turn on a
page that was fine, and the "fixes" changed pages nobody had seen broken."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from services.blueprint import app_check as ac
from services.blueprint import process_trials as pt
from services.blueprint.page_review import ReviewUnavailable
from services.smith import trials
from tests.services.test_the_whole_app_is_used import DOC


class _Svc:
    def __init__(self, out: Path, doc: dict):
        self.out, self.doc = out, json.loads(json.dumps(doc))
        self.save()

    def save(self) -> None:
        p = self.out / ".forge" / "blueprint" / "current.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.doc))


class _App:
    def __init__(self, root):
        pass

    def __enter__(self):
        return SimpleNamespace(base="http://x")

    def __exit__(self, *a):
        return None


def _visit(route="/slots", who="Parent", page="PAGE-003"):
    return {"page": page, "route": route, "name": "Slots", "entity": "Slot", "as": who}


def _setup(monkeypatch, shots_by_role):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Admin")
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, ref: (f"{ref} (preview)", [{"name": "c"}]))
    monkeypatch.setattr("services.blueprint.app_check.arrival_findings", lambda app, doc, out: [])
    monkeypatch.setattr("services.blueprint.app_check.flow_move_findings", lambda doc, v, shot: [])

    def run_shots(app, entries, out, **k):
        got = shots_by_role[Path(out).name]
        if isinstance(got, Exception):
            raise got
        return got
    monkeypatch.setattr("services.blueprint.page_review.run_shots", run_shots)


def test_a_browser_that_cannot_open_the_pages_is_not_a_fault_of_the_pages(tmp_path, monkeypatch):
    _setup(monkeypatch, {"parent": ReviewUnavailable("chromium did not start"),
                         "doctor": [{"id": ac.visit_id(_visit(who="Doctor")), "status": 200, "landed": "/slots",
                                     "text": "Slots 09:00", "errors": ["navigation: Timeout 30000ms exceeded"]}]})
    monkeypatch.setattr(ac, "visits", lambda doc: [_visit(), _visit(who="Doctor")])
    svc = _Svc(tmp_path, DOC)
    turns = []
    out = ac.check_app(svc, str(tmp_path), app_factory=_App, run_turn=lambda *a, **k: turns.append(a) or {})
    assert turns == []                                             # nothing was sent to repair
    assert out["left"] == [] and [u["route"] for u in out["untried"]] == ["/slots"]
    reasons = out["untried"][0]["reasons"]
    assert any("chromium did not start" in r for r in reasons) and any("browser failed" in r for r in reasons)
    check = svc.doc["runtime"]["check"]
    assert check["untried"] == ["/slots"] and check["failing"] == [] and check["working"] == 0
    assert not [i for i in svc.doc["runtime"].get("issues") or [] if i.get("kind") == "page_check"]


def test_a_page_that_is_wrong_is_still_a_finding_beside_the_checks_own_failure(tmp_path, monkeypatch):
    shot = {"id": ac.visit_id(_visit()), "status": 500, "landed": "/slots", "text": "",
            "errors": ["screenshot: page closed", "pageerror: x is not a function"]}
    _setup(monkeypatch, {"parent": [shot]})
    monkeypatch.setattr(ac, "visits", lambda doc: [_visit()])
    svc = _Svc(tmp_path, DOC)
    out = ac.check_app(svc, str(tmp_path), app_factory=_App, rounds=0, run_turn=lambda *a, **k: {})
    assert [t["route"] for t in out["left"]] == ["/slots"]
    said = " ".join(out["left"][0]["findings"])
    assert "HTTP 500" in said and "x is not a function" in said and "screenshot" not in said
    assert out["untried"] == []                                    # a failing page is red, not untried


def test_an_app_that_cannot_start_leaves_every_page_untried(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "visits", lambda doc: [_visit()])

    class _Down(_App):
        def __enter__(self):
            raise RuntimeError("next dev would not start")
    svc = _Svc(tmp_path, DOC)
    turns = []
    out = ac.check_app(svc, str(tmp_path), app_factory=_Down, run_turn=lambda *a, **k: turns.append(a) or {})
    assert turns == [] and out["left"] == []
    assert "would not start" in out["untried"][0]["reasons"][0]


def test_processes_the_app_could_not_run_are_untried_not_failing(tmp_path, monkeypatch):
    from tests.services.test_every_process_runs_through import DOC as PDOC, _Bench, _client, _setup as _pt_setup
    _pt_setup(tmp_path, monkeypatch, {})

    class _Down(_Bench):
        def app(self):
            raise trials.TrialUnavailable("next dev would not start")
    svc = _Svc(tmp_path, PDOC)
    turns = []
    out = pt.prove_processes(svc, str(tmp_path), client=_client([]), bench_factory=_Down,
                             run_turn=lambda *a, **k: turns.append(a) or {})
    assert turns == [] and out["left"] == []
    assert len(out["untried"]) == 2 and "would not start" in out["untried"][0]["reason"]
    assert not [i for i in svc.doc["runtime"].get("issues") or [] if i.get("kind") == "process"]


def test_process_trials_that_crash_leave_every_process_untried_with_the_reason(tmp_path, monkeypatch):
    """The trial server hung up mid-run on ECom L5 (2026-10-11); the loop logged
    it and the card said "0 of 29" with no reason. The check's own crash is
    untried, named, never red."""
    from services.blueprint import fix_to_green as ftg
    from services.blueprint import scorecard as sc
    from tests.services.test_every_process_runs_through import DOC as PDOC
    svc = _Svc(tmp_path, PDOC)
    sc.seed_from_boot(svc)
    monkeypatch.setattr("services.blueprint.page_repair._repair_pages", lambda *a, **k: {"fixed": [], "left": []})
    monkeypatch.setattr("services.blueprint.app_check._check_app",
                        lambda *a, **k: {"pages": 0, "working": 0, "fixed": [], "left": [], "untried": [], "touched": []})

    def boom(*a, **k):
        raise ConnectionResetError("Remote end closed connection without response")
    monkeypatch.setattr("services.blueprint.process_trials._prove_processes", boom)
    monkeypatch.setattr(ftg, "_on_a_bench", lambda *a, **k: {})
    ftg._check_everything(svc, str(tmp_path), str(tmp_path / "app"), None, say=lambda t: None, run_turn=lambda *a, **k: {},
                          app_factory=None, bench_factory=None, client=None, cancelled=lambda: False, record=False)
    logic = sc.read(svc.doc)["criteria"]["logic"]
    assert logic["red"] == [] and len(logic["untried"]) == 2
    assert "Remote end closed" in logic["untried"][0]["why"]


def test_a_trial_request_is_asked_again_when_the_server_hangs_up(monkeypatch):
    import http.client
    from types import SimpleNamespace
    from services.smith import trials
    calls = []

    class _Resp:
        status = 200
        def read(self): return b"ok"
        def __enter__(self): return self
        def __exit__(self, *a): return None

    class _Opener:
        def open(self, req, timeout=0):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise http.client.RemoteDisconnected("Remote end closed connection without response")
            return _Resp()
    monkeypatch.setattr("urllib.request.build_opener", lambda *a: _Opener())
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert trials._http(SimpleNamespace(base="http://x"), "GET", "/p", None, []) == (200, "", "ok")
    assert len(calls) == 2

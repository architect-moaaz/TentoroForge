"""The build's check is not the app's fault when its own server stops.

6m1a22xb (forge-v3, 2026-10-22 17:06): the check's `next dev` held 6.1 GB
under a 4 GB heap cap and the kernel killed it. Every page tried after that
met a refused connection, and the Publish dialog said "4 of 20 pages passed":
`/stay-lookup` "breaks with nothing to show (ERR_EMPTY_RESPONSE)", `/login`
"could not be tried" — read by everyone as sixteen broken pages.

So a check server is held to what the host counts (resident memory, not the
heap), started afresh between people when it grows past `TRIAL_RSS_MB` and at
once past `TRIAL_RSS_CEILING_MB`, and what was lost while it was down is asked
again. What is still lost after `RESTARTS` is "could not try", never a fault.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from services import dev_servers
from services.blueprint import app_check as ac
from services.blueprint.page_review import ReviewUnavailable
from tests.services.test_a_tooling_fault_is_not_a_repair import DOC, _Svc, _visit

REFUSED = "navigation: page.goto: net::ERR_EMPTY_RESPONSE at http://127.0.0.1:56109/stay-lookup"


class _Server:
    """A check server that can be asked, measured and started afresh."""

    def __init__(self, up: bool = True, rss: int = 100):
        self.base = "http://x"
        self.generation = 1
        self.up = up
        self.rss = rss
        self.restarts: list[str] = []

    def answers(self, timeout: float = 10) -> bool:
        return self.up

    def rss_mb(self) -> int:
        return self.rss

    def restart(self, why: str, *, if_generation: int | None = None) -> bool:
        self.restarts.append(why)
        self.generation += 1
        self.up, self.rss = True, 100
        return True


def _setup(monkeypatch, run_shots, arrival=lambda app, doc, out: []):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Admin")
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, ref: (f"{ref} (preview)", [{"name": "c"}]))
    monkeypatch.setattr("services.blueprint.app_check.arrival_findings", arrival)
    monkeypatch.setattr("services.blueprint.app_check.flow_move_findings", lambda doc, v, shot: [])
    monkeypatch.setattr("services.blueprint.page_review.run_shots", run_shots)


def _ok(v):
    """A page that opened fine — `v` a visit, or an entry `run_shots` was given."""
    return {"id": v.get("id") or ac.visit_id(v), "status": 200, "landed": v["route"], "text": "Stays"}


def test_a_state_the_check_could_not_reach_is_the_checks_failure_not_the_pages():
    shot = {"id": "x", "status": 200, "landed": "/stay-lookup", "text": "Stays",
            "states": {"empty": {"status": None, "errors": [REFUSED]}}}
    visit = {**_visit("/stay-lookup"), "as": "Requester"}
    assert ac.shot_findings(shot, visit, DOC) == []
    assert ac.unreachable(shot)
    assert any("ERR_EMPTY_RESPONSE" in f and "empty state" in f for f in ac.tooling_faults(shot))
    # A page that really breaks with nothing to show still does.
    real = {**shot, "states": {"empty": {"status": 500, "errors": ["pageerror: rows.map is not a function"]}}}
    assert any("with nothing to show it breaks" in f for f in ac.shot_findings(real, visit, DOC))


def test_pages_lost_while_the_server_was_down_are_asked_again_after_it_is_started_afresh(tmp_path, monkeypatch):
    server = _Server()
    visits = [_visit("/stay-lookup", "Requester", "PAGE-007"), _visit("/cases/mine", "Requester", "PAGE-003")]
    calls: list[list[str]] = []

    def run_shots(app, entries, out, **k):
        calls.append([e["route"] for e in entries])
        if len(calls) == 1:
            server.up = False                           # killed under the second page
            return [_ok(visits[0]) | {"id": entries[0]["id"]},
                    {"id": entries[1]["id"], "unavailable": "could not sign in: connect ECONNREFUSED 127.0.0.1:56109"}]
        return [_ok(v) for v in visits if ac.visit_id(v) in {e["id"] for e in entries}]
    _setup(monkeypatch, run_shots)
    report = ac.check_pages(server, DOC, visits, tmp_path)
    assert len(server.restarts) == 1 and "stopped answering" in server.restarts[0]
    assert calls == [["/stay-lookup", "/cases/mine"], ["/cases/mine"]]  # only what was lost is asked again
    assert all(not p["findings"] and not p["untried"] for p in report.values())


def test_what_is_still_lost_after_the_restarts_is_untried_and_never_repaired(tmp_path, monkeypatch):
    server = _Server()

    def run_shots(app, entries, out, **k):
        server.up = False
        return [{"id": e["id"], "status": 200, "landed": e["route"], "text": "",
                 "states": {"empty": {"errors": [REFUSED]}}} for e in entries]
    _setup(monkeypatch, run_shots)
    monkeypatch.setattr(ac, "visits", lambda doc: [_visit("/stay-lookup", "Requester", "PAGE-007")])

    class _App:
        def __init__(self, root):
            pass

        def __enter__(self):
            return server

        def __exit__(self, *a):
            return None
    svc = _Svc(tmp_path, DOC)
    turns = []
    out = ac.check_app(svc, str(tmp_path), app_factory=_App, run_turn=lambda *a, **k: turns.append(a) or {})
    assert turns == [] and out["left"] == []
    assert [u["route"] for u in out["untried"]] == ["/stay-lookup"]
    assert len(server.restarts) == ac.RESTARTS
    assert svc.doc["runtime"]["check"]["untried"] == ["/stay-lookup"]
    assert ac.publish_note(str(tmp_path))["untried"] == ["/stay-lookup"]


def test_signing_in_that_could_not_be_tried_is_untried_not_a_finding(tmp_path, monkeypatch):
    server = _Server(up=False)

    def arrival(app, doc, out):
        if server.generation == 1:
            raise ReviewUnavailable("screenshots failed: could not sign in: connect ECONNREFUSED 127.0.0.1:56109")
        return []
    _setup(monkeypatch, lambda app, entries, out, **k: [_ok(e) for e in entries], arrival)
    login = {"page": "PAGE-020", "route": "/login", "name": "Sign in", "entity": None, "as": "signed out"}
    report = ac.check_pages(server, DOC, [login], tmp_path)
    assert report["PAGE-020"]["findings"] == [] and report["PAGE-020"]["untried"] == []
    assert len(server.restarts) == 1                     # started afresh, then signing in was tried again

    server2 = _Server(up=False)

    def never(app, doc, out):
        raise ReviewUnavailable("screenshots failed: could not sign in: connect ECONNREFUSED 127.0.0.1:56109")
    _setup(monkeypatch, lambda app, entries, out, **k: [_ok(e) for e in entries], never)
    report = ac.check_pages(server2, DOC, [login], tmp_path)
    assert report["PAGE-020"]["findings"] == []
    assert "could not be tried" in report["PAGE-020"]["untried"][0][1]


def test_a_server_grown_past_its_share_is_started_afresh_before_the_next_persons_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_servers, "TRIAL_RSS_MB", 3000)
    server = _Server(rss=3500)
    _setup(monkeypatch, lambda app, entries, out, **k: [_ok(e) for e in entries])
    ac.check_pages(server, DOC, [_visit("/cases/mine", "Requester", "PAGE-003")], tmp_path)
    assert len(server.restarts) == 1 and "3500 MB" in server.restarts[0]


def test_the_server_is_never_restarted_under_someone_using_it(tmp_path, monkeypatch):
    server = _Server()
    gate = ac._ServerGate(server)
    order: list[str] = []
    inside = threading.Event()

    def use():
        with gate.using():
            inside.set()
            time.sleep(0.2)
            order.append("used")
    t = threading.Thread(target=use)
    t.start()
    inside.wait(2)
    gate.restart("grew", server.generation)
    order.append("restarted")
    t.join()
    assert order == ["used", "restarted"]
    assert gate.restart("again", 1) is True and len(server.restarts) == 1   # a neighbour restarted it already


def test_a_stand_in_app_is_never_restarted(tmp_path, monkeypatch):
    from types import SimpleNamespace
    gate = ac._ServerGate(SimpleNamespace(base="http://x"))
    assert gate.restart("x", 0) is False and gate.heavy() == 0


def test_the_watch_starts_the_server_afresh_past_the_ceiling(monkeypatch, tmp_path):
    from services.blueprint import page_review as pr
    monkeypatch.setattr(pr, "WATCH_EVERY_S", 0.05)
    monkeypatch.setattr(dev_servers, "TRIAL_RSS_CEILING_MB", 4000)
    app = pr.RunningApp(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr(app, "rss_mb", lambda: 0 if seen else 5000)
    monkeypatch.setattr(app, "restart", lambda why, if_generation=None: seen.append(why) or True)
    app._watching.set()
    t = threading.Thread(target=app._watch, daemon=True)
    t.start()
    deadline = time.monotonic() + 2
    while not seen and time.monotonic() < deadline:
        time.sleep(0.02)
    app._watching.clear()
    assert seen and "5000 MB" in seen[0]


def test_memory_is_counted_over_the_whole_process_group():
    assert dev_servers.group_rss_mb(os.getpgid(0)) > 0
    assert dev_servers.group_rss_mb(0) == 0


def test_the_publish_dialog_names_the_pages_the_check_never_saw():
    src = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "deploy" / "PublishDialog.tsx").read_text()
    assert "untried?: string[]" in src and "could not be checked" in src
    assert json.loads(json.dumps(ac.publish_note("/nonexistent")))["untried"] == []


def test_a_real_server_is_started_afresh_on_its_port_with_its_database_copy_kept(monkeypatch, tmp_path):
    """A stand-in for `next dev` (a plain HTTP server answering
    `/api/auth/csrf`), killed and started afresh through `restart`."""
    import subprocess
    import sys
    from services.blueprint import page_review as pr
    (tmp_path / "api" / "auth").mkdir(parents=True)
    (tmp_path / "api" / "auth" / "csrf").write_text("{}")
    real_popen = subprocess.Popen
    started: list[int] = []

    def popen(argv, **kw):
        port = argv[argv.index("--port") + 1]
        kw.pop("env", None)
        proc = real_popen([sys.executable, "-m", "http.server", port, "--bind", "127.0.0.1"], **kw)
        started.append(proc.pid)
        return proc
    monkeypatch.setattr(pr.subprocess, "Popen", popen)
    monkeypatch.setattr(pr, "WATCH_EVERY_S", 3600.0)
    dropped: list[str] = []
    app = pr.RunningApp(tmp_path)
    app.clone = ("", "copy", "postgres://copy")
    monkeypatch.setattr(app, "_drop_copy", lambda: dropped.append("copy"))
    app._serve()
    try:
        assert app.answers() and app.generation == 1
        first = app.proc.pid
        os.killpg(first, 9)                               # what the kernel did
        app.proc.wait(5)
        assert not app.answers()
        assert app.restart("it stopped answering", if_generation=1)
        assert app.answers() and app.generation == 2 and app.proc.pid != first
        assert not app.restart("again", if_generation=1)  # a neighbour's restart is not repeated
        assert dropped == []                              # the database copy is kept across a restart
    finally:
        app._stop()
    assert dropped == ["copy"] and not app.answers()

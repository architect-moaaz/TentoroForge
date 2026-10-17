"""Two things Claude had that Smith did not (measured against the Mark 8 turns,
2026-10-17): a notebook across turns, and the application's own checks as one
try instead of one `open_page` per screen."""
from __future__ import annotations

import json

import pytest

from services.smith import notebook, tools, trials
from services.smith.loop import Observation


class _Out:
    def __init__(self, status="resolved", said="done", touched=(), finding=""):
        self.status, self.said, self.touched, self.finding = status, said, list(touched), finding


def test_a_turn_leaves_what_it_read_tried_and_changed(tmp_path):
    obs = [
        Observation(tool="read_file", args={"path": "app/src/pages/orders/view.tsx"}, status="read", said="…"),
        Observation(tool="open_page", args={"route": "/orders", "as": "Manager"}, status="read",
                    said="landed on /orders\nbrowser error: x is undefined"),
        Observation(tool="write_page_code", args={"page": "orders", "because": "x undefined"}, status="resolved",
                    said="edited", touched=["app/src/pages/orders/view.tsx"]),
    ]
    row = notebook.record(tmp_path, "the orders page is blank", obs, _Out(touched=["app/src/pages/orders/view.tsx"]))
    assert row and row["reads"] == ["read_file app/src/pages/orders/view.tsx"]
    assert row["tries"][0].startswith("open_page /orders: landed on /orders")
    assert row["changes"] == ["write_page_code  — x undefined"] or row["changes"][0].startswith("write_page_code")
    lines = (tmp_path / notebook.PATH).read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["ask"] == "the orders page is blank"


def test_the_next_turn_reads_the_newest_first_and_bounded(tmp_path):
    assert notebook.recall(tmp_path) == ""
    for i in range(10):
        notebook.record(tmp_path, f"ask {i}", [Observation(tool="read_file", args={"path": f"f{i}.ts"},
                                                            status="read", said="…")],
                        _Out(finding=f"left {i}" if i == 9 else ""))
    text = notebook.recall(tmp_path, shown=3)
    assert text.startswith("WHAT EARLIER TURNS ON THIS APPLICATION LEARNED")
    assert text.index("ask 9") < text.index("ask 8") < text.index("ask 7") and "ask 6" not in text
    assert "left: left 9" in text and "read: read_file f9.ts" in text
    assert len(notebook.recall(tmp_path, max_chars=200)) <= 200


def test_a_turn_that_did_nothing_leaves_no_line(tmp_path):
    assert notebook.record(tmp_path, "hi", [], _Out(said="")) is None
    assert not (tmp_path / notebook.PATH).exists()


def test_the_opening_page_starts_with_the_notebook(tmp_path, monkeypatch):
    from services.smith4 import context
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    doc = {"meta": {"name": "T"}, "roles": [{"id": "r1", "name": "Admin"}],
           "pages": [{"id": "p_home", "name": "Home", "route": "/", "roles": ["r1"]}],
           "requirements": [{"id": "q1", "text": "A home screen"}], "data": {"entities": []}}
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
    notebook.record(tmp_path, "earlier ask", [Observation(tool="read_file", args={"path": "a.ts"},
                                                           status="read", said="…")], _Out())
    page = context.opening("p1", str(tmp_path), "new ask")
    assert page.startswith("WHAT EARLIER TURNS") and "earlier ask" in page


# ── the checks oracle ──────────────────────────────────────────────────────

class _Bench:
    running = False

    def __init__(self):
        self.output_dir = "x"

    def app(self):
        return object()

    def server_said(self):
        return []


DOC = {"pages": [{"id": "p_orders", "name": "Orders", "route": "/orders"}, {"id": "p_home", "name": "Home", "route": "/"}],
       "data": {"entities": [{"id": "e_order", "name": "Order"}]}, "roles": [{"name": "Admin"}]}


def test_run_checks_is_a_trial_the_loop_may_call():
    assert tools.is_trial("run_checks") and tools.is_tool("run_checks")
    assert "run_checks" in tools.render()


def test_run_checks_reports_every_check_and_marks_what_is_not_right(monkeypatch):
    from services.blueprint import access_check, route_check, rule_trials
    seen = {}
    monkeypatch.setattr(route_check, "check_routes", lambda app, doc, only=None, **k: seen.update(routes=only) or {
        "total": 4, "green": [1, 2, 3], "red": [{"label": "Orders as Visitor", "why": "HTTP 200 where sign-in was expected"}],
        "untried": []})
    monkeypatch.setattr(access_check, "check_access", lambda app, doc, only=None, **k: seen.update(access=only) or {
        "total": 2, "green": [1, 2], "red": [], "untried": []})
    monkeypatch.setattr(rule_trials, "refuse_rules", lambda doc, bench, client, **k: {
        "total": 1, "green": [], "red": [], "untried": [{"label": "No refunds after 30 days", "why": "app down"}],
        "skipped": [{"label": "Totals add up", "why": "gates no process a trial can run"}]})
    monkeypatch.setattr(trials, "_rules_client", lambda: object())
    said = trials.run("run_checks", {"what": "all"}, bench=_Bench(), doc=DOC)
    assert "checks · routes: 3 of 4 screens answer as declared, 1 not right" in said
    assert "✗ Orders as Visitor: HTTP 200 where sign-in was expected" in said
    assert "checks · access: 2 of 2 record scopes hold" in said
    assert "checks · rules: 0 of 1" in said and "? No refunds" in said and "– Totals add up" in said
    assert trials.failed(said)
    assert seen == {"routes": None, "access": None}


def test_run_checks_narrows_to_the_screens_and_record_types_named(monkeypatch):
    from services.blueprint import access_check, route_check
    seen = {}
    monkeypatch.setattr(route_check, "check_routes", lambda app, doc, only=None, **k: seen.update(routes=only) or {
        "total": 1, "green": [1], "red": [], "untried": []})
    monkeypatch.setattr(access_check, "check_access", lambda app, doc, only=None, **k: seen.update(access=only) or {
        "total": 1, "green": [1], "red": [], "untried": []})
    said = trials.run("run_checks", {"what": "routes", "routes": ["/orders"]}, bench=_Bench(), doc=DOC)
    assert seen["routes"] == {"p_orders"} and not trials.failed(said)
    trials.run("run_checks", {"what": "access", "entities": "Order"}, bench=_Bench(), doc=DOC)
    assert seen["access"] == {"e_order"}
    said = trials.run("run_checks", {"what": "routes", "routes": ["/nowhere"]}, bench=_Bench(), doc=DOC)
    assert said.startswith("No screen is called /nowhere")


def test_run_checks_pages_presses_each_named_screen(monkeypatch):
    calls = []
    monkeypatch.setattr(trials, "open_page", lambda bench, doc, route, as_, sign_in=False, press=False:
                        calls.append((route, as_, press)) or f"HTTP 500 on {route}\nblank")
    said = trials.run("run_checks", {"what": "pages", "routes": ["/orders", "/"], "as": "Admin"}, bench=_Bench(), doc=DOC)
    assert calls == [("/orders", "Admin", True), ("/", "Admin", True)]
    assert "checks · page /orders as Admin: not right\n  ✗ HTTP 500 on /orders" in said and trials.failed(said)
    said = trials.run("run_checks", {"what": "pages"}, bench=_Bench(), doc=DOC)
    assert "could not run with those arguments" in said


def test_a_check_that_cannot_start_the_app_says_so(monkeypatch):
    from services.blueprint import route_check

    def boom(*a, **k):
        raise trials.TrialUnavailable("The app could not be started to try this: no node")
    monkeypatch.setattr(route_check, "check_routes", boom)
    said = trials.run("run_checks", {"what": "routes"}, bench=_Bench(), doc=DOC)
    assert "could not run — The app could not be started" in said and not trials.failed(said)

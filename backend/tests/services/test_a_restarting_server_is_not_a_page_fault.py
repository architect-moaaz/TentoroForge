"""A try that lands while the app's dev server is restarting itself (Next's
memory watchdog) sees connection errors and a page that "says it is loading".
That is not the page's fault: the try waits for the server, opens the page
once more and says what happened; a server that stays away is reported as
such and never counts as a failing page. Servers for trying an app run with
the larger trial heap so this happens less in the first place."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.smith import trials


class _FakeApp:
    def __init__(self, root, log=None, dist_dir="", **_):
        self.base = "http://127.0.0.1:1"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


GONE = {"url": "/budgets", "status": None, "state": "loading",
        "errors": ["Failed to load resource: net::ERR_EMPTY_RESPONSE",
                   "Failed to load resource: net::ERR_CONNECTION_REFUSED"], "controls": [], "text": ""}
FINE = {"url": "/budgets", "status": 200, "errors": [], "text": "Budget Overview Groceries ₹1,200",
        "controls": [{"kind": "link", "label": "Groceries", "outcome": "navigated", "detail": "/budgets/x (HTTP 200)"}]}
DOC = {"pages": [{"id": "PAGE-010", "route": "/budgets"}], "data": {"entities": []}}


@pytest.fixture
def bench(tmp_path, monkeypatch):
    b = trials.Bench(str(tmp_path), factory=_FakeApp)
    monkeypatch.setattr(trials, "_session", lambda app, doc, ref, guest=None: ("Consumer", []))
    monkeypatch.setattr(trials, "_role", lambda doc, ref: ("Consumer", False))
    return b


def _shots(monkeypatch, *answers):
    calls = []

    def fake(app, entries, shots_dir, **kw):
        calls.append(entries[0]["route"])
        return [dict(answers[min(len(calls) - 1, len(answers) - 1)])]

    monkeypatch.setattr("services.blueprint.page_review.run_shots", fake)
    return calls


def test_a_restart_is_waited_out_and_the_page_opened_again(bench, monkeypatch):
    calls = _shots(monkeypatch, GONE, FINE)
    monkeypatch.setattr(trials, "_server_back", lambda app, timeout=None: True)
    said = trials.open_page(bench, DOC, "/budgets", "Consumer")
    assert calls == ["/budgets", "/budgets"], "opened twice: once into the restart, once after"
    assert "HTTP 200" in said and "restarted" in said and "opened again once it was back" in said
    assert "browser error" not in said and "loading" not in said
    assert trials.failed(said) is False


def test_a_server_that_stays_away_is_said_and_is_not_a_page_fault(bench, monkeypatch):
    _shots(monkeypatch, GONE)
    monkeypatch.setattr(trials, "_server_back", lambda app, timeout=None: False)
    said = trials.open_page(bench, DOC, "/budgets", "Consumer")
    assert "server restarted" in said and "says nothing about the page" in said and "do not change the page" in said
    assert "browser error" not in said and "HTTP None" not in said
    assert trials.failed(said) is False


def test_the_servers_own_restart_line_counts_even_with_a_status(bench, monkeypatch, tmp_path):
    """The watchdog's line in the server log is the surest sign; a status
    squeezed in before the restart does not hide it."""
    bench.app()
    log = Path(tmp_path) / ".forge" / "trials" / "server.log"
    monkeypatch.setattr(trials, "_server_back", lambda app, timeout=None: True)

    def fake(app, entries, shots_dir, **kw):
        if not fake.calls:
            log.write_bytes(b"GET /budgets 200 in 9000ms\n \xe2\x9a\xa0 Server is approaching the used memory threshold, restarting...\n")
            fake.calls.append(1)
            return [dict(GONE, status=200)]
        return [dict(FINE)]
    fake.calls = []
    monkeypatch.setattr("services.blueprint.page_review.run_shots", fake)
    said = trials.open_page(bench, DOC, "/budgets", "Consumer")
    assert bench.restarts == 1 and "opened again once it was back" in said and trials.failed(said) is False


def test_a_press_that_hit_the_restart_is_not_a_broken_control(bench, monkeypatch):
    shot = dict(FINE, controls=[
        {"kind": "button", "label": "Transport-₹600", "outcome": "error",
         "detail": "could not be pressed: page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:1/calendar"},
        {"kind": "link", "label": "Add", "outcome": "navigated", "detail": "/transactions/add (HTTP 200)"},
    ])
    _shots(monkeypatch, shot)
    said = trials.open_page(bench, DOC, "/budgets", "Consumer")
    assert "could not be pressed — the app's server was restarting" in said
    assert ": errors" not in said
    assert trials.failed(said) is False


def test_a_real_browser_error_still_counts(bench, monkeypatch):
    _shots(monkeypatch, dict(FINE, errors=["pageerror: budget is undefined"]))
    said = trials.open_page(bench, DOC, "/budgets", "Consumer")
    assert "browser error: pageerror: budget is undefined" in said and trials.failed(said) is True


def test_trial_servers_run_with_the_larger_heap(monkeypatch):
    from services import dev_servers
    from services.blueprint import page_review
    assert dev_servers.TRIAL_HEAP_MB > dev_servers.HEAP_MB
    assert f"--max-old-space-size={dev_servers.HEAP_MB}" in dev_servers.capped_env({})["NODE_OPTIONS"]
    assert f"--max-old-space-size={dev_servers.TRIAL_HEAP_MB}" in page_review._capped({})["NODE_OPTIONS"]
    assert "--max-old-space-size=4096" in dev_servers.capped_env({}, heap_mb=4096)["NODE_OPTIONS"]
    assert dev_servers.capped_env({"NODE_OPTIONS": "--max-old-space-size=512"}, heap_mb=4096)["NODE_OPTIONS"] == "--max-old-space-size=512"


def test_the_shipped_next_config_trims_webpack_memory():
    cfg = Path("templates/standalone-app/next.config.js").read_text()
    assert "webpackMemoryOptimizations: true" in cfg

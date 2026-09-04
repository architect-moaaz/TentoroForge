"""The account of a run has to outlive the run.

Three builds stopped mid-DAG in one night and each post-mortem was archaeology:
file mtimes, socket queues, thread counts, and inferring the last node from
which Blueprint sections were missing. One of those answers was wrong — a run
that had ended was read as one that was hung, and the fix proposed for it would
have changed nothing.
"""
from __future__ import annotations

import json

from services.blueprint.run_ledger import RunLedger, explain, read, runs


def _stalled(out) -> str:
    """A run that dies mid-composition, as the PLC build did."""
    rid = "20260901-000000-abc123"
    led = RunLedger(out, rid, phase="build")
    led.planned(["requirements", "data_model", "page_contracts",
                 "page_layouts", "testing", "preview"])
    for n in ("requirements", "data_model", "page_contracts"):
        led.node_start(n)
        led.node_done(n, artifacts=3)
    led.node_start("page_layouts", subjects=44)
    led.crashed(RuntimeError("boom mid-composition"))
    return rid


def test_a_run_that_dies_says_where_it_stopped(tmp_path):
    _stalled(tmp_path)
    info = explain(tmp_path)

    assert info["found"] is True
    # The question every post-mortem opened with, answered from one file.
    assert info["stoppedIn"] == ["page_layouts"]
    assert info["neverStarted"] == ["testing", "preview"]
    assert info["completed"] == ["requirements", "data_model", "page_contracts"]
    assert info["endedCleanly"] is False
    assert "boom mid-composition" in info["crashed"]["error"]


def test_the_plan_is_written_before_anything_runs(tmp_path):
    """A run that dies in its opening seconds must still say what it meant to
    do — "which of the eighteen never started" is otherwise unanswerable."""
    rid = "20260901-010000-def456"
    led = RunLedger(tmp_path, rid)
    led.planned(["a", "b", "c"])
    # nothing else happens: the process is gone

    events = read(tmp_path, rid)
    assert [e["event"] for e in events] == ["run:start", "plan"]

    # This process is alive, so the run reads as still running and its nodes
    # are pending rather than never-started — "never started" is a verdict, and
    # a verdict needs the run to be over.
    assert explain(tmp_path, rid)["pending"] == ["a", "b", "c"]


def test_a_run_whose_process_died_is_over_even_though_it_said_nothing(tmp_path):
    """The case this module exists for. A killed process records no outcome, so
    "no end event" cannot mean "still running" — the pid written at run:start
    is what settles it, as a fact rather than a timeout guessing at one."""
    import json

    rid = "20260901-100000-dead99"
    led = RunLedger(tmp_path, rid)
    led.planned(["a", "b"])
    led.node_start("a")

    # Rewrite run:start with a pid that cannot be alive.
    path = tmp_path / ".forge" / "runs" / f"{rid}.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["pid"] = 2 ** 22          # far above any real pid on this platform
    lines[0] = json.dumps(first)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    info = explain(tmp_path, rid)
    assert info["running"] is False
    assert info["endedBy"] == "process gone"
    assert info["stoppedIn"] == ["a"]
    assert info["neverStarted"] == ["b"]


def test_each_event_is_flushed_as_it_happens(tmp_path):
    """Buffering until the end loses the record exactly when it is wanted."""
    rid = "20260901-020000-ghi789"
    led = RunLedger(tmp_path, rid)
    led.planned(["a"])
    led.node_start("a")

    # Read from a separate handle while the ledger is still open.
    path = tmp_path / ".forge" / "runs" / f"{rid}.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[-1])["event"] == "node:start"


def test_a_truncated_final_line_does_not_lose_the_rest(tmp_path):
    """A half-written line means the process died mid-write. That is worth
    knowing, and it must not cost the lines before it."""
    rid = _stalled(tmp_path)
    path = tmp_path / ".forge" / "runs" / f"{rid}.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + '{"event": "node:do',
                    encoding="utf-8")

    assert explain(tmp_path, rid)["stoppedIn"] == ["page_layouts"]


def test_the_ledger_never_raises_at_the_run(tmp_path):
    """It describes the run; it does not get to end it."""
    # A file where a directory must go: mkdir fails, and so does every write.
    (tmp_path / "nowhere").write_text("not a directory", encoding="utf-8")
    led = RunLedger(tmp_path / "nowhere" / "deep", "rid")
    # Every one of these is best-effort and must stay quiet.
    led.planned(["a"])
    led.node_start("a")
    led.node_failed("a", "whatever")
    led.finish(type("R", (), {"completed": [], "failed": ["a"], "blocked": [],
                              "skipped": [], "failed_because": {},
                              "skipped_because": {}})())


def test_runs_are_listed_newest_first(tmp_path):
    import time

    for rid in ("20260901-000000-aaa", "20260901-010000-bbb"):
        RunLedger(tmp_path, rid).planned(["a"])
        time.sleep(0.01)
    assert runs(tmp_path)[0] == "20260901-010000-bbb"


def test_a_clean_run_records_its_outcome(tmp_path):
    rid = "20260901-030000-jkl012"
    led = RunLedger(tmp_path, rid)
    led.planned(["a", "b"])
    for n in ("a", "b"):
        led.node_start(n)
        led.node_done(n)
    led.finish(type("R", (), {"completed": ["a", "b"], "failed": [],
                              "blocked": [], "skipped": [],
                              "failed_because": {}, "skipped_because": {}})())

    info = explain(tmp_path, rid)
    assert info["endedCleanly"] is True
    assert info["stoppedIn"] == []
    assert info["crashed"] is None


def test_a_live_run_is_not_described_as_a_stalled_one(tmp_path):
    """Both a working run and a dead one leave nodes that started and never
    finished. Calling them `stoppedIn` regardless reported four nodes running
    normally in a wave as the place a healthy run had stopped — a diagnostic
    that reads "working" as "stopped" sends the next post-mortem exactly where
    the last one went wrong.
    """
    rid = "20260901-090000-live01"
    led = RunLedger(tmp_path, rid, phase="build")
    led.planned(["data_model", "design_system", "page_layouts", "preview"])
    led.node_start("data_model")
    led.node_done("data_model")
    led.node_start("design_system")      # in flight, nothing wrong
    led.node_start("page_layouts")       # in flight

    info = explain(tmp_path, rid)
    assert info["running"] is True
    assert info["inFlight"] == ["design_system", "page_layouts"]
    assert info["stoppedIn"] == []
    # "Never started" is not a finding while more can still start.
    assert info["neverStarted"] == []
    assert info["pending"] == ["preview"]


def test_once_it_is_over_the_same_nodes_are_where_it_stopped(tmp_path):
    rid = "20260901-090000-dead01"
    led = RunLedger(tmp_path, rid, phase="build")
    led.planned(["data_model", "page_layouts", "preview"])
    led.node_start("data_model")
    led.node_done("data_model")
    led.node_start("page_layouts")
    led.crashed(RuntimeError("gone"))

    info = explain(tmp_path, rid)
    assert info["running"] is False
    assert info["stoppedIn"] == ["page_layouts"]
    assert info["inFlight"] == []
    assert info["neverStarted"] == ["preview"]
    assert info["pending"] == []


def test_a_node_that_finished_is_never_reported_as_pending(tmp_path):
    """Service and projection nodes emitted `node:done` without `node:start`,
    so `explain` listed a node that had RUN as still waiting to run — the exact
    misreading this ledger exists to prevent.

    Fixed at the source (all node kinds now emit a start) and again here, since
    a ledger written by an older build must not produce a wrong verdict when
    read by a newer one.
    """
    rid = "20260901-110000-svc001"
    led = RunLedger(tmp_path, rid)
    led.planned(["data_model", "apis", "preview"])
    led.node_start("data_model")
    led.node_done("data_model")
    led.node_done("apis")            # done with no start, as older runs wrote

    info = explain(tmp_path, rid)
    assert "apis" in info["completed"]
    assert "apis" not in info["pending"]
    assert info["pending"] == ["preview"]

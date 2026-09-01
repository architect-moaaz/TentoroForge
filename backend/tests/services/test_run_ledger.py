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
    assert explain(tmp_path, rid)["neverStarted"] == ["a", "b", "c"]


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

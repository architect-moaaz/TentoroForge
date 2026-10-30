"""A worker restarting is not the platform restarting. The backend runs two
workers; uvicorn replaced one that missed its health ping, and the new one
closed every open run as "the platform restarted while it ran" — among them
Personal Finance's checks, alive in their own process, told to its owner as
lost (u8w3uw4j, 2026-10-22). A run is closed when the process that opened it
is gone, or its number now belongs to a process that began after it."""
from __future__ import annotations

import json
import os
import time

from services import run_registry


def _ledger(root, app: str, pid: int, at: str) -> str:
    runs = root / app / ".forge" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{app}-run.jsonl"
    path.write_text(json.dumps({"event": "run:start", "phase": "checks", "at": at, "pid": pid}) + "\n"
                    + json.dumps({"event": "run:heartbeat", "at": at}) + "\n")
    return str(path)


def _ended(path: str) -> bool:
    return "run:crashed" in open(path).read()


def test_a_run_whose_process_is_alive_is_left_open(tmp_path, monkeypatch):
    now = time.time()
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    monkeypatch.setattr(run_registry, "_process_started", lambda pid: now - 600 if pid == 4242 else None)
    alive = _ledger(tmp_path, "pf", 4242, at)
    gone = _ledger(tmp_path, "cm", 5151, at)
    closed = run_registry.close_orphaned_ledgers(tmp_path)
    assert not _ended(alive), "its process still runs it"
    assert _ended(gone) and closed == ["cm-run"]


def test_a_number_taken_by_a_newer_process_is_not_the_runs(tmp_path, monkeypatch):
    now = time.time()
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
    monkeypatch.setattr(run_registry, "_process_started", lambda pid: now - 60)
    path = _ledger(tmp_path, "pf", 9, at)
    run_registry.close_orphaned_ledgers(tmp_path)
    assert _ended(path), "pid 9 is a new worker, begun after the run"


def test_this_process_never_counts_as_the_writer(tmp_path, monkeypatch):
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    monkeypatch.setattr(run_registry, "_process_started", lambda pid: 0.0)
    path = _ledger(tmp_path, "pf", os.getpid(), at)
    run_registry.close_orphaned_ledgers(tmp_path)
    assert _ended(path)


def test_a_live_build_in_its_own_process_is_left_open_on_any_platform(tmp_path):
    """No /proc on a Mac: every live run read as dead, and a backend restart
    closed DITANS's running D4 build as lost (2026-10-30). A real process,
    begun before its run, is read as alive wherever it runs."""
    import subprocess

    child = subprocess.Popen(["sleep", "30"])
    try:
        time.sleep(1.2)
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path = _ledger(tmp_path, "ditans", child.pid, at)
        assert abs(run_registry._process_started(child.pid) - time.time()) < 10
        run_registry.close_orphaned_ledgers(tmp_path)
        assert not _ended(path)
    finally:
        child.kill()

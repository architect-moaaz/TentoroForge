"""A build that reached its boot check died on Windows with
`AttributeError: module 'signal' has no attribute 'SIGKILL'`, after the whole application had
been written: the check ended `npm run dev` with `os.killpg(os.getpgid(...))` and `signal.SIGKILL`,
none of which Windows has. `kill_process_tree` ends the tree on both.

The real tree kill runs on whatever platform the suite runs on (a parent that starts a child that
sleeps; both must be gone). The POSIX sequence is pinned with fakes, since a Windows machine
cannot signal a group.
"""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from services import process_tree
from services.process_tree import kill_process_tree

PARENT = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        import os
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def test_the_whole_tree_is_gone_not_just_the_root():
    kwargs = {"start_new_session": True} if sys.platform != "win32" else {}
    proc = subprocess.Popen([sys.executable, "-c", PARENT], stdout=subprocess.PIPE, text=True, **kwargs)
    try:
        child_pid = int(proc.stdout.readline())
        assert _alive(proc.pid) and _alive(child_pid)

        kill_process_tree(proc, grace=15)

        assert proc.poll() is not None, "the root is gone"
        deadline = time.time() + 15
        while _alive(child_pid) and time.time() < deadline:
            time.sleep(0.2)
        assert not _alive(child_pid), "and so is what it started — it was left running, holding the pipe"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_a_process_that_is_already_gone_is_not_an_error():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    kill_process_tree(proc)  # must not raise


def test_posix_asks_politely_then_for_certain(monkeypatch):
    sent = []

    class Stubborn:
        pid = 4242

        def poll(self):
            return None

        def wait(self, timeout=None):
            if len(sent) < 2:  # survives SIGTERM
                raise subprocess.TimeoutExpired("x", timeout)

    monkeypatch.setattr(process_tree.sys, "platform", "linux")
    monkeypatch.setattr(process_tree.os, "getpgid", lambda pid: pid + 1, raising=False)
    monkeypatch.setattr(process_tree.os, "killpg", lambda pgid, sig: sent.append((pgid, sig)), raising=False)
    monkeypatch.setattr(process_tree.signal, "SIGKILL", 9, raising=False)  # absent on Windows

    kill_process_tree(Stubborn(), grace=0)
    assert sent == [(4243, process_tree.signal.SIGTERM), (4243, 9)], "the group, TERM first, then KILL"


def test_posix_stops_at_a_group_that_is_already_gone(monkeypatch):
    calls = []

    class Gone:
        pid = 7

        def poll(self):
            return None

    def killpg(pgid, sig):
        calls.append(sig)
        raise ProcessLookupError

    monkeypatch.setattr(process_tree.sys, "platform", "linux")
    monkeypatch.setattr(process_tree.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(process_tree.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(process_tree.signal, "SIGKILL", 9, raising=False)
    kill_process_tree(Gone())
    assert len(calls) == 1, "nothing left to signal, so it stops"


def test_windows_walks_the_tree_with_taskkill(monkeypatch):
    ran = []

    class P:
        pid = 99

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(process_tree.sys, "platform", "win32")
    monkeypatch.setattr(process_tree.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    kill_process_tree(P())
    assert ran == [["taskkill", "/PID", "99", "/T", "/F"]]


def test_the_two_build_paths_use_it_and_not_posix_only_calls():
    """The call sites that took the build down must not name what Windows lacks."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "services" / "blueprint"
    for name in ("assembly.py", "page_review.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "kill_process_tree" in src, name
        assert "SIGKILL" not in src and "killpg" not in src, f"{name} still calls POSIX-only process-group signals"


# ---------------------------------------------------------------------------
# The next thing the same build tripped on: the boot check's first request.
# ---------------------------------------------------------------------------

def test_the_first_request_may_take_as_long_as_the_boot_is_allowed(monkeypatch):
    """`GET /login?callbackUrl=%2Fmovies 200 in 60334ms` — the server answered, the check had given up
    at a fixed 60. The request is the first compile; it gets the boot's own patience."""
    from services.blueprint.assembly import boot_request_timeout

    monkeypatch.delenv("FORGE_BOOT_REQUEST_TIMEOUT", raising=False)
    assert boot_request_timeout(120) == 120.0, "the default boot timeout, not a hard-coded 60"
    assert boot_request_timeout(30) == 60.0, "never less than a minute for a cold compile"
    monkeypatch.setenv("FORGE_BOOT_REQUEST_TIMEOUT", "240")
    assert boot_request_timeout(120) == 240.0, "a slower machine can say so"
    monkeypatch.setenv("FORGE_BOOT_REQUEST_TIMEOUT", "nonsense")
    assert boot_request_timeout(120) == 120.0, "an unreadable override is ignored, not fatal"


def test_the_boot_check_no_longer_hard_codes_its_request_timeout():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "services" / "blueprint" / "assembly.py").read_text(encoding="utf-8")
    assert "urlopen(url, timeout=60)" not in src
    assert "boot_request_timeout(timeout)" in src

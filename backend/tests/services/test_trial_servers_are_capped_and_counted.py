"""No trial server can take the host (forge-v3, 2026-10-09).

A generated app's page pulls ~6,700 modules and `next dev` keeps every page
it compiled: E-commerce's trial server reached 7.5 GB beside Data entry's
2.5 GB, the host had 845 MB left, a backend worker missed its health ping and
was replaced (a tester's Smith turn died with it), and the kernel killed the
server. Every dev server now runs with a heap cap, and at most a few trial
servers run at once; the rest wait for a slot.
"""
from __future__ import annotations

import time

import pytest

from services import dev_servers


def test_every_dev_server_runs_with_the_heap_cap():
    env = dev_servers.capped_env({"PATH": "/bin"})
    assert f"--max-old-space-size={dev_servers.HEAP_MB}" in env["NODE_OPTIONS"]
    kept = dev_servers.capped_env({"NODE_OPTIONS": "--max-old-space-size=1024"})
    assert kept["NODE_OPTIONS"] == "--max-old-space-size=1024", "one already set is kept"
    added = dev_servers.capped_env({"NODE_OPTIONS": "--enable-source-maps"})
    assert added["NODE_OPTIONS"].startswith("--enable-source-maps --max-old-space-size=")
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    review = (root / "services/blueprint/page_review.py").read_text()
    assert "env = _capped({" in review and "start_new_session=True, env=env)" in review
    assert "env=_capped_env({" in (root / "services/blueprint/assembly.py").read_text()
    assert (root / "services/preview_manager.py").read_text().count("env=_capped_env(env)") == 2


def test_only_so_many_trial_servers_run_at_once(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_servers, "DIR", tmp_path)
    a, b, c = (dev_servers.TrialSlot(wait_s=0.5, slots=2) for _ in range(3))
    assert {a.acquire(), b.acquire()} == {0, 1}
    started = time.monotonic()
    with pytest.raises(dev_servers.SlotUnavailable):
        c.acquire()
    assert time.monotonic() - started >= 0.5, "it waited before giving up"
    a.release()
    assert c.acquire() in (0, 1), "a released slot is the next one's"
    b.release(); c.release()


def test_a_review_that_cannot_get_a_slot_says_so(tmp_path, monkeypatch):
    from services.blueprint.page_review import ReviewUnavailable, RunningApp
    monkeypatch.setattr(dev_servers, "DIR", tmp_path)
    monkeypatch.setattr(dev_servers, "MAX_TRIALS", 1)
    monkeypatch.setattr(dev_servers, "SLOT_WAIT_S", 0.2)
    held = dev_servers.TrialSlot()
    held.acquire()
    with pytest.raises(ReviewUnavailable, match="already being tried"):
        RunningApp(tmp_path).__enter__()
    held.release()

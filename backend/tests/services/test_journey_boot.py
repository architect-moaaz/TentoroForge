"""Unit tests for the journey-verifier boot orchestrator.

We test the observable contract:
  - reachable app → yields booted=False, no process spawned
  - unreachable + valid package.json → spawns, yields booted=True with a pid
  - unreachable + no package.json → BootError
  - boot timeout → BootError with log tail
  - exception inside the with-block → child process is killed

We do NOT hit the real network or spawn real node here — that would make
the suite slow and flaky. Instead we monkeypatch `_reachable` and the
subprocess seam.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.journey_verifier import boot as boot_mod
from services.journey_verifier.boot import BootError, booted_app


def _fake_reachable(states: list[bool]):
    """Pop bools off `states` to simulate reachability transitions."""
    it = iter(states)
    def _r(url, *, timeout_s: int = 2) -> bool:
        try:
            return next(it)
        except StopIteration:
            return True
    return _r


class _FakePopen:
    """Minimum stand-in for subprocess.Popen — remembers what was called
    and pretends to still be running until terminate()."""
    instances: list["_FakePopen"] = []

    def __init__(self, *a, **kw):
        self.args = a
        self.kwargs = kw
        self.pid = 44444
        self._terminated = False
        self._return = None
        _FakePopen.instances.append(self)

    def poll(self):
        return self._return

    def wait(self, timeout=None):
        if self._terminated:
            self._return = 0
            return 0
        # In the "process never dies" branch let the CM SIGKILL path run.
        raise subprocess.TimeoutExpired(cmd=self.args, timeout=timeout)

    def terminate(self):
        self._terminated = True

    def kill(self):
        self._terminated = True


def _install_fake_popen(monkeypatch):
    _FakePopen.instances.clear()
    monkeypatch.setattr(boot_mod.subprocess, "Popen", _FakePopen)
    # os.killpg → just mark terminated (no real signalling in tests)
    monkeypatch.setattr(
        boot_mod.os, "killpg",
        lambda pid, sig: _FakePopen.instances[-1].terminate() if _FakePopen.instances else None,
    )
    monkeypatch.setattr(boot_mod.os, "getpgid", lambda pid: pid)


def test_already_up_yields_not_booted(monkeypatch, tmp_path):
    monkeypatch.setattr(boot_mod, "_reachable", _fake_reachable([True]))
    _install_fake_popen(monkeypatch)

    with booted_app(tmp_path, base_url="http://localhost:9999") as info:
        assert info["booted"] is False
        assert info["pid"] is None

    # Never spawned anything
    assert _FakePopen.instances == []


def test_boots_when_unreachable(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "next dev"}}', encoding="utf-8")
    # First probe = unreachable; second inside _wait_for_boot = reachable
    monkeypatch.setattr(boot_mod, "_reachable", _fake_reachable([False, True]))
    _install_fake_popen(monkeypatch)

    with booted_app(tmp_path, base_url="http://localhost:9999", boot_timeout_s=5) as info:
        assert info["booted"] is True
        assert info["pid"] == 44444
        assert info["url"] == "http://localhost:9999"

    # Cleanup ran
    assert _FakePopen.instances[0]._terminated


def test_bootless_when_no_package_json(monkeypatch, tmp_path):
    monkeypatch.setattr(boot_mod, "_reachable", _fake_reachable([False]))
    _install_fake_popen(monkeypatch)

    with pytest.raises(BootError, match="no package.json"):
        with booted_app(tmp_path, base_url="http://localhost:9999") as _:
            pass


def test_boot_timeout_raises_with_log_tail(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "next dev"}}', encoding="utf-8")
    # Always unreachable → _wait_for_boot exhausts its budget
    monkeypatch.setattr(boot_mod, "_reachable", lambda url, timeout_s=2: False)
    monkeypatch.setattr(boot_mod.time, "sleep", lambda _s: None)  # skip 1s delays
    _install_fake_popen(monkeypatch)

    # Write something into the log path that _tail will surface
    log_path = tmp_path / ".journey-boot.log"
    log_path.write_text("Error: EADDRINUSE port 9999 already in use\n", encoding="utf-8")

    with pytest.raises(BootError) as exc:
        with booted_app(
            tmp_path, base_url="http://localhost:9999", boot_timeout_s=1,
            log_sink=log_path,
        ) as _:
            pass

    assert "9999" in str(exc.value) or "1s" in str(exc.value)
    # Process was still killed on the way out
    assert _FakePopen.instances[0]._terminated


def test_exception_inside_block_still_kills_child(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "next dev"}}', encoding="utf-8")
    monkeypatch.setattr(boot_mod, "_reachable", _fake_reachable([False, True]))
    _install_fake_popen(monkeypatch)

    class Boom(Exception): ...

    with pytest.raises(Boom):
        with booted_app(tmp_path, base_url="http://localhost:9999", boot_timeout_s=5) as info:
            assert info["booted"] is True
            raise Boom("verifier exploded")

    assert _FakePopen.instances[0]._terminated

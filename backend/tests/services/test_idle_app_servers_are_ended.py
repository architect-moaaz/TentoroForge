"""The app servers nobody is using are ended, and the ones in use are not.

forge-v3, 2026-10-05: four `next dev` servers held twelve of the host's
sixteen gigabytes — three Previews opened hours earlier and a trial server
whose worker had died. The kernel killed the backend's workers, and the Smith
turns they were running died with them. These run real process groups.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from services import dev_servers


@pytest.fixture(autouse=True)
def _own_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_servers, "DIR", tmp_path / "servers")
    yield


@pytest.fixture
def servers():
    started: list[subprocess.Popen] = []

    def start() -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"],
                                start_new_session=True)
        started.append(proc)
        return proc
    yield start
    for proc in started:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        proc.wait()


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _rewrite(pid: int, **fields) -> None:
    path = dev_servers.DIR / f"{pid}.json"
    rec = json.loads(path.read_text())
    rec.update(fields)
    path.write_text(json.dumps(rec))


def _used(pid: int, ago: float) -> None:
    then = time.time() - ago
    os.utime(dev_servers.DIR / f"{pid}.json", (then, then))


def _ended(proc: subprocess.Popen) -> bool:
    try:
        proc.wait(timeout=10)
        return True
    except subprocess.TimeoutExpired:
        return False


def test_a_server_whose_owner_died_is_ended(servers):
    proc = servers()
    dev_servers.track(proc.pid, port=51001, root="/apps/a", kind="review")
    _rewrite(proc.pid, owner=_dead_pid(), ownerStarted=None)

    ended = dev_servers.reap()

    assert _ended(proc), "nothing will ever stop a server whose owner is gone"
    assert ended and "the process that started it is gone" in ended[0]
    assert not list(dev_servers.DIR.glob("*.json"))


def test_a_server_at_work_is_left_alone_however_long_it_runs(servers):
    proc = servers()
    dev_servers.track(proc.pid, port=51002, root="/apps/b", kind="review")
    _used(proc.pid, ago=6 * 3600)

    assert dev_servers.reap() == []
    assert proc.poll() is None, "a review ends its own server when its work ends"


def test_an_idle_preview_is_ended_and_comes_back_when_opened(servers):
    proc = servers()
    dev_servers.track(proc.pid, port=3201, root="/apps/c/app", kind="preview", key="c")
    _used(proc.pid, ago=dev_servers.PREVIEW_IDLE_S + 60)

    ended = dev_servers.reap()

    assert _ended(proc)
    assert "not opened for" in ended[0]
    assert dev_servers.was_reaped(proc.pid), "the health check must not restart it as a crash"
    assert dev_servers.reaped("c") == "/apps/c/app"
    assert dev_servers.reaped("c") is None, "one request brings it back, not every one"


def test_a_preview_in_use_stays(servers):
    proc = servers()
    dev_servers.track(proc.pid, port=3202, root="/apps/d/app", kind="preview", key="d")
    _used(proc.pid, ago=dev_servers.PREVIEW_IDLE_S + 60)
    dev_servers.touch(3202)

    assert dev_servers.reap() == []
    assert proc.poll() is None


def test_previews_beyond_the_cap_end_stalest_first(servers, monkeypatch):
    monkeypatch.setattr(dev_servers, "MAX_PREVIEWS", 2)
    procs = [servers() for _ in range(3)]
    for i, proc in enumerate(procs):
        dev_servers.track(proc.pid, port=3210 + i, root=f"/apps/{i}/app", kind="preview", key=str(i))
        _used(proc.pid, ago=600 - i * 100)

    assert dev_servers.make_room(keep=2) == 1
    assert _ended(procs[0]), "the one opened longest ago goes"
    assert procs[1].poll() is None and procs[2].poll() is None


def test_a_server_that_already_stopped_is_forgotten(servers):
    proc = servers()
    dev_servers.track(proc.pid, port=51003, root="/apps/e", kind="boot-check")
    os.killpg(proc.pid, 9)
    proc.wait()

    assert dev_servers.reap() == []
    assert not list(dev_servers.DIR.glob("*"))


def test_a_number_reused_by_another_process_is_not_killed(servers):
    proc = servers()
    dev_servers.track(proc.pid, port=51004, root="/apps/f", kind="review")
    # As if the server had ended and its number now belonged to this process.
    _rewrite(proc.pid, started="some other start", owner=_dead_pid(), ownerStarted=None)

    dev_servers.reap()

    assert proc.poll() is None, "a stranger in a recycled process group is never ended"
    assert not list(dev_servers.DIR.glob("*.json"))

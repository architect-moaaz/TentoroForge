"""PR #28 review (2026-10-22): the live preview kept its list of servers in one worker's memory, and the backend runs two workers
(`uvicorn --workers 2`). A start landed on worker A; a request that landed on worker B found nothing (503), the status said "off", the
Editor started a second server, and `_stage_here` deleted the working folder under A's running Metro. The cap of 3 was 3 per worker.

The list is now a file per project in a folder every worker shares (`services/phone_live_registry.py`). "Another worker" is played
here two ways: the module's own memory cleared between calls (a worker with nothing of its own), and a real second process.
"""
import asyncio
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from services import phone_live as pl
from services import phone_live_registry as reg
from services import phone_preview as pp

_REAL_KILL = reg.kill_pid          # the fixture below replaces it with a list


@pytest.fixture(autouse=True)
def _shared(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "DIR", tmp_path / "phone-live")
    killed: list[int] = []
    monkeypatch.setattr(reg, "kill_pid", lambda pid, force=False: killed.append(int(pid)))
    pl._servers.clear()
    pl._sync_locks.clear()
    pl._reaper = None
    yield killed
    pl._servers.clear()


def _another_worker():
    """What a worker that started nothing has: none of the first worker's memory."""
    pl._servers.clear()
    pl._sync_locks.clear()
    pl._reaper = None


def _dead_pid() -> int:
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    return done.pid


def _ready(short_id, port=5555, org="", **over):
    """Make the record of a server the first worker started and finished starting."""
    rec, created = reg.claim(short_id, "out", org=org, per_org_cap=9, global_cap=99)
    assert created
    reg.update(short_id, rec["token"], state="ready", port=port, pid=os.getpid(), pidStarted=reg._started(os.getpid()),
               stage="stage", **over)
    return rec


# ---- the second worker sees what the first started ----------------------------------------------------------------------

def test_a_second_worker_sees_a_server_the_first_started_and_passes_requests_to_the_same_port():
    _ready("abc", port=5555)
    _another_worker()
    assert pl.status("abc")["state"] == "ready"
    assert pl.port_of("abc") == 5555, "the request is passed on to the very server the first worker started"


def test_asking_for_a_start_on_the_second_worker_starts_nothing_and_leaves_the_working_folder_alone(monkeypatch):
    _ready("abc")
    _another_worker()
    started, staged = [], []

    async def fake_start(server):
        started.append(server.short_id)

    monkeypatch.setattr(pl, "_start", fake_start)
    monkeypatch.setattr(pp, "_stage_here", lambda *a, **k: staged.append(a))

    async def go():
        return pl.start("out", "abc")
    answer = asyncio.run(go())
    assert answer["state"] == "ready" and started == [] and staged == [], "no second server, no deleted folder under the first one"
    assert pl._servers == {}


def test_the_second_worker_can_mark_it_unreachable_and_stop_it(_shared):
    rec = _ready("abc")
    _another_worker()
    pl.mark_unreachable("abc")
    assert reg.get("abc")["state"] == "failed" and pl.status("abc")["state"] == "failed"
    pl.stop("abc")
    assert reg.get("abc") is None and _shared == [os.getpid()], "ended from the other worker, whose process it is"
    assert rec["token"]


def test_a_sync_asked_for_on_the_second_worker_copies_the_files_itself(monkeypatch, tmp_path):
    _ready("abc")
    reg.update("abc", stage=str(tmp_path / "stage"), outputDir=str(tmp_path / "out"))
    _another_worker()
    seen = []
    monkeypatch.setattr(pl, "sync_files", lambda real, stage: seen.append((real, stage)) or 2)
    monkeypatch.setattr(pl, "_refresh_sample_data", lambda doc, stage: 0)
    monkeypatch.setattr(pp, "native_dir", lambda out: Path(out) / "native")

    class _Service:
        @staticmethod
        def load(output_dir):
            return type("S", (), {"doc": {}})()

    monkeypatch.setattr("services.blueprint.service.BlueprintService", _Service)
    assert asyncio.run(pl.sync("abc")) == 2
    assert seen == [(tmp_path / "out" / "native", tmp_path / "stage")]


# ---- the caps are over all workers, and one organisation never ends another's server ---------------------------------------------

def test_an_organisation_over_its_cap_ends_its_own_least_recently_used_server_whichever_worker_started_it():
    _ready("one", org="X")
    time.sleep(0.02)
    _ready("two", org="X")
    _another_worker()
    rec, created = reg.claim("three", "out", org="X", per_org_cap=2, global_cap=9)
    assert created and reg.get("one") is None
    assert {r["id"] for r in reg.records()} == {"two", "three"}


def test_a_start_never_ends_another_organisations_server_to_make_room():
    _ready("x1", org="X")
    _ready("x2", org="X")
    time.sleep(0.02)
    reg.claim("y1", "out", org="Y", per_org_cap=2, global_cap=9)
    reg.claim("y2", "out", org="Y", per_org_cap=2, global_cap=9)
    reg.claim("y3", "out", org="Y", per_org_cap=2, global_cap=9)          # Y is over ITS cap: Y's oldest goes, X's two stay
    assert {r["id"] for r in reg.records()} == {"x1", "x2", "y2", "y3"}


def test_when_the_platform_is_full_a_start_is_refused_and_nobody_else_is_ended():
    for i, org in enumerate(["A", "B", "C", "D"]):
        _ready(f"s{i}", org=org)
    with pytest.raises(reg.CapReached):
        reg.claim("late", "out", org="E", per_org_cap=2, global_cap=4)
    assert {r["id"] for r in reg.records()} == {"s0", "s1", "s2", "s3"}, "all four are still there"
    assert reg.get("late") is None, "and nothing was written for the refused start"


def test_the_organisation_that_is_full_itself_can_still_start_by_ending_its_own_even_when_the_platform_is_full():
    _ready("a1", org="A")
    _ready("a2", org="A")
    _ready("b1", org="B")
    _ready("c1", org="C")
    time.sleep(0.02)
    rec, created = reg.claim("a3", "out", org="A", per_org_cap=2, global_cap=4)
    assert created and reg.get("a1") is None and {r["id"] for r in reg.records()} == {"a2", "b1", "c1", "a3"}


def test_asking_to_start_again_for_a_server_that_exists_never_counts_against_the_caps():
    for i, org in enumerate(["A", "B", "C", "D"]):
        _ready(f"s{i}", org=org)
    rec, created = reg.claim("s1", "out", org="B", per_org_cap=2, global_cap=4)
    assert created is False and rec["id"] == "s1"


def test_the_platform_refuses_with_a_sentence_and_the_router_says_so(monkeypatch):
    monkeypatch.setattr(pl, "MAX_SERVERS", 1)
    _ready("other", org="A")

    async def go():
        return pl.start("out", "mine", "B")
    with pytest.raises(pl.LiveUnavailable, match="Too many live previews"):
        asyncio.run(go())
    assert reg.get("mine") is None and reg.get("other") is not None


def test_the_record_carries_the_organisation():
    rec, _ = reg.claim("abc", "out", org="org-1")
    assert reg.get("abc")["org"] == "org-1" and rec["org"] == "org-1"


# ---- npm is ended when its start is cancelled -------------------------------------------------------------------------------------

def test_a_cancelled_step_ends_the_process_it_started(monkeypatch, tmp_path):
    ended = []
    monkeypatch.setattr(reg, "kill_pid", lambda pid, force=False: ended.append((pid, force)))
    started = {}

    class _Proc:
        pid = 4242
        returncode = None

        async def communicate(self):
            await asyncio.sleep(3600)

        def kill(self):
            started["killed"] = True

    async def fake(*args, **kw):
        started["kwargs"] = kw
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)

    async def go():
        task = asyncio.create_task(pp._run(["npm", "install"], tmp_path, {}, "Installing"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert ended == [(4242, True)], "the install is ended when the start that wanted it is stopped"
    if os.name != "nt":
        assert started["kwargs"].get("start_new_session") is True, "in its own group, so what npm started is ended with it"


def test_a_step_that_takes_too_long_ends_the_whole_process_not_only_npm(monkeypatch, tmp_path):
    ended = []
    monkeypatch.setattr(reg, "kill_pid", lambda pid, force=False: ended.append((pid, force)))
    monkeypatch.setattr(pp, "STEP_TIMEOUT", 0.05)

    class _Proc:
        pid = 777
        returncode = None

        async def communicate(self):
            await asyncio.sleep(3600)

        def kill(self):
            pass

    async def fake(*args, **kw):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
    with pytest.raises(pp.PhonePreviewError, match="took too long"):
        asyncio.run(pp._run(["npm", "install"], tmp_path, {}, "Installing"))
    assert ended == [(777, True)]


# ---- a worker that died --------------------------------------------------------------------------------------------------

def test_what_a_worker_that_died_left_is_cleared_and_the_next_start_brings_it_back(_shared):
    _ready("abc")
    gone = _dead_pid()
    reg.update("abc", owner=gone, ownerStarted=None)
    assert pl.status("abc")["state"] == "failed", "a server nobody is watching is not offered"
    assert reg.reap(600) and reg.get("abc") is None
    rec, created = reg.claim("abc", "out")
    assert created and rec["owner"] == os.getpid()


def test_a_start_whose_worker_is_gone_reads_as_off_and_the_next_start_clears_it():
    rec, _ = reg.claim("abc", "out")
    reg.update("abc", rec["token"], owner=_dead_pid(), ownerStarted=None)
    assert pl.status("abc")["state"] == "off"
    again, created = reg.claim("abc", "out")
    assert created and again["token"] != rec["token"]


def test_a_start_that_was_stopped_in_between_writes_nothing_into_the_next_one():
    first, _ = reg.claim("abc", "out")
    reg.release("abc", first["token"])
    second, _ = reg.claim("abc", "out")
    assert not reg.update("abc", first["token"], state="ready", port=1), "the old start's token no longer matches"
    assert reg.get("abc")["state"] == "starting" and reg.get("abc")["token"] == second["token"]


# ---- the reaper, from any worker -------------------------------------------------------------------------------------------

def test_reaping_ends_what_failed_what_is_idle_and_nothing_else(_shared):
    _ready("fresh")
    _ready("idle")
    os.utime(reg._path("idle"), (time.time() - 5000, time.time() - 5000))
    _ready("broken")
    reg.update("broken", state="failed", error="x")
    ended = reg.reap(600)
    assert sorted(line.split(":")[0] for line in ended) == ["broken", "idle"]
    assert reg.get("fresh") is not None and reg.get("idle") is None and reg.get("broken") is None


def test_a_reused_process_number_is_not_taken_for_the_server():
    _ready("abc")
    reg.update("abc", pidStarted="not-when-it-started", ownerStarted="also-not")
    if reg._started(os.getpid()) is None:
        pytest.skip("this system does not say when a process started (no /proc)")
    assert reg.live("abc") is None


def test_a_process_that_finished_is_not_alive_and_this_one_is():
    assert reg.pid_alive(os.getpid()) and not reg.pid_alive(_dead_pid()) and not reg.pid_alive(0)


# ---- a real second process ----------------------------------------------------------------------------------------------------

CHILD = textwrap.dedent("""
    import json, os, sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from services import phone_live_registry as reg
    reg.DIR = Path(sys.argv[2])
    rec, created = reg.claim("abc", "out")
    print(json.dumps({"created": created, "owner": os.getpid()}), flush=True)
    sys.stdin.readline()           # stay alive (a worker) until the parent says so
""")


def test_a_real_second_process_sees_the_first_and_both_cannot_start_it(tmp_path):
    backend = Path(__file__).resolve().parents[2]
    script = tmp_path / "other_worker.py"
    script.write_text(CHILD, encoding="utf-8")
    child = subprocess.Popen([sys.executable, str(script), str(backend), str(reg.DIR)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             text=True, cwd=str(backend), env={**os.environ, "PYTHONUTF8": "1"})
    try:
        said = json.loads(child.stdout.readline())
        assert said["created"] is True and said["owner"] != os.getpid()   # (the number the child itself reports: a launcher may stand in front of it)
        rec, created = reg.claim("abc", "out")
        assert created is False, "the first process holds it: this one starts nothing"
        assert rec["owner"] == said["owner"] and reg.live("abc") is not None
        child.stdin.write("\n")
        child.stdin.flush()
        child.wait(timeout=20)
        assert reg.live("abc") is None, "once that process is gone the record is no longer alive"
        again, created = reg.claim("abc", "out")
        assert created is True and again["owner"] == os.getpid()
    finally:
        if child.poll() is None:
            child.kill()


# ---- the built picture's builds: one at a time over all workers ----------------------------------------------------------------

def test_a_build_in_one_worker_is_seen_as_running_by_the_other_and_is_not_started_twice(tmp_path):
    out = tmp_path / "app"
    (out / ".forge").mkdir(parents=True)
    held = pp._take_build_lock(out)
    assert held is not None
    assert pp._take_build_lock(out) is None, "a second build cannot take the lock"
    assert pp._build_running(out) is True
    pp._release_build_lock(held)
    assert pp._build_running(out) is False
    again = pp._take_build_lock(out)
    assert again is not None
    pp._release_build_lock(again)


def test_a_build_cut_off_with_its_worker_is_not_still_building(tmp_path):
    out = tmp_path / "app"
    (out / ".forge").mkdir(parents=True)
    held = pp._take_build_lock(out)
    pp._release_build_lock(held)                   # what the system does when the worker holding it dies
    pp._write_status(out, state="building", step="Drawing the screens")
    assert pp._build_running(out) is False


def test_a_real_process_is_really_ended_when_the_step_is_cancelled(tmp_path, monkeypatch):
    """No fake: a real long-running command, started the way a step is, then cancelled."""
    monkeypatch.setattr(reg, "kill_pid", _REAL_KILL)
    pidfile = tmp_path / "pid.txt"
    code = f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); time.sleep(120)"

    async def go():
        task = asyncio.create_task(pp._run([sys.executable, "-c", code], tmp_path, dict(os.environ), "Installing"))
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text():
                break
            await asyncio.sleep(0.05)
        pid = int(pidfile.read_text())
        assert reg.pid_alive(pid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return pid
    pid = asyncio.run(go())
    for _ in range(60):
        if not reg.pid_alive(pid):
            break
        time.sleep(0.1)
    assert not reg.pid_alive(pid), "the process was still running after the step was cancelled"


def test_the_build_for_the_phone_app_ends_npm_on_a_cancel_too(tmp_path, monkeypatch):
    from services import native_build

    ended = []
    monkeypatch.setattr(reg, "kill_pid", lambda pid, force=False: ended.append((pid, force)))

    class _Proc:
        pid = 31337
        returncode = None

        async def communicate(self):
            await asyncio.sleep(3600)

        def kill(self):
            pass

    async def fake(*a, **k):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
    (tmp_path / "native").mkdir()

    async def go():
        task = asyncio.create_task(native_build._npm_run(["npm", "install"], str(tmp_path / "native"), 3600))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert ended == [(31337, True)]


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="zombies are a Linux thing")
def test_a_killed_process_that_its_parent_has_not_collected_yet_is_not_alive():
    """Found by running the tests on Linux (2026-10-23): `kill(pid, 0)` answers for a killed process until its parent collects it, so an install
    ended on a cancel still looked alive."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert reg.pid_alive(child.pid)
        child.kill()
        for _ in range(50):                    # killed, and NOT waited for: it stays in the table as a zombie
            if Path(f"/proc/{child.pid}/stat").read_text().split(")")[1].split()[0] == "Z":
                break
            time.sleep(0.05)
        assert not reg.pid_alive(child.pid)
    finally:
        child.wait()

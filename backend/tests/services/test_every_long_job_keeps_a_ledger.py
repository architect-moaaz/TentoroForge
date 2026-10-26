"""Every long job keeps a ledger, a restart closes each one once, and a stop waits for the work under way.

forge-v3, 2026-09-26 → 10-26: 13 checks and 11 Smith turns were lost to
restarts. `/smith/turn`, the Smith v4 fix, self-heal and publishes kept no
ledger, so the cutover gate could not see them; Docker gave every job ten
seconds on a stop; and both workers closed the same orphaned ledger, so it
carried `run:crashed` twice and the person was told twice.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import lost_runs, run_registry
from services.blueprint import run_ledger
from services.blueprint.run_ledger import job_ledger, ledger_kind, own_open_ledgers, wait_for_own_jobs, with_ledger


def _events(path: Path) -> list[str]:
    return [json.loads(l)["event"] for l in path.read_text().splitlines() if l.strip()]


def _runs(app: Path) -> list[Path]:
    return sorted((app / ".forge" / "runs").glob("*.jsonl"))


def test_each_ledger_says_what_kind_of_work_it_records():
    assert ledger_kind("x/20261026-101010-smith-turn.jsonl") == "turn"
    assert ledger_kind("20261026-101010-checks.jsonl") == ledger_kind("a-app-check.jsonl") == "check"
    assert ledger_kind("20261026-101010-publish.jsonl") == "publish"
    assert ledger_kind("20261026-101010-smith-fix.jsonl") == "fix"
    assert ledger_kind("20261026-101010-self-heal.jsonl") == "heal"
    assert ledger_kind("20261026-101010-a1b2c3.jsonl") == "build"
    assert lost_runs.kind_of("20261026-1-publish.jsonl") == "publish"


def test_a_job_ledger_ends_when_its_work_returns_and_crashes_when_it_raises(tmp_path):
    with job_ledger(tmp_path, "publish") as ledger:
        assert ledger is not None and ledger.kind == "publish"
    (path,) = _runs(tmp_path)
    assert path.name.endswith("-publish.jsonl") and _events(path)[-1] == "run:end"
    with pytest.raises(RuntimeError):
        with_ledger(tmp_path, "heal", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    heal = [p for p in _runs(tmp_path) if p.name.endswith("-self-heal.jsonl")][0]
    assert _events(heal)[-1] == "run:crashed"
    assert with_ledger(None, "fix", lambda a, b=0: a + b, 1, b=2) == 3, "no app, no ledger, the work still runs"


def test_only_a_turn_is_the_projects_turn(tmp_path):
    with job_ledger(tmp_path, "publish"):
        assert str(tmp_path.resolve()) not in run_registry.TURNS
    with job_ledger(tmp_path, "turn"):
        assert str(tmp_path.resolve()) in run_registry.TURNS
    assert str(tmp_path.resolve()) not in run_registry.TURNS


def test_a_publish_ledger_is_never_taken_for_a_build(tmp_path):
    """`last_build` answers "carry on"; a publish's ledger is not a build to
    resume, and a publish under way is not a build in flight."""
    runs = tmp_path / ".forge" / "runs"
    runs.mkdir(parents=True)
    (runs / "20261026-100000-a1b2c3.jsonl").write_text(
        json.dumps({"event": "run:start", "phase": "build", "at": "2026-10-26T10:00:00Z", "runId": "b"}) + "\n"
        + json.dumps({"event": "run:end", "at": "2026-10-26T10:05:00Z"}) + "\n")
    (runs / "20261026-110000-publish.jsonl").write_text(
        json.dumps({"event": "run:start", "phase": "publish", "at": "2026-10-26T11:00:00Z", "runId": "p"}) + "\n")
    assert (run_registry.last_build(tmp_path) or {}).get("runId") != "p"
    snap = run_registry.ledger_snapshot(tmp_path, turns=False)
    assert not snap or not snap.get("active"), "a publish under way is not a build in flight"


def test_a_stopped_publish_is_told_as_a_publish(tmp_path):
    said = lost_runs.message_for(tmp_path / "20261026-1-publish.jsonl", "restarted", "10:00 UTC")
    assert "published" in said and "Press Publish" in said


CLOSER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from services import run_registry
time.sleep(float(sys.argv[3]) - time.time())          # start together
print(",".join(run_registry.close_orphaned_ledgers(sys.argv[2])))
"""


def test_two_workers_close_an_orphan_once(tmp_path):
    """Both workers run `close_orphaned_ledgers` at the same moment on start."""
    backend = Path(__file__).resolve().parents[2]
    gone = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    pid = int(gone.stdout)                                # a process that has exited: the writer is gone
    for i in range(12):
        runs = tmp_path / f"app{i:02d}" / ".forge" / "runs"
        runs.mkdir(parents=True)
        (runs / f"20261026-10000{i % 10}-smith-turn.jsonl").write_text(
            json.dumps({"event": "run:start", "pid": pid, "at": "2026-10-26T10:00:00Z"}) + "\n")
    import time
    at = str(time.time() + 1.5)
    procs = [subprocess.Popen([sys.executable, "-c", CLOSER, str(backend), str(tmp_path), at],
                              stdout=subprocess.PIPE, text=True, cwd=backend) for _ in range(2)]
    outs = [p.communicate(timeout=60)[0].strip() for p in procs]
    closed = [x for o in outs for x in o.split(",") if x]
    assert len(closed) == 12, outs                       # each closed once, by one of the two
    for path in tmp_path.glob("*/.forge/runs/*.jsonl"):
        assert _events(path).count("run:crashed") == 1, path


@pytest.mark.skipif(not Path("/proc/self/stat").exists(),
                    reason="a writer's start time is read from /proc (Linux, where the platform runs)")
def test_a_ledger_whose_writer_lives_is_not_closed(tmp_path):
    runs = tmp_path / "app" / ".forge" / "runs"
    runs.mkdir(parents=True)
    path = runs / "20261026-100000-checks.jsonl"
    alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        import time as _t
        _t.sleep(0.2)
        path.write_text(json.dumps({"event": "run:start", "pid": alive.pid,
                                    "at": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())}) + "\n")
        assert run_registry.close_orphaned_ledgers(tmp_path) == []
        assert _events(path) == ["run:start"]
    finally:
        alive.kill()


def test_the_lost_run_watch_closes_once_too(tmp_path):
    runs = tmp_path / "app" / ".forge" / "runs"
    runs.mkdir(parents=True)
    path = runs / "20261026-100000-smith-turn.jsonl"
    path.write_text(json.dumps({"event": "run:start", "pid": 1, "at": "2026-10-26T10:00:00Z"}) + "\n")
    old = path.stat().st_mtime - 1000
    os.utime(path, (old, old))
    assert lost_runs.scan(tmp_path, lost_s=60) == [str(path)]
    assert lost_runs.scan(tmp_path, lost_s=60) == []
    assert _events(path).count("run:crashed") == 1


def test_a_stop_waits_for_this_processs_jobs_and_no_one_elses(tmp_path):
    import threading
    app = tmp_path / "app"
    with job_ledger(app, "turn"):
        assert own_open_ledgers(tmp_path) and own_open_ledgers(tmp_path)[0].name.endswith("-smith-turn.jsonl")
    assert own_open_ledgers(tmp_path) == []
    # Another process's open ledger is not this process's to wait for.
    other = tmp_path / "other" / ".forge" / "runs"
    other.mkdir(parents=True)
    (other / "20261026-1-checks.jsonl").write_text(json.dumps({"event": "run:start", "pid": 1}) + "\n")
    assert own_open_ledgers(tmp_path) == []

    done = threading.Event()

    def work() -> None:
        with job_ledger(app, "publish"):
            done.wait(5)
    t = threading.Thread(target=work)
    t.start()
    import time
    time.sleep(0.2)
    threading.Timer(0.5, done.set).start()
    assert wait_for_own_jobs(tmp_path, 5, poll_s=0.1) == []      # it waited for the publish to end
    t.join()
    with job_ledger(app, "turn"):
        left = wait_for_own_jobs(tmp_path, 0.3, poll_s=0.1)
    assert len(left) == 1, "what is still running at the cap is reported, not waited for"


@pytest.mark.asyncio
async def test_a_publish_keeps_a_ledger_while_it_runs(tmp_path):
    from services.deploy import runs

    async def publish(_own):
        assert any(p.name.endswith("-publish.jsonl") for p in _runs(tmp_path))
        yield SimpleNamespace(stage="snapshot", message="m", progress=10, data={})
        yield SimpleNamespace(stage="done", message="m", progress=100, data={})

    class _Sessions:
        def __call__(self):
            return self

        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return None
    queue = runs.start(publish, _Sessions(), output_dir=str(tmp_path))
    frames = []
    while (item := await asyncio.wait_for(queue.get(), 5)) is not None:
        frames.append(item["stage"])
    assert frames == ["snapshot", "done"]
    (path,) = [p for p in _runs(tmp_path) if p.name.endswith("-publish.jsonl")]
    assert _events(path)[-1] == "run:end"


def test_every_job_that_kept_none_now_does():
    """The four that the gate could not see open a ledger where they start."""
    root = Path(__file__).resolve().parents[2]
    assert 'job_ledger(root, "turn"' in (root / "routers" / "output_projects.py").read_text()
    gen = (root / "routers" / "generate.py").read_text()
    assert 'with_ledger, output_dir, "fix", _smith_turn' in gen and 'with_ledger, output_dir, "turn", _smith_turn' in gen
    assert 'with_ledger, output_dir, "heal", _smith_turn' in (root / "services" / "self_healing.py").read_text()
    assert "output_dir=project.output_dir" in (root / "routers" / "deployments.py").read_text()
    assert "--timeout-graceful-shutdown" in (root / "Dockerfile").read_text()
    assert "stop_grace_period" in (root.parent / "docker-compose.prod.yml").read_text()
    assert "wait_for_own_jobs" in (root / "main.py").read_text()
    assert run_ledger.JOB_SUFFIXES["-publish"] == "publish"

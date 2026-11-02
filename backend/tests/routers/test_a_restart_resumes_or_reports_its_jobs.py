"""A build or turn ran as a thread in one worker; when the process went, the
person was told to say "carry on" however much of the build was done
(audit, 2026-11-01). Each is a row now (`services.jobs`): the leader finds
the rows a dead worker left, resumes a build from the Blueprint's own state,
and tells the person about what cannot be resumed."""
from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services import jobs


def _dead_pid() -> int:
    """A pid that existed and is gone: the worker before the restart."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


async def _project(auth_client, org_id, tmp_path) -> dict:
    project = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Ledgerly"})).json()
    from database import async_session
    from models.project import Project
    async with async_session() as db:
        row = await db.get(Project, uuid.UUID(project["id"]))
        row.output_dir = str(tmp_path / project["short_id"])
        await db.commit()
    (tmp_path / project["short_id"]).mkdir(parents=True, exist_ok=True)
    return project


async def _job(project_id: str, *, kind: str, worker: str, resume: dict | None = None, attempts: int = 1,
               status: str = "running", beat_ago_s: float = 0) -> str:
    from database import async_session
    from models.run_job import RunJob
    now = datetime.now(timezone.utc)
    row = RunJob(id=uuid.uuid4(), project_id=uuid.UUID(project_id), kind=kind, status=status, worker=worker,
                 args={"message": "build it"}, actor={"user": "test@example.com", "org": "o", "ceiling": None},
                 resume=resume, attempts=attempts, claimed_at=now - timedelta(seconds=beat_ago_s + 60),
                 heartbeat_at=now - timedelta(seconds=beat_ago_s))
    async with async_session() as db:
        db.add(row)
        await db.commit()
    return str(row.id)


async def _row(job: str):
    from database import async_session
    from models.run_job import RunJob
    async with async_session() as db:
        return await db.get(RunJob, uuid.UUID(job))


async def _said(auth_client, project: dict) -> list[str]:
    rows = (await auth_client.get(f"/api/projects/{project['id']}/conversations")).json()
    return [r["content"] for r in rows if r["role"] == "assistant"]


@pytest.mark.asyncio
async def test_a_job_moves_from_queued_to_done_and_a_failure_is_kept(auth_client, org_id, tmp_path):
    project = await _project(auth_client, org_id, tmp_path)
    ok = await jobs.open(project_id=project["id"], kind="turn", args={"message": "hi"},
                         actor={"user": "test@example.com", "org": org_id, "ceiling": 2.5})
    assert (await _row(ok)).status == "queued"

    def work():
        assert jobs.current() == ok
        jobs.note_resume({"phase": "build", "app_name": "Ledgerly"})
        return "done"

    def run_ok():
        with jobs.working(ok):
            return work()
    assert await asyncio.get_running_loop().run_in_executor(None, run_ok) == "done"
    row = await _row(ok)
    assert row.status == "done" and row.ended_at and row.resume == {"phase": "build", "app_name": "Ledgerly"}
    assert row.actor["ceiling"] == 2.5 and row.args == {"message": "hi"} and row.worker == jobs.worker_id()

    bad = await jobs.open(project_id=project["id"], kind="build")

    def run_bad():
        with jobs.working(bad):
            raise RuntimeError("the executor is gone")
    with pytest.raises(RuntimeError):
        await asyncio.get_running_loop().run_in_executor(None, run_bad)
    row = await _row(bad)
    assert row.status == "failed" and "the executor is gone" in row.error
    assert jobs.current() is None and ok not in jobs._LIVE and bad not in jobs._LIVE


@pytest.mark.asyncio
async def test_the_leader_resumes_what_can_be_resumed_and_says_the_rest(auth_client, org_id, tmp_path):
    project = await _project(auth_client, org_id, tmp_path)
    pid, host = project["id"], socket.gethostname()
    dead = f"{host}:{_dead_pid()}"
    build = await _job(pid, kind="turn", worker=dead, resume={"phase": "build", "app_name": "Ledgerly"})
    talk = await _job(pid, kind="turn", worker=dead)                       # never reached a build
    twice = await _job(pid, kind="build", worker=dead, resume={"phase": "build"}, attempts=2)
    gone_elsewhere = await _job(pid, kind="build", worker="other-host:7", beat_ago_s=jobs.LOST_S + 5)
    alive_elsewhere = await _job(pid, kind="build", worker="other-host:7", beat_ago_s=5)
    mine = await jobs.open(project_id=pid, kind="turn")                     # live in this very process
    finished = await _job(pid, kind="build", worker=dead, status="done")

    resumed: list[str] = []

    async def resume(row):
        resumed.append(str(row.id))

    done = await jobs.recover("restarted", resume=resume)
    assert sorted(done["resumed"]) == sorted([build]) == sorted(resumed)
    assert sorted(done["reported"]) == sorted([talk, twice, gone_elsewhere])
    for j in (alive_elsewhere, mine):
        assert (await _row(j)).status == "queued" if j == mine else (await _row(j)).status == "running"
    assert (await _row(finished)).status == "done"
    assert (await _row(talk)).status == "reported" and (await _row(talk)).recovered_at

    said = await _said(auth_client, project)
    assert any("while I was working on your last message" in t and "carry on" in t for t in said), said
    assert any("picked up once after stopping like this" in t for t in said), said
    # Claimed once: a second leader's pass finds nothing left to do.
    assert await jobs.recover("restarted", resume=resume) == {"resumed": [], "reported": []}
    jobs._LIVE.pop(mine, None)


@pytest.mark.asyncio
async def test_a_restart_resumes_the_build_from_the_blueprint_and_says_so(auth_client, org_id, tmp_path,
                                                                          monkeypatch):
    from routers import blueprint_generate as router

    project = await _project(auth_client, org_id, tmp_path)
    out = tmp_path / project["short_id"]
    job = await _job(project["id"], kind="turn", worker=f"{socket.gethostname()}:{_dead_pid()}",
                     resume={"phase": "build", "app_name": "Ledgerly", "modules": ["billing"]})
    remembered: list = []
    monkeypatch.setattr(router, "_remember",
                        lambda loop, pid, role, text, meta=None, lock=None: remembered.append((role, text)))
    monkeypatch.setattr(router, "_start_checks", lambda *a, **k: None)
    seen: dict = {}

    def fake_dag(output_dir, app_root, description, *, approved, emit, app_name, documents, modules):
        from services import jobs as _jobs
        seen.update(output_dir=output_dir, description=description, approved=approved, app_name=app_name,
                    modules=modules, job=_jobs.current())
        emit("message", {"text": "Your application is built."})
        return {"status": "complete"}
    monkeypatch.setattr(router, "_run_dag", fake_dag)

    done = await jobs.recover("restarted")
    assert done == {"resumed": [job], "reported": []}
    for _ in range(100):
        if (await _row(job)).status == "done":
            break
        await asyncio.sleep(0.05)

    assert seen == dict(output_dir=str(out), description="", approved=True, app_name="Ledgerly",
                        modules=["billing"], job=job), "carried on from the Blueprint, as the job"
    row = await _row(job)
    assert row.status == "done" and row.attempts == 2 and row.worker == jobs.worker_id()
    assert remembered[0][0] == "assistant" and "picked the build up again" in remembered[0][1]
    assert ("assistant", "Your application is built.") in remembered
    assert not [r for r in remembered if r[0] == "user"], "nobody asked again"


@pytest.mark.asyncio
async def test_an_organisation_that_cannot_pay_now_is_told_instead(auth_client, org_id, tmp_path, monkeypatch):
    project = await _project(auth_client, org_id, tmp_path)
    job = await _job(project["id"], kind="build", worker=f"{socket.gethostname()}:{_dead_pid()}",
                     resume={"phase": "build"})

    async def refusal(db, **kw):
        return ["the organisation's credit is used up"]
    monkeypatch.setattr("services.credits.refusal", refusal)

    assert await jobs.recover("restarted") == {"resumed": [], "reported": [job]}
    said = await _said(auth_client, project)
    assert any("Press Build" in t and "the organisation's credit is used up" in t for t in said), said


@pytest.mark.asyncio
async def test_a_lost_ledger_a_job_speaks_for_is_not_said_twice(auth_client, org_id, tmp_path, monkeypatch):
    import json

    from services import lost_runs

    project = await _project(auth_client, org_id, tmp_path)
    await _job(project["id"], kind="build", worker=f"{socket.gethostname()}:{_dead_pid()}",
               resume={"phase": "build"})
    runs = tmp_path / "ledgers" / project["short_id"] / ".forge" / "runs"
    runs.mkdir(parents=True)
    build = runs / "20261101-120000-build1.jsonl"
    build.write_text(json.dumps({"event": "run:start", "phase": "build", "pid": 9}) + "\n")
    check = runs / "20261101-120500-checks.jsonl"
    check.write_text(json.dumps({"event": "run:start", "phase": "check", "pid": 9}) + "\n")
    monkeypatch.setattr(lost_runs, "kind_of", lambda p: "check" if "checks" in str(p) else "build")

    assert await lost_runs.tell([str(build), str(check)], "restarted") == 1
    said = await _said(auth_client, project)
    assert len(said) == 1 and "checking the application" in said[0], said


def test_every_build_and_turn_goes_on_record_and_the_leader_watches():
    import inspect

    import main
    from routers import blueprint_generate, drafts_room

    src = inspect.getsource(blueprint_generate)
    for kind in ('kind="build"', 'kind="turn"'):
        assert f"job = await jobs.open(project_id=project_id, {kind}" in src
    assert 'kind="handoff"' in inspect.getsource(drafts_room)
    assert "_start_job_recovery" in inspect.getsource(main._run_the_loops_once)
    assert "jobs.working(actor.get(\"job\"))" in inspect.getsource(blueprint_generate._acting_with)
    assert "build_slots.held(emit)" in inspect.getsource(blueprint_generate._run_dag)

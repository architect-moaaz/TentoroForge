"""Every build and Smith turn is on record while it runs (`models.run_job`),
and the ones a dead worker leaves are picked up again or said.

A build or turn is a thread in one API worker. When that process went —
a restart, the out-of-memory killer — its ledger was closed as crashed and
the person told to say "carry on" (`services.lost_runs`), however much of a
paid-for build was already done. Now:

- `open` writes the row before the work starts: the project, the kind, the
  request's arguments, who it is for and its ceiling, and this worker.
- The work runs inside `working` (in its thread): the row says running, and
  done or failed at the end. A build that reaches a run carrying on from the
  Blueprint's own state records how to carry it on (`note_resume`).
- Each worker beats for its live rows every `HEARTBEAT_S` (`beat_forever`).
- The leader (`services.leader`) runs `watch_forever`: a row still open
  whose worker is gone is claimed once, then resumed when it can be — it has
  a `resume` and has not already been resumed — or said to the person.

Recording is best-effort throughout: a job that cannot be written leaves its
work to run unrecorded, as everything ran before.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterator

logger = logging.getLogger(__name__)

#: How often a worker says its jobs are alive.
HEARTBEAT_S = 20.0
#: A job on another host whose worker has not beaten for this long is gone (`lost_runs.LOST_S`).
LOST_S = int(os.environ.get("FORGE_RUN_LOST_S") or 180)
#: How often the leader looks for jobs a dead worker left.
WATCH_EVERY_S = 60.0
#: A job is taken this many times at most: once, and once more resumed. A
#: build that takes its worker down twice (out of memory) is not started a third time.
MAX_ATTEMPTS = 2
#: How long after its recovery a job still speaks for its application's lost ledgers (`speaks_for`).
SPEAKS_FOR_S = 3600

OPEN = ("queued", "waiting", "running")

#: The jobs this process runs, by id: the event loop that opened them, which owns the database's connections.
_LIVE: dict[str, asyncio.AbstractEventLoop] = {}
_current = threading.local()


def worker_id() -> str:
    """This process, as a row names it."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(at: datetime | None) -> datetime | None:
    """SQLite returns what it was given without its zone; every time here is UTC."""
    if at is None:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _jsonable(value: Any) -> Any:
    """`value` as JSON can carry it: what cannot be said plainly is said as text."""
    import json
    return json.loads(json.dumps(value, default=str))


def current() -> str | None:
    """The job the calling thread works for, if any (`working`)."""
    return getattr(_current, "job", None)


def loop_of(job: str | None) -> asyncio.AbstractEventLoop | None:
    return _LIVE.get(job) if job else None


# ---------------------------------------------------------------------------
# The row
# ---------------------------------------------------------------------------

async def open(*, project_id: Any, kind: str, args: Any = None, actor: dict | None = None) -> str | None:
    """Put a job on record before its work starts; its id, or None when it
    could not be written (the work runs unrecorded)."""
    from database import async_session
    from models.run_job import RunJob

    job_id = uuid.uuid4()
    job = str(job_id)
    # LIVE HERE BEFORE THE ROW EXISTS: the leader's sweep in this process must
    # never find a row naming this process that this process does not know.
    _LIVE[job] = asyncio.get_running_loop()
    try:
        now = _now()
        row = RunJob(id=job_id, project_id=uuid.UUID(str(project_id)), kind=kind,
                     args=_jsonable(args), actor=_jsonable(actor), status="queued",
                     worker=worker_id(), claimed_at=now, heartbeat_at=now)
        async with async_session() as db:
            db.add(row)
            await db.commit()
    except Exception:  # noqa: BLE001 — the record never stops the work
        _LIVE.pop(job, None)
        logger.warning("[jobs] could not put a %s job for %s on record", kind, project_id, exc_info=True)
        return None
    return job


async def adopt(job: str, *, attempts: int) -> None:
    """Take a recovered job into this process: it is running here now."""
    _LIVE[job] = asyncio.get_running_loop()
    now = _now()
    await _update(job, status="running", worker=worker_id(), claimed_at=now, heartbeat_at=now,
                  attempts=attempts, ended_at=None, error=None)


async def _update(job: str, *, where_status: tuple[str, ...] | None = None, **values: Any) -> int:
    from sqlalchemy import update

    from database import async_session
    from models.run_job import RunJob

    stmt = update(RunJob).where(RunJob.id == uuid.UUID(job)).values(**values)
    if where_status:
        stmt = stmt.where(RunJob.status.in_(where_status))
    async with async_session() as db:
        res = await db.execute(stmt)
        await db.commit()
        return int(res.rowcount or 0)


async def set_status(job: str, status: str, **more: Any) -> None:
    try:
        await _update(job, status=status, heartbeat_at=_now(), **more)
    except Exception:  # noqa: BLE001
        logger.warning("[jobs] %s: could not record %s", job, status, exc_info=True)


async def finish(job: str, error: BaseException | None = None) -> None:
    await set_status(job, "failed" if error is not None else "done", ended_at=_now(),
                     error=f"{type(error).__name__}: {error}"[:2000] if error is not None else None)
    # Only once its end is written: until then a row naming this process is live in it.
    _LIVE.pop(job, None)


def _from_thread(job: str | None, make: Callable[[], Awaitable[Any]]) -> None:
    """`make()` run on the job's loop, from the work's thread, waited for."""
    loop = loop_of(job)
    if loop is None or loop.is_closed():
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    try:
        if running is loop:
            loop.create_task(make())
        else:
            asyncio.run_coroutine_threadsafe(make(), loop).result(timeout=30)
    except Exception:  # noqa: BLE001 — the record never stops the work
        logger.warning("[jobs] %s: could not reach its record", job, exc_info=True)


@contextmanager
def working(job: str | None) -> Iterator[None]:
    """The work of `job`, in its thread: running while the block runs,
    done or failed at its end, and `current()` for whatever it calls."""
    if not job:
        yield
        return
    _current.job = job
    _from_thread(job, lambda: set_status(job, "running"))
    error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        _current.job = None
        _from_thread(job, lambda: finish(job, error))


def note_resume(spec: dict) -> None:
    """From the work's thread: the job is in a run that carries on from the
    Blueprint's own state, and this is how to start it again."""
    job = current()
    if job:
        _from_thread(job, lambda: _note_resume(job, spec))


async def _note_resume(job: str, spec: dict) -> None:
    try:
        await _update(job, resume=_jsonable(spec))
    except Exception:  # noqa: BLE001
        logger.warning("[jobs] %s: could not record how to resume it", job, exc_info=True)


async def beat_forever() -> None:
    """Each worker's heartbeat for the jobs it runs."""
    from sqlalchemy import update

    from database import async_session
    from models.run_job import RunJob

    while True:
        await asyncio.sleep(HEARTBEAT_S)
        mine = [uuid.UUID(j) for j, loop in list(_LIVE.items()) if loop is asyncio.get_running_loop()]
        if not mine:
            continue
        try:
            async with async_session() as db:
                await db.execute(update(RunJob).where(RunJob.id.in_(mine)).values(heartbeat_at=_now()))
                await db.commit()
        except Exception:  # noqa: BLE001 — the beat never takes a worker down
            logger.warning("[jobs] the heartbeat failed", exc_info=True)


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

def worker_alive(row: Any, now: datetime | None = None) -> bool:
    """Whether the worker a row names is still running it. On this host,
    a fact: the pid exists and began before it took the job (a pid is reused
    after a restart), or — this very process — the job is live in it.
    Elsewhere, its heartbeat is recent."""
    now = now or _now()
    host, _, pid = str(row.worker or "").rpartition(":")
    if host and host == socket.gethostname() and pid.isdigit():
        if int(pid) == os.getpid():
            return str(row.id) in _LIVE
        from services.run_registry import _process_started

        began = _process_started(int(pid))
        claimed = _aware(row.claimed_at)
        return began is not None and claimed is not None and began <= claimed.timestamp() + 1
    beat = _aware(row.heartbeat_at)
    return beat is not None and (now - beat).total_seconds() < LOST_S


class NotResumed(Exception):
    """A job that could have been resumed and was not, with why, in words for the person."""


def resumable(row: Any) -> bool:
    return bool(row.resume) and int(row.attempts or 1) < MAX_ATTEMPTS


async def recover(why: str, *, resume: Callable[[Any], Awaitable[None]] | None = None,
                  tell: Callable[[Any, str, str], Awaitable[None]] | None = None) -> dict[str, list[str]]:
    """Every open job whose worker is gone: claimed once (`interrupted`),
    then resumed where it can be, or said to its person. Returns the ids
    by what was done."""
    from sqlalchemy import select

    from database import async_session
    from models.run_job import RunJob

    resume = resume or _resume
    tell = tell or _tell
    done: dict[str, list[str]] = {"resumed": [], "reported": []}
    async with async_session() as db:
        rows = list((await db.execute(select(RunJob).where(RunJob.status.in_(OPEN)))).scalars())
    for row in rows:
        if worker_alive(row):
            continue
        job = str(row.id)
        # ONCE, whichever leader gets there: the claim names the status it saw.
        if await _update(job, where_status=(row.status,), status="interrupted", recovered_at=_now()) != 1:
            continue
        logger.info("[jobs] %s %s on %s was left by %s", row.kind, job, row.project_id, row.worker)
        reason = ""
        if resumable(row):
            try:
                await resume(row)
                done["resumed"].append(job)
                continue
            except NotResumed as exc:
                reason = str(exc)
            except Exception:  # noqa: BLE001 — a resume that fails is said instead
                logger.exception("[jobs] %s could not be resumed", job)
        try:
            await tell(row, why, reason)
        except Exception:  # noqa: BLE001
            logger.exception("[jobs] could not tell the person about %s", job)
        await set_status(job, "reported", ended_at=_now())
        done["reported"].append(job)
    return done


async def _resume(row: Any) -> None:
    from routers.blueprint_generate import resume_job
    await resume_job(row)


def _ledger_kind(row: Any) -> str:
    return "turn" if row.kind == "turn" and not row.resume else "build"


async def _tell(row: Any, why: str, reason: str = "") -> None:
    """The person reads what stopped and how to go on (`lost_runs`)."""
    from services import lost_runs

    when = time.strftime("%H:%M UTC", time.gmtime())
    text = lost_runs.message_for_kind(_ledger_kind(row), why, when)
    if reason:
        text = f"{text} I did not pick it up again myself: {reason}"
    elif row.resume and int(row.attempts or 1) >= MAX_ATTEMPTS:
        text = (f"{text} It had already been picked up once after stopping like this, so I have not "
                "started it a third time myself.")
    await lost_runs.say(project_id=row.project_id, text=text, kind=_ledger_kind(row), why=why, ledger=str(row.id))


async def speaks_for(short_id: str) -> bool:
    """Whether a job speaks for this application's lost runs: one is open,
    or was recovered within `SPEAKS_FOR_S`. Its recovery resumes or tells,
    so the ledger it left is not said a second time (`lost_runs.tell`)."""
    from sqlalchemy import or_, select

    from database import async_session
    from models.project import Project
    from models.run_job import RunJob

    try:
        async with async_session() as db:
            hit = (await db.execute(
                select(RunJob.id).join(Project, Project.id == RunJob.project_id)
                .where(Project.short_id == short_id)
                .where(or_(RunJob.status.in_(OPEN),
                           RunJob.recovered_at >= _now() - timedelta(seconds=SPEAKS_FOR_S)))
                .limit(1))).first()
        return hit is not None
    except Exception:  # noqa: BLE001 — not knowing, the ledger is said as before
        logger.warning("[jobs] could not ask whether a job speaks for %s", short_id, exc_info=True)
        return False


async def watch_forever(*, every_s: float = WATCH_EVERY_S) -> None:
    """The leader's watch: at once (what the last process left), then every
    `every_s` (what a sibling worker that died left)."""
    why = "restarted"
    while True:
        try:
            done = await recover(why)
            if done["resumed"] or done["reported"]:
                logger.info("[jobs] resumed %s; reported %s", done["resumed"] or "-", done["reported"] or "-")
        except Exception:  # noqa: BLE001 — the watch never takes the leader down
            logger.exception("[jobs] the recovery watch failed")
        why = "stopped responding"
        await asyncio.sleep(every_s)


__all__ = ["open", "adopt", "working", "current", "note_resume", "set_status", "finish", "recover",
           "watch_forever", "beat_forever", "speaks_for", "worker_alive", "resumable", "NotResumed"]

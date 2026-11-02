"""A run whose process went away is noticed, closed, and SAID to the person
whose run it was.

A restart closes the ledgers it killed at startup; a worker that dies
while its sibling lives closes nothing — the ledger just stops pulsing.
The tester of pcn4owv7 waited an hour on "Still working on it" after the
host's out-of-memory killer took the worker running their turn
(2026-10-15 03:14 UTC). Every worker runs `watch_forever`: a ledger with
no pulse for `LOST_S` is closed as crashed, the application's chat gets
one line saying so and how to go on, and the incident is on the record.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from services import incidents

logger = logging.getLogger(__name__)

#: A turn pulses every 20 s and a build on every event; three minutes of
#: silence is a process that is gone, not a slow model call.
LOST_S = int(os.environ.get("FORGE_RUN_LOST_S") or 180)
WATCH_EVERY_S = 60


def kind_of(path: str | Path) -> str:
    from services.blueprint.run_ledger import ledger_kind
    return ledger_kind(path)


def _last_event(path: Path) -> str | None:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            tail = fh.read().decode("utf-8", "replace").strip().splitlines()
        return str(json.loads(tail[-1]).get("event") or "") if tail else None
    except (OSError, ValueError):
        return None


def scan(root: str | Path, lost_s: int | None = None) -> list[str]:
    """Close every ledger under `root` that is neither ended nor pulsing:
    `run:crashed` is appended, and the paths closed are returned."""
    lost_s = LOST_S if lost_s is None else lost_s
    closed: list[str] = []
    root = Path(root)
    if not root.is_dir():
        return closed
    now = time.time()
    for runs in root.glob("*/.forge/runs"):
        for path in runs.glob("*.jsonl"):
            last = _last_event(path)
            if last is None or last in ("run:end", "run:crashed"):
                continue
            try:
                quiet = now - os.path.getmtime(path)
            except OSError:
                continue
            if quiet < lost_s:
                continue
            from services.run_registry import close_once
            # Once, whichever worker's watch gets there first (`close_once`).
            if close_once(path, {"event": "run:crashed",
                                 "error": f"the process working on it went away — no pulse for {int(quiet)} s",
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                          still_open=lambda p: time.time() - os.path.getmtime(p) >= lost_s):
                closed.append(str(path))
    return closed


def message_for(path: str | Path, why: str, when: str) -> str:
    """What the person reads, in Smith's voice: what stopped, when, how to go on."""
    return message_for_kind(kind_of(path), why, when)


def message_for_kind(kind: str, why: str, when: str) -> str:
    cause = ("The platform restarted" if why == "restarted"
             else "The platform's process working on this went away")
    if kind == "turn":
        return (f"{cause} at {when} while I was working on your last message, and that turn was lost before "
                "it finished. Nothing you said is lost. Say “carry on” and I will pick up from where it stopped.")
    if kind == "check":
        return (f"{cause} at {when} while I was checking the application, and that check stopped before it "
                "finished. Say “check the app again” and I will run it through.")
    if kind == "publish":
        return (f"{cause} at {when} while your app was being published, and the publish stopped before it "
                "finished. Press Publish to send it again.")
    if kind in ("fix", "heal"):
        return (f"{cause} at {when} while I was fixing a fault in your app, and that fix stopped before it "
                "finished. Say “carry on” and I will look at it again.")
    if kind == "drafts":
        return (f"{cause} at {when} while the Drafts Room was working, and that run stopped before it "
                "finished. Open the Drafts Room and run it again.")
    return (f"{cause} at {when} during the build, and the build stopped before it finished. "
            "Press Build to carry on; what was already built is kept.")


async def tell(paths: list[str], why: str) -> int:
    """One line into the chat of each application a closed ledger belongs
    to, and one incident each. Returns how many were told.

    A build or turn whose job is on record is said by the job's recovery
    instead (`services.jobs`), which resumes it when it can: telling the
    person to press Build beside "I have picked it up again" is two answers."""
    from services import jobs

    when = time.strftime("%H:%M UTC", time.gmtime())
    told = 0
    for raw in paths:
        path = Path(raw)
        short_id = path.parent.parent.parent.name        # <short_id>/.forge/runs/<ledger>
        kind = kind_of(path)
        if kind in ("turn", "build") and await jobs.speaks_for(short_id):
            logger.info("[lost-runs] %s: %s is its job's to say", short_id, path.stem)
            continue
        if await say(short_id=short_id, text=message_for(path, why, when), kind=kind, why=why, ledger=path.stem):
            told += 1
    return told


async def say(*, text: str, kind: str, why: str, ledger: str, short_id: str = "", project_id: Any = None) -> bool:
    """`text` into the application's chat, as Smith, and an incident on the
    record. The application by its short id or its id. Whether it was said."""
    from sqlalchemy import select

    from database import async_session
    from models.project import Conversation, MessageRole, MessageType, Project

    if short_id:
        incidents.record(f"{kind}_lost", app=short_id, detail=text, why=why, ledger=ledger)
    try:
        async with async_session() as sess:
            where = Project.short_id == short_id if short_id else Project.id == project_id
            project = (await sess.execute(select(Project).where(where))).scalar_one_or_none()
            if project is None:
                return False
            if not short_id:
                short_id = project.short_id
                incidents.record(f"{kind}_lost", app=short_id, detail=text, why=why, ledger=ledger)
            sess.add(Conversation(project_id=project.id, role=MessageRole.assistant, content=text,
                                  message_type=MessageType.chat,
                                  metadata_={"source": "lost_run", "ledger": ledger, "why": why}))
            await sess.commit()
            logger.info("[lost-runs] told %s that %s was lost (%s)", short_id, ledger, why)
            return True
    except Exception:  # noqa: BLE001 — telling is best-effort; the ledger is closed either way
        logger.warning("[lost-runs] could not tell %s about %s", short_id or project_id, ledger, exc_info=True)
        return False


async def watch_forever() -> None:
    """Each worker's watch. Two workers watching is harmless: the first to
    close a ledger makes it ended for the second."""
    from services.project_paths import OUTPUT_ROOT
    while True:
        await asyncio.sleep(WATCH_EVERY_S)
        try:
            closed = await asyncio.to_thread(scan, OUTPUT_ROOT)
            if closed:
                await tell(closed, "stopped responding")
        except Exception:  # noqa: BLE001 — the watch never takes a worker down
            logger.exception("[lost-runs] the watch failed")

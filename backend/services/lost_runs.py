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

from services import incidents

logger = logging.getLogger(__name__)

#: A turn pulses every 20 s and a build on every event; three minutes of
#: silence is a process that is gone, not a slow model call.
LOST_S = int(os.environ.get("FORGE_RUN_LOST_S") or 180)
WATCH_EVERY_S = 60


def kind_of(path: str | Path) -> str:
    stem = Path(path).stem
    if stem.endswith("-smith-turn"):
        return "turn"
    if stem.endswith("-checks") or stem.endswith("-app-check"):
        return "check"
    return "build"


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
                if now - os.path.getmtime(path) < lost_s:
                    continue
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"event": "run:crashed",
                                         "error": "the process working on it went away — no pulse for "
                                                  f"{int(now - os.path.getmtime(path))} s",
                                         "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
                closed.append(str(path))
            except OSError:
                continue
    return closed


def message_for(path: str | Path, why: str, when: str) -> str:
    """What the person reads, in Smith's voice: what stopped, when, how to go on."""
    kind = kind_of(path)
    cause = ("The platform restarted" if why == "restarted"
             else "The platform's process working on this went away")
    if kind == "turn":
        return (f"{cause} at {when} while I was working on your last message, and that turn was lost before "
                "it finished. Nothing you said is lost. Say “carry on” and I will pick up from where it stopped.")
    if kind == "check":
        return (f"{cause} at {when} while I was checking the application, and that check stopped before it "
                "finished. Say “check the app again” and I will run it through.")
    return (f"{cause} at {when} during the build, and the build stopped before it finished. "
            "Press Build to carry on; what was already built is kept.")


async def tell(paths: list[str], why: str) -> int:
    """One line into the chat of each application a closed ledger belongs
    to, and one incident each. Returns how many were told."""
    from sqlalchemy import select

    from database import async_session
    from models.project import Conversation, MessageRole, MessageType, Project

    when = time.strftime("%H:%M UTC", time.gmtime())
    told = 0
    for raw in paths:
        path = Path(raw)
        short_id = path.parent.parent.parent.name        # <short_id>/.forge/runs/<ledger>
        text = message_for(path, why, when)
        incidents.record(f"{kind_of(path)}_lost", app=short_id, detail=text, why=why, ledger=path.stem)
        try:
            async with async_session() as sess:
                project = (await sess.execute(select(Project).where(Project.short_id == short_id))).scalar_one_or_none()
                if project is None:
                    continue
                sess.add(Conversation(project_id=project.id, role=MessageRole.assistant, content=text,
                                      message_type=MessageType.chat,
                                      metadata_={"source": "lost_run", "ledger": path.stem, "why": why}))
                await sess.commit()
                told += 1
                logger.info("[lost-runs] told %s that %s was lost (%s)", short_id, path.stem, why)
        except Exception:  # noqa: BLE001 — telling is best-effort; the ledger is closed either way
            logger.warning("[lost-runs] could not tell %s about %s", short_id, path.stem, exc_info=True)
    return told


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

"""Every `next dev` the platform starts, on disk, and the reaper that ends
the ones nobody is using.

A generated app's dev server grows to three or four gigabytes. The platform
starts them for the Preview tab, for the build's boot check, for the page
reviewer and for Smith's trials — each in its own process group, so it
survives the worker that started it. The registries that knew about them were
in that worker's memory. When a worker died (the host ran out of memory) its
servers kept running with nobody left to stop them, and a Preview opened two
hours earlier was never stopped either. On forge-v3 four of them held twelve
of the host's sixteen gigabytes; the kernel killed the reviewer's browser and
the backend's workers, and every Smith turn in flight died with them
(ihf6pjga, 2026-10-05).

So every server is written down here — one small file per process group, in a
directory every worker and every checkout on the machine shares — and a reaper
in each worker ends:

  * a server whose owner process is gone: nothing will ever use or stop it;
  * a Preview nobody has opened for `PREVIEW_IDLE_S`;
  * the least recently used Previews beyond `MAX_PREVIEWS`.

A server still in use by a live owner — a review, a trial, a boot check — is
never touched: those end themselves when their work does.

A Preview the reaper ended leaves a tombstone naming its app, so the next
request for it starts it again instead of answering 503 to an open tab.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Shared by every worker and every backend on the machine.
DIR = Path(os.environ.get("FORGE_DEV_SERVERS_DIR") or Path(tempfile.gettempdir()) / "forge-dev-servers")

#: A Preview unopened this long is ended.
PREVIEW_IDLE_S = int(os.environ.get("FORGE_PREVIEW_IDLE_MINUTES") or 30) * 60
#: At most this many Previews at once; starting one more ends the stalest.
MAX_PREVIEWS = int(os.environ.get("FORGE_MAX_PREVIEWS") or 2)
#: How long a tombstone lets an open tab bring its Preview back.
TOMBSTONE_S = 24 * 3600
#: How often each worker's reaper looks.
REAP_EVERY_S = 60


def _path(pgid: int) -> Path:
    return DIR / f"{int(pgid)}.json"


def _proc(pid: int, *, ask_ps: bool = True) -> tuple[int, str] | None:
    """(parent, start time) of `pid` as the OS tells it — the start time is
    what tells this process from a later one that reused its number. None
    when there is no such process, or it cannot be read."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # The command may hold spaces and parentheses; fields resume after
        # the last ')': state, ppid, … start time is the 20th.
        rest = stat[stat.rindex(")") + 2:].split()
        return int(rest[1]), rest[19]
    except (OSError, ValueError, IndexError):
        pass
    if Path("/proc").is_dir() or not ask_ps:
        return None
    try:
        out = subprocess.run(["ps", "-o", "ppid=,lstart=", "-p", str(int(pid))],
                             capture_output=True, text=True, timeout=5).stdout.split(None, 1)
        return int(out[0]), out[1].strip()
    except Exception:  # noqa: BLE001 — unreadable is unknown, never a reason to act
        return None


def _started(pid: int) -> str | None:
    seen = _proc(pid)
    return seen[1] if seen else None


def _alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(int(pgid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def track(pid: int, *, port: int, root: str | Path, kind: str, key: str = "") -> None:
    """A dev server started as the leader of its own process group `pid`.

    `kind` is "preview" for a server people open, anything else for one a
    piece of work started and will stop; `key` is what the Preview is found
    by again (the project's short id)."""
    # ONLY OUR OWN. A record is an order to end a process group one day; a
    # number that is not a group this process started — a test's fake, a
    # child that already exited and was replaced — must never become one.
    #
    # Read from /proc where there is one (the platform's containers). Without
    # it (a laptop) nothing is spawned to ask, here on the path that starts a
    # server: the record carries no start time and the group check is all.
    seen = _proc(int(pid), ask_ps=False)
    try:
        ours = (seen is None or seen[0] == os.getpid()) and os.getpgid(int(pid)) == int(pid)
    except OSError:
        ours = False
    if not ours:
        return
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        _path(pid).write_text(json.dumps({
            "pgid": int(pid), "port": int(port), "root": str(root), "kind": kind,
            "key": key, "owner": os.getpid(), "ownerStarted": (_proc(os.getpid(), ask_ps=False) or (0, None))[1],
            "started": seen[1] if seen else None, "at": time.time()}))
    except OSError as exc:
        logger.warning("[dev-servers] could not record %s on %s: %s", kind, port, exc)


def forget(pid: int | None) -> None:
    """The server was stopped by whoever started it."""
    if not pid:
        return
    try:
        _path(pid).unlink()
    except OSError:
        pass


def touch(port: int) -> None:
    """Someone used the server on `port` just now."""
    for path, rec in _records():
        if rec.get("port") == port:
            try:
                os.utime(path)
            except OSError:
                pass
            return


def reaped(key: str) -> str | None:
    """The app folder of `key`'s Preview if the reaper ended it, so a request
    for it can start it again. Consumed: one request brings it back."""
    if not key:
        return None
    for path in DIR.glob("*.reaped"):
        try:
            rec = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if rec.get("key") == key:
            try:
                path.unlink()
            except OSError:
                pass
            return str(rec.get("root") or "") or None
    return None


def was_reaped(pid: int) -> bool:
    """The reaper ended this server — it is not a crash to restart."""
    return (DIR / f"{int(pid)}.reaped").exists()


def _records() -> list[tuple[Path, dict[str, Any]]]:
    out = []
    try:
        paths = list(DIR.glob("*.json"))
    except OSError:
        return out
    for path in paths:
        try:
            rec = json.loads(path.read_text())
            rec["used"] = path.stat().st_mtime
        except (OSError, ValueError):
            continue
        out.append((path, rec))
    return out


def _gone(rec: dict[str, Any]) -> bool:
    """The process group is no longer the one recorded."""
    pgid = int(rec.get("pgid") or 0)
    if not pgid or not _group_alive(pgid):
        return True
    started = rec.get("started")
    return bool(started) and _started(pgid) not in (None, started)


def _orphaned(rec: dict[str, Any]) -> bool:
    owner = int(rec.get("owner") or 0)
    if not owner or not _alive(owner):
        return True
    started = rec.get("ownerStarted")
    return bool(started) and _started(owner) not in (None, started)


def _end(path: Path, rec: dict[str, Any], why: str) -> None:
    pgid = int(rec["pgid"])
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            break
        for _ in range(20):
            if not _group_alive(pgid):
                break
            time.sleep(0.25)
        if not _group_alive(pgid):
            break
    logger.info("[dev-servers] ended %s on port %s for %s (%s)", rec.get("kind"), rec.get("port"),
                rec.get("root"), why)
    try:
        if rec.get("kind") == "preview":
            path.rename(path.with_suffix(".reaped"))
        else:
            path.unlink()
    except OSError:
        pass


def make_room(*, keep: int = MAX_PREVIEWS) -> int:
    """End the least recently used Previews so at most `keep` remain.
    Returns how many were ended."""
    previews = sorted(((p, r) for p, r in _records() if r.get("kind") == "preview" and not _gone(r)),
                      key=lambda pr: pr[1]["used"])
    ended = 0
    for path, rec in previews[:max(0, len(previews) - max(0, keep))]:
        _end(path, rec, f"more than {keep} previews running")
        ended += 1
    return ended


def reap(now: float | None = None) -> list[str]:
    """One pass: forget what is gone, end what is orphaned, idle or over the
    cap. Returns a line per server ended."""
    now = time.time() if now is None else now
    ended: list[str] = []
    for path, rec in _records():
        if _gone(rec):
            forget(rec.get("pgid"))
            continue
        why = ""
        if _orphaned(rec):
            why = "the process that started it is gone"
        elif rec.get("kind") == "preview" and now - rec["used"] > PREVIEW_IDLE_S:
            why = f"not opened for {int((now - rec['used']) // 60)} minutes"
        if why:
            _end(path, rec, why)
            ended.append(f"{rec.get('kind')} {rec.get('root')}: {why}")
    ended += ["preview: more previews running than allowed"] * make_room()
    for stone in DIR.glob("*.reaped") if DIR.is_dir() else []:
        try:
            if now - stone.stat().st_mtime > TOMBSTONE_S:
                stone.unlink()
        except OSError:
            pass
    return ended


async def reaper() -> None:
    """Each worker's loop. Two workers reaping at once is harmless: ending a
    group twice finds it gone the second time."""
    import asyncio
    while True:
        try:
            await asyncio.to_thread(reap)
        except Exception:  # noqa: BLE001 — the reaper never takes a worker down
            logger.exception("[dev-servers] reap failed")
        await asyncio.sleep(REAP_EVERY_S)

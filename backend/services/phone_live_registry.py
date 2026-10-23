"""Which live phone previews are running, written on disk so that every backend worker sees the same answer.

THE LIST OF RUNNING SERVERS WAS IN ONE WORKER'S MEMORY. The backend runs `uvicorn --workers 2` (backend/Dockerfile); a start landed on
worker A, and about half of the later requests landed on worker B, which had no such server: 503 "not running" for the picture, and the
status said "off", so the Editor started a second server, which deleted the working folder under the first one's Metro. The cap of
3 servers was 3 per worker (PR #28 review, 2026-10-22).

So the answer is a small file per project in a folder every worker shares (next to `services/dev_servers.py`'s records for `next dev`):

    {id, outputDir, state, error, port, pid, stage, owner, ownerStarted, token, startedAt}

* `claim` is the only way to begin: under one lock it looks at the file; a live server or a start in progress is not started again.
* Anyone may read it, use the port, mark the server unreachable or stop it. Only the worker that claimed it (`token`) writes its
  progress, so a start that was stopped in between cannot write into a later one.
* The file's modified time is "last used". `reap` ends what is failed, idle, or left by a worker that died.
* The caps are over all workers: an organisation may hold `per_org_cap` servers and a start beyond that ends ITS OWN least recently used
  one; the platform holds `global_cap`, and a start that would pass it is refused (`CapReached`), never made by ending another
  organisation's server (PR #28 review, 2026-10-22: one organisation's start ended another's).
* A server whose owner is gone has nothing watching its files for changes: it is ended, and the next start brings it back.

No process list is trusted by number alone: where the system says when a process started (Linux `/proc`), that is kept with the number.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Iterator, Optional

from services import dev_servers

logger = logging.getLogger(__name__)

#: Shared by every worker on the machine, as `dev_servers.DIR` is.
DIR = dev_servers.DIR / "phone-live"
_LOCK_WAIT_S = 10.0


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

def pid_alive(pid: int) -> bool:
    """Whether a process with this number is running. (`os.kill(pid, 0)` ENDS the process on Windows, so it is not used there.)"""
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(ok) and code.value == 259                # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return not _is_zombie(pid)


def _is_zombie(pid: int) -> bool:
    """On Linux a process that has been killed stays in the table, answering `kill(pid, 0)` as if it lived, until its parent collects it. Found by running
    the tests on Linux (2026-10-23): a step's install, ended on a cancel, still looked alive. Such a process is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat[stat.rindex(")") + 2:].split()[0] == "Z"
    except (OSError, ValueError, IndexError):
        return False


def _started(pid: int) -> Optional[str]:
    """When the system says the process started (Linux), so a later process with the same number is not taken for it."""
    seen = dev_servers._proc(int(pid), ask_ps=False)
    return seen[1] if seen else None


class CapReached(RuntimeError):
    """The platform already runs as many live previews as it may, and none of them is the asking organisation's to end."""


def _same_process(pid: int, started: Optional[str]) -> bool:
    if not pid_alive(pid):
        return False
    return not started or _started(pid) in (None, started)


def kill_pid(pid: int, force: bool = False) -> None:
    """The dev server and what it started: `npx` is a shell around node, so one process is not enough. `force`: do not ask it to stop."""
    pid = int(pid or 0)
    if pid <= 0:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
            return
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            group = os.getpgid(pid)
        except ProcessLookupError:
            return
        if group == pid:                                      # the leader of its own group (`start_new_session`)
            os.killpg(group, sig)
        else:
            os.kill(pid, sig)
    except (OSError, subprocess.SubprocessError):
        logger.debug("[phone_live_registry] could not end %s", pid, exc_info=True)


# ---------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------

def _path(short_id: str) -> Path:
    return DIR / f"{''.join(c for c in str(short_id) if c.isalnum() or c in '-_')}.json"


@contextlib.contextmanager
def _locked(wait_s: float = _LOCK_WAIT_S) -> Iterator[None]:
    """One lock for the few lines that read and write the records (a file lock: released by the system if the holder dies)."""
    DIR.mkdir(parents=True, exist_ok=True)
    fh = open(DIR / "registry.lock", "a+")                     # noqa: SIM115 - held until the block ends
    deadline = time.monotonic() + wait_s
    try:
        while not dev_servers._try_lock(fh):
            if time.monotonic() >= deadline:
                raise TimeoutError("the live preview registry stayed locked")
            time.sleep(0.05)
        try:
            yield
        finally:
            dev_servers._unlock(fh)
    finally:
        fh.close()


def _read(path: Path) -> Optional[dict[str, Any]]:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec["used"] = path.stat().st_mtime
        return rec
    except (OSError, ValueError):
        return None


def _write(path: Path, rec: dict[str, Any]) -> None:
    rec = {k: v for k, v in rec.items() if k != "used"}
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.replace(tmp, path)


def records() -> list[dict[str, Any]]:
    try:
        paths = sorted(DIR.glob("*.json"))
    except OSError:
        return []
    return [r for r in (_read(p) for p in paths) if r]


def alive(rec: dict[str, Any]) -> bool:
    """A start in progress or a server in use, whose owner is still there. A failed one is not alive."""
    if rec.get("state") not in ("starting", "ready"):
        return False
    if not _same_process(int(rec.get("owner") or 0), rec.get("ownerStarted")):
        return False
    if rec.get("state") == "ready":
        return _same_process(int(rec.get("pid") or 0), rec.get("pidStarted"))
    return True


def get(short_id: str) -> Optional[dict[str, Any]]:
    """The record of this project's server, or None. It may be failed or its owner gone: `alive` says."""
    return _read(_path(short_id))


def live(short_id: str) -> Optional[dict[str, Any]]:
    rec = get(short_id)
    return rec if rec and alive(rec) else None


def touch(short_id: str) -> None:
    """Someone used the server just now (the file's modified time is "last used")."""
    with contextlib.suppress(OSError):
        os.utime(_path(short_id))


def mine(short_id: str, token: str) -> bool:
    rec = get(short_id)
    return bool(rec and rec.get("token") == token)


def update(short_id: str, token: Optional[str] = None, **fields: Any) -> bool:
    """Write progress into the record. With `token` only if the record is still the one that claimed it. False when there is none."""
    try:
        with _locked():
            rec = get(short_id)
            if rec is None or (token is not None and rec.get("token") != token):
                return False
            rec.update(fields)
            _write(_path(short_id), rec)
            return True
    except (TimeoutError, OSError):
        logger.warning("[phone_live_registry] could not update %s", short_id, exc_info=True)
        return False


def release(short_id: str, token: Optional[str] = None) -> None:
    """Take the record away. With `token` only if it is still the one that claimed it."""
    with contextlib.suppress(TimeoutError, OSError):
        with _locked():
            rec = get(short_id)
            if rec is not None and (token is None or rec.get("token") == token):
                with contextlib.suppress(OSError):
                    _path(short_id).unlink()


def end(rec: dict[str, Any], why: str) -> None:
    """Stop its process and take its record away, from whichever worker is asking."""
    logger.info("[phone_live_registry] ending %s on port %s (%s)", rec.get("id"), rec.get("port"), why)
    if _same_process(int(rec.get("pid") or 0), rec.get("pidStarted")):
        kill_pid(int(rec["pid"]))
    release(str(rec.get("id") or ""), rec.get("token"))


def claim(short_id: str, output_dir: str | Path, *, org: str = "", per_org_cap: int = 2, global_cap: int = 4) -> tuple[dict[str, Any], bool]:
    """The one way to begin. Returns `(record, created)`.

    Under the lock: a server that is live or starting is used, not started again (so a second start, from any worker, never reaches
    the working folder a running Metro stands on). Otherwise what is left of an old one is cleared; while the organisation holds
    `per_org_cap` or more, ITS least recently used server is ended; and if the platform then holds `global_cap` or more, the start is
    refused with `CapReached` (another organisation's server is never ended to make room). A new record, owned by this process, is
    written in the `starting` state."""
    org = str(org or "")
    with _locked():
        existing = get(short_id)
        if existing is not None and alive(existing):
            touch(short_id)
            return existing, False
        if existing is not None:
            leftover = dict(existing)
            if _same_process(int(leftover.get("pid") or 0), leftover.get("pidStarted")):
                kill_pid(int(leftover["pid"]))
            with contextlib.suppress(OSError):
                _path(short_id).unlink()
        running = sorted((r for r in records() if r.get("id") != short_id and alive(r)), key=lambda r: r["used"])
        own = [r for r in running if str(r.get("org") or "") == org]
        for rec in own[:max(0, len(own) - max(0, per_org_cap - 1))]:
            end_unlocked(rec, f"the organisation already has {per_org_cap} live previews")
            running.remove(rec)
        if len(running) >= max(1, global_cap):
            raise CapReached(f"{len(running)} live previews are already running")
        rec = {"id": short_id, "outputDir": str(output_dir), "org": org, "state": "starting", "error": "", "port": 0, "pid": 0,
               "pidStarted": None, "stage": "", "owner": os.getpid(), "ownerStarted": _started(os.getpid()),
               "token": uuid.uuid4().hex, "startedAt": time.time()}
        DIR.mkdir(parents=True, exist_ok=True)
        _write(_path(short_id), rec)
        return rec, True


def end_unlocked(rec: dict[str, Any], why: str) -> None:
    """`end`, for a caller that already holds the lock."""
    logger.info("[phone_live_registry] ending %s on port %s (%s)", rec.get("id"), rec.get("port"), why)
    if _same_process(int(rec.get("pid") or 0), rec.get("pidStarted")):
        kill_pid(int(rec["pid"]))
    with contextlib.suppress(OSError):
        _path(str(rec.get("id") or "")).unlink()


def reap(idle_s: float, now: Optional[float] = None) -> list[str]:
    """One pass, from any worker: end what is failed, idle, or left behind by a worker that is gone. Returns a line per server."""
    now = time.time() if now is None else now
    out: list[str] = []
    for rec in records():
        why = ""
        if rec.get("state") == "failed":
            why = "it failed"
        elif not _same_process(int(rec.get("owner") or 0), rec.get("ownerStarted")):
            why = "the worker that started it is gone"
        elif rec.get("state") == "ready" and now - rec["used"] > idle_s:
            why = f"not used for {int((now - rec['used']) // 60)} minutes"
        elif rec.get("state") == "ready" and not _same_process(int(rec.get("pid") or 0), rec.get("pidStarted")):
            why = "its process stopped"
        if why:
            end(rec, why)
            out.append(f"{rec.get('id')}: {why}")
    return out

"""Which of two pending questions was asked LAST.

A confirmation ("Shall I go ahead?") and a proposed plan are two files; a plain
"Go ahead" answers the later one. File mtimes cannot order them (equal on a fast
write, a second apart on a coarse filesystem), so each carries a sequence number
from one counter per project: strictly increasing, never repeated, written when
the question is created. Files without one (older projects) fall back to mtime.
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path

_COUNTER = Path(".forge") / "seq.json"


_LOCK = threading.Lock()
_LOCK_FILE = Path(".forge") / "seq.lock"


@contextlib.contextmanager
def _locked(output_dir: str | Path):
    """One writer at a time: a lock for threads in this process, and an exclusive lock file
    (O_CREAT|O_EXCL - atomic on Windows and POSIX) for other processes. A lock file older than
    a few seconds belongs to a dead process and is taken over."""
    with _LOCK:
        path = Path(output_dir) / _LOCK_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = None
        deadline = time.monotonic() + 3.0
        while fd is None:
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - path.stat().st_mtime > 5:
                        path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    break                      # give up waiting: the in-process lock still orders this process
                time.sleep(0.005)
            except OSError:
                break
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def _highest(output_dir: str | Path) -> int:
    """The highest sequence already on disk: the counter AND the two pending-question files, so a lost
    counter (or a file restored with a number from the future) can never be outranked by a new question."""
    from services.smith import confirm, plan
    top = 0
    for rel in (_COUNTER, confirm.PENDING_PATH, plan.PENDING_PATH):
        v = seq_of(Path(output_dir) / rel)
        if v is not None:
            top = max(top, v)
    return top


def next_seq(output_dir: str | Path) -> int:
    """The next number: strictly above everything already written (the counter, the pending
    files) and above the clock; safe under threads and processes."""
    with _locked(output_dir):
        seq = max(_highest(output_dir) + 1, time.time_ns())
        path = Path(output_dir) / _COUNTER
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"seq": seq}), "utf-8")
            os.replace(tmp, path)
        except Exception:  # noqa: BLE001 - the number is still unique for this call
            pass
        return seq


def seq_of(path: Path) -> int | None:
    """The sequence stored in a pending-question file, or None (older file / unreadable)."""
    try:
        raw = json.loads(path.read_text("utf-8"))
        v = raw.get("seq") if isinstance(raw, dict) else None
        return int(v) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def asked_after(output_dir: str | Path, a: str | Path, b: str | Path) -> bool:
    """Was file ``a`` created AFTER file ``b``? By sequence when both have one, else by mtime."""
    pa, pb = Path(output_dir) / a, Path(output_dir) / b
    sa, sb = seq_of(pa), seq_of(pb)
    if sa is not None and sb is not None:
        return sa > sb
    try:
        return pa.stat().st_mtime_ns > pb.stat().st_mtime_ns
    except OSError:
        return False

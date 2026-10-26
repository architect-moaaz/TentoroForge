"""Start a child process in a group of its own, and stop the whole group: the same on Windows as everywhere else.

A dev server (`next dev`) starts children of its own, so stopping it means stopping the group. POSIX does that with
`setsid` at start and `killpg` at the end; Windows has neither (`os.setsid` is an AttributeError, which made the Preview
button fail with "module 'os' has no attribute 'setsid'"). There a new process group is requested at start and
`taskkill /T` takes the tree."""
from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


def own_group() -> dict[str, Any]:
    """Keyword arguments for `Popen` / `asyncio.create_subprocess_exec` that put the child in a group of its own."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"preexec_fn": os.setsid}


def stop_group(proc: Any, *, force: bool = False) -> None:
    """Stop `proc` and everything it started. Never raises: a process that is already gone is stopped."""
    pid = getattr(proc, "pid", None)
    if not pid:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass

"""End a process and everything it started — on POSIX and on Windows.

`npm run dev` is not the server: it starts `next dev`, which starts `next-server`, and all of
them inherit the pipe the parent reads. Ending npm alone leaves the grandchildren running and
HOLDING THE PIPE OPEN, so a read that waits for EOF waits for ever (see
`assembly._boots`). The tree has to go, not the root.

POSIX does that with a process group: the child is started in its own session and the group is
signalled. Windows has neither `os.killpg` / `os.getpgid` nor `signal.SIGKILL`, so a build that
reached the boot check there died on `AttributeError: module 'signal' has no attribute 'SIGKILL'`
after the whole application had been written. `taskkill /T /F` is the Windows tree-kill.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys


def kill_process_tree(proc: "subprocess.Popen", *, grace: float = 10.0) -> None:
    """Terminate `proc` and its descendants; wait up to `grace` seconds for it to be gone.

    Never raises for a process that is already gone. The caller still reads whatever the pipe
    holds afterwards; this only guarantees nothing is left writing to it.
    """
    if proc.poll() is not None:
        return

    if sys.platform == "win32":
        # No process group to signal: /T walks the tree from this pid, /F forces it.
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()  # at least the root
            except OSError:
                pass
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        return

    # Politely first, then for certain — the group, not the pid.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue

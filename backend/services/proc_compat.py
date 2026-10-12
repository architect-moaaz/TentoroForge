"""Child processes that behave the same on Windows as on POSIX.

Three things differ and each one failed a build on a Windows host:

* ``npm`` / ``npx`` are ``.cmd`` shims there. ``subprocess`` does no PATHEXT lookup
  without ``shell=True``, so a bare ``"npx"`` raised ``FileNotFoundError: [WinError 2]``
  — :func:`tool` resolves the real file.
* ``start_new_session`` does not exist; the equivalent is a new process group —
  :func:`group_kwargs`.
* ``os.killpg`` / ``os.getpgid`` / ``signal.SIGKILL`` do not exist, and ending the
  ``npm`` shim leaves its ``node`` children holding the output pipe open —
  :func:`kill_group` ends the whole tree (``taskkill /T``).
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
from typing import Any

IS_WINDOWS = os.name == "nt"


def tool(name: str) -> str:
    """The executable to run for ``name``.

    On Windows ``npm`` and ``npx`` are ``.cmd`` shims that ``subprocess`` does not find by their bare
    name, so they are resolved to the real file. Everywhere else the name is returned as it was, so
    the process is found by the system's own PATH lookup exactly as it always was."""
    return (shutil.which(name) or name) if IS_WINDOWS else name


def resolve(argv: list[str]) -> list[str]:
    """``argv`` with its program resolved."""
    return [tool(argv[0]), *argv[1:]] if argv else argv


def link_dir(link: "os.PathLike[str] | str", target: "os.PathLike[str] | str") -> None:
    """Make ``link`` a directory that is ``target``: a symbolic link, or on Windows a junction.

    Creating a symlink on Windows needs administrator rights or Developer Mode (``WinError 1314``), which
    a person running the platform on their own machine usually does not have. A directory junction does
    the same job for this (reading a shared ``node_modules``) and needs no privilege. Everywhere else it
    is the symlink it always was."""
    try:
        os.symlink(os.fspath(target), os.fspath(link), target_is_directory=True)
    except OSError:
        if not IS_WINDOWS:
            raise
        import _winapi  # CPython on Windows only

        _winapi.CreateJunction(os.fspath(target), os.fspath(link))


def group_kwargs() -> dict[str, Any]:
    """``Popen`` keywords that make the child the leader of its own group, so the
    whole tree it starts can be ended together."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_group(proc: subprocess.Popen, *, force: bool = False) -> None:
    """End ``proc`` and everything it started. Never raises: a process that is
    already gone is the goal."""
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=20, stdin=subprocess.DEVNULL)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError):
        try:
            proc.kill() if force or IS_WINDOWS else proc.terminate()
        except OSError:
            pass

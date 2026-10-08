"""The OS-specific process helpers choose by platform, and the path rule needs no platform at all.

`proc_compat` is the one place that knows Windows differs: `.cmd` shims, no `start_new_session`,
no `killpg`. Both branches are exercised here by simulation, so a Mac or Linux run is covered
from a Windows machine and the reverse."""
import subprocess
from pathlib import PurePosixPath, PureWindowsPath

import pytest

from services import proc_compat


def test_windows_gets_a_process_group_and_posix_a_new_session(monkeypatch):
    monkeypatch.setattr(proc_compat, "IS_WINDOWS", True)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    assert proc_compat.group_kwargs() == {"creationflags": 512}
    monkeypatch.setattr(proc_compat, "IS_WINDOWS", False)
    assert proc_compat.group_kwargs() == {"start_new_session": True}


def test_posix_ends_a_tree_with_killpg_and_windows_with_taskkill(monkeypatch):
    class Proc:
        pid = 4242
        killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def terminate(self):
            self.killed = True

    calls = []
    monkeypatch.setattr(proc_compat.subprocess, "run", lambda argv, **kw: calls.append(("run", argv)))

    monkeypatch.setattr(proc_compat, "IS_WINDOWS", True)
    proc_compat.kill_group(Proc())
    assert calls[-1][1][:2] == ["taskkill", "/PID"] and "/T" in calls[-1][1]

    monkeypatch.setattr(proc_compat, "IS_WINDOWS", False)
    monkeypatch.setattr(proc_compat.os, "killpg", lambda pgid, sig: calls.append(("killpg", sig)), raising=False)
    monkeypatch.setattr(proc_compat.os, "getpgid", lambda pid: pid, raising=False)
    proc_compat.kill_group(Proc())
    assert calls[-1][0] == "killpg"


def test_killing_a_finished_process_is_a_no_op():
    class Done:
        pid = 1

        def poll(self):
            return 0

    proc_compat.kill_group(Done())  # must not raise or signal anything


def test_a_program_name_resolves_without_changing_its_arguments():
    argv = proc_compat.resolve(["npm", "run", "build"])
    assert argv[1:] == ["run", "build"]
    assert proc_compat.resolve([]) == []


@pytest.mark.parametrize("path_type", [PurePosixPath, PureWindowsPath])
def test_the_forward_slash_key_is_the_same_on_every_platform(path_type):
    """`as_posix()` is what the path comparisons use: identical on POSIX, and the fix on Windows."""
    rel = path_type("src") / "lib" / "workflows" / "definitions" / "add-book.json"
    assert rel.as_posix() == "src/lib/workflows/definitions/add-book.json"

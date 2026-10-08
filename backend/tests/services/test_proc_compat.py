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


def test_the_dev_server_registry_records_nothing_where_there_are_no_process_groups(tmp_path, monkeypatch):
    """The registry is about POSIX process groups. On Windows `os.getpgid` does not exist: it must
    not raise (that made the build's own app check report every page as not working), and it must
    write no record the reaper could one day act on."""
    import os

    from services import dev_servers

    monkeypatch.setattr(dev_servers, "DIR", tmp_path / "servers")
    monkeypatch.delattr(os, "getpgid", raising=False)
    dev_servers.track(4321, port=3999, root=tmp_path, kind="boot-check")
    assert not (tmp_path / "servers").exists() or not list((tmp_path / "servers").glob("*.json"))


def test_screenshot_output_with_non_ascii_text_is_read_as_utf8(tmp_path, monkeypatch):
    """node writes UTF-8. Decoded with the Windows ANSI code page a non-ASCII byte killed the reader
    thread and `proc.stderr` came back None, so the page check crashed ('NoneType' is not subscriptable)."""
    import subprocess as sp
    from services.blueprint import page_review

    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return sp.CompletedProcess(argv, 1, stdout=None, stderr=None)   # what the broken decode produced

    monkeypatch.setattr(page_review.subprocess, "run", fake_run)
    monkeypatch.setattr(page_review, "_playwright_modules", lambda: tmp_path)
    monkeypatch.setattr(page_review, "_link_node_modules", lambda modules, link: link.mkdir())
    app = type("A", (), {"base": "http://127.0.0.1:1"})()
    with pytest.raises(page_review.ReviewUnavailable):
        page_review.run_shots(app, [], tmp_path / "out")
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"

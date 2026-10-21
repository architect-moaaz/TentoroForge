"""A dev server is started in a group of its own and stopped as a group, on Windows as elsewhere.

`preexec_fn=os.setsid` and `os.killpg` do not exist on Windows: the Preview button failed with
"module 'os' has no attribute 'setsid'" (found on the first Habit Pal preview, 2026-10-21)."""
from __future__ import annotations

import subprocess
import sys
import time

from services import process_groups


def test_a_child_started_in_its_own_group_is_stopped_with_its_group():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **process_groups.own_group())
    try:
        assert child.poll() is None, "it is running"
        process_groups.stop_group(child)
        for _ in range(50):
            if child.poll() is not None:
                break
            time.sleep(0.1)
        assert child.poll() is not None, "stopping the group stopped the child"
    finally:
        if child.poll() is None:
            child.kill()


def test_stopping_something_already_gone_does_not_raise():
    child = subprocess.Popen([sys.executable, "-c", "pass"], **process_groups.own_group())
    child.wait(timeout=30)
    process_groups.stop_group(child)
    process_groups.stop_group(None)


def test_the_preview_launchers_no_longer_name_a_unix_only_call():
    import pathlib
    for name in ("preview.py", "services/preview_manager.py"):
        text = (pathlib.Path(__file__).resolve().parents[2] / name).read_text(encoding="utf-8")
        assert "os.setsid" not in text and "os.killpg" not in text, name

"""`["npm", ...]` starts on Windows.

The build's install step runs npm as a plain argument list; on Windows the file is `npm.cmd`, so the first build step
died with WinError 2 and no page was ever written. The backend resolves the tool names when it starts."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from services import windows_commands


def test_it_does_nothing_off_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(windows_commands, "_installed", False)
    assert windows_commands.resolve_tools_on_windows() is False


@pytest.mark.skipif(os.name != "nt" or not shutil.which("npm"), reason="needs Windows with npm installed")
def test_npm_is_found_by_its_short_name():
    windows_commands.resolve_tools_on_windows()
    done = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip()

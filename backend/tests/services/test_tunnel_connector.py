"""The Watch live connector (templates/tunnel/ttf-watch-connect.mjs) has its own tests in Node; this runs them with the rest."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

TEST = Path(__file__).resolve().parents[2] / "templates" / "tunnel" / "ttf-watch-connect.test.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_connectors_own_tests_pass():
    r = subprocess.run(["node", "--test", str(TEST)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]

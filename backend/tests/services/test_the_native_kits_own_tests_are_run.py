"""The native kit's own tests, and the read route's, run here.

`templates/native/__tests__` (a fake server in the process, no network) and the web side's read-route test were run by
nobody: a suite that is not run is not a test. Each file is run with plain `node --experimental-strip-types`; they need a
node that has `module.registerHooks` (v22.15 or later), and are skipped without one. `NODE22` may name one."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
NATIVE = sorted((TEMPLATES / "native" / "__tests__").glob("*.test.mts"))
READ = sorted((TEMPLATES / "runtime" / "__tests__").glob("the-reads-a-page-makes-are-answered-over-http.test.mts"))
FILES = NATIVE + READ


def _capable_node() -> str | None:
    """The first node that can load the suites' module hooks, or None."""
    for candidate in (os.environ.get("NODE22", "").strip(), shutil.which("node") or ""):
        if not candidate:
            continue
        try:
            done = subprocess.run([candidate, "-e", 'process.exit(typeof require("node:module").registerHooks === "function" ? 0 : 1)'],
                                  capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return candidate
    return None


NODE = _capable_node()


def test_there_are_native_tests_to_run():
    assert len(NATIVE) >= 7, "the native kit's tests are where the suite looks for them"
    assert READ, "the read route's own test is where the suite looks for it"


@pytest.mark.skipif(NODE is None, reason="needs a node with module.registerHooks (v22.15+); set NODE22")
@pytest.mark.parametrize("path", FILES, ids=[f.name for f in FILES])
def test_the_suite_passes(path):
    done = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", str(path)],
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, (done.stdout[-1800:] + done.stderr[-1800:])

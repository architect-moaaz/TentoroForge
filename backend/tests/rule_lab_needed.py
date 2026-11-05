"""The mark for a test that runs the rule lab (the app's own rules engine,
bundled with esbuild and run by node). Without them the test is skipped and
says which tool is missing, rather than failing on the lab's
`LabUnavailable` as if the code were wrong (PR #29: a checkout without
esbuild failed 16 rule tests)."""
from __future__ import annotations

import shutil

import pytest

from services.blueprint import rule_lab


def _missing() -> str:
    if not shutil.which("node"):
        return "node"
    return "" if rule_lab.available() else "esbuild (npm install at the repository root, or esbuild on the PATH)"


needs_lab = pytest.mark.skipif(bool(_missing()), reason=f"the rule lab needs {_missing() or 'nothing more'}")

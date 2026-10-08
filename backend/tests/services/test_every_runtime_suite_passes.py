"""Every suite under templates/runtime/__tests__ runs here.

Five of them — the seed's own tests among them — had failed since
2026-09-19, when seed.ts began reading the account model, and nothing
noticed: no pytest ran them. A runtime suite that is not run is not a test.
"""
import subprocess
from pathlib import Path

import pytest

SUITES = sorted((Path(__file__).resolve().parents[2] / "templates/runtime/__tests__").glob("run-*.sh"))


@pytest.mark.parametrize("suite", SUITES, ids=[s.name for s in SUITES])
def test_the_runtime_suite_passes(suite):
    out = subprocess.run(["bash", str(suite)], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]

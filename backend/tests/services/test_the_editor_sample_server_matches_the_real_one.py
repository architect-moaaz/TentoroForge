"""The editor's sample server offers everything the real one does.

To render a page without a database, the editor swaps `@/sdk/server` for a
sample shim (`static/jit-samples.mjs` → `.forge-jit/shims/sample-server.ts`).
The shim is written by hand, so it falls behind: `similar()` arrived with image
search and the shim was never told, and every page that ranks by picture failed
to render in the editor —

    Build failed with 1 error: src/app/(dashboard)/scan/confirm/[scanId]/load.ts:
    No matching export in ".../sample-server.ts" for import "similar"

(HippieKit, zo9k0ekd). A function added to the real SDK now fails this test
until the shim has it too.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REAL = BACKEND / "templates/app-foundation/src/sdk/server.ts"


def _exports(ts: str) -> set[str]:
    # Not anchored to the line start: the shim declares several at once
    # (`export type ListOptions<E> = any; export type Measure<E> = any;`).
    names = set(re.findall(r"(?:^|;)\s*export\s+(?:async\s+)?(?:function|const|let|class|interface|type)\s+(\w+)",
                           ts, re.M))
    for block in re.findall(r"^export\s*{([^}]*)}", ts, re.M):
        names |= {n.strip().removeprefix("type ").split(" as ")[-1].strip()
                  for n in block.split(",") if n.strip()}
    return names


def _shim() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "--input-type=module", "-e",
         "import { sampleServer } from './jit-samples.mjs';"
         "process.stdout.write(sampleServer([{ name: 'Thing', fields: [{ name: 'name', type: 'string' }] }], []));"],
        cwd=BACKEND / "static", capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-800:]
    return out.stdout


def test_the_shim_exports_everything_a_page_can_import():
    missing = sorted(_exports(REAL.read_text("utf-8")) - _exports(_shim()))
    assert not missing, f"@/sdk/server exports these and the editor's sample server does not: {missing}"


def test_similar_behaves_like_the_real_one():
    """Nothing to compare against is no rows; otherwise closest first."""
    shim = _shim()
    assert "if (!opts?.image && !String(opts?.text ?? \"\").trim()) return { rows: [], error: null };" in shim
    assert "similarity" in shim

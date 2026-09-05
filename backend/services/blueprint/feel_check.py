"""Workflow and rule conditions are checked by the engine's own parser.

A workflow authored `{{input.caseType}} == 'REFUND' && …` as a condition.
The engine's dialect is FEEL — `=`, `and`, `or`, `not` — and its tokenizer
refused `==` at run time, so the "Create Case" form dispatched, the engine
answered 200, and no case was written. Nothing had read the expression
before a person pressed the button.

This runs the runtime's FEEL tokenizer and parser (bundled from
`templates/runtime/feel-lite` with esbuild, on demand) over a batch of
expressions, so what is refused here is exactly what the engine would
refuse. No node, no esbuild: the check reports nothing rather than
inventing a verdict.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_ENTRY = _BACKEND / "scripts" / "feel" / "entry.ts"
_BUNDLE = _BACKEND / "scripts" / "feel" / "validate.cjs"
_FEEL_SRC = _BACKEND / "templates" / "runtime" / "feel-lite"


def _ensure_bundle() -> Path | None:
    if _BUNDLE.exists() and _BUNDLE.stat().st_mtime >= max(
            (p.stat().st_mtime for p in _FEEL_SRC.glob("*.ts")), default=0):
        return _BUNDLE
    esbuild = _BACKEND.parent / "node_modules" / ".bin" / "esbuild"
    cmd = [str(esbuild)] if esbuild.exists() else ["npx", "esbuild"]
    try:
        subprocess.run(cmd + [str(_ENTRY), "--bundle", "--platform=node", "--format=cjs",
                              f"--outfile={_BUNDLE}", "--log-level=error"],
                       check=True, capture_output=True, timeout=120)
        return _BUNDLE
    except Exception as exc:  # noqa: BLE001
        logger.warning("[feel-check] could not build the validator: %s", exc)
        return None


def check_expressions(items: list[tuple[str, str]]) -> dict[str, str]:
    """`{id: error}` for every expression the engine's parser refuses."""
    if not items or not shutil.which("node"):
        return {}
    bundle = _ensure_bundle()
    if bundle is None:
        return {}
    payload = json.dumps([{"id": i, "expression": e} for i, e in items])
    try:
        proc = subprocess.run(["node", str(bundle)], input=payload, capture_output=True,
                              text=True, timeout=60, check=True)
        return {r["id"]: str(r.get("error") or "invalid") for r in json.loads(proc.stdout or "[]")
                if not r.get("ok")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[feel-check] validator failed: %s", exc)
        return {}

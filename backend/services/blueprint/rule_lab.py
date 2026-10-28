"""The rule lab: what the generated app's own rules engine says.

Checks a decision table at save (the cells it cannot read, the rows that
overlap under Unique, the rows a First table never reaches) and answers the
editor's "Test it" — run a save of a sample record through the app's real
engine with the rules as drafted. Bundled from `templates/runtime` with
the installed esbuild on demand, so the platform never carries a second
evaluator that could disagree with the app.

No node, no esbuild: the lab says it is unavailable (`LabUnavailable`) rather
than inventing a verdict.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BACKEND = Path(__file__).resolve().parents[2]
_ENTRY = _BACKEND / "scripts" / "rules" / "lab.ts"
_BUNDLE = _BACKEND / "scripts" / "rules" / "lab.cjs"
_SOURCES = [_BACKEND / "templates" / "runtime" / "rules", _BACKEND / "templates" / "runtime" / "feel-lite"]
_BUILD_LOCK = threading.Lock()


class LabUnavailable(RuntimeError):
    """Node or esbuild is missing, or the lab could not run."""


def _newest_source() -> float:
    stamps = [_ENTRY.stat().st_mtime]
    for d in _SOURCES:
        stamps += [p.stat().st_mtime for p in d.glob("*.ts")]
    return max(stamps)


def _bundle() -> Path:
    with _BUILD_LOCK:
        if _BUNDLE.exists() and _BUNDLE.stat().st_mtime >= _newest_source():
            return _BUNDLE
        # The installed esbuild only: never `npx`, which may download a
        # package on a host (PR #29 review). None: the lab is unavailable, and
        # every caller already treats that as "not judged".
        esbuild = next((p for p in (_BACKEND.parent / "node_modules" / ".bin" / "esbuild",
                                    _BACKEND.parent / "frontend" / "node_modules" / ".bin" / "esbuild")
                        if p.exists()), None)
        if esbuild is None:
            raise LabUnavailable("esbuild is not installed (run npm install at the repository root)")
        cmd = [str(esbuild)]
        tmp = _BUNDLE.with_suffix(".tmp.cjs")
        try:
            subprocess.run(cmd + [str(_ENTRY), "--bundle", "--platform=node", "--format=cjs",
                                  f"--outfile={tmp}", "--log-level=error"],
                           check=True, capture_output=True, timeout=120)
            tmp.replace(_BUNDLE)
        except Exception as exc:  # noqa: BLE001
            raise LabUnavailable(f"the rule lab could not be built: {exc}") from exc
        return _BUNDLE


def run(request: dict[str, Any], timeout: float = 20) -> dict[str, Any]:
    """Send one request to the lab; its answer, or LabUnavailable."""
    if not shutil.which("node"):
        raise LabUnavailable("node is not installed")
    bundle = _bundle()
    try:
        proc = subprocess.run(["node", str(bundle)], input=json.dumps(request), capture_output=True,
                              text=True, timeout=timeout, check=True)
        out = json.loads(proc.stdout or "{}")
    except subprocess.TimeoutExpired as exc:
        raise LabUnavailable("the rule lab took too long") from exc
    except Exception as exc:  # noqa: BLE001
        raise LabUnavailable(f"the rule lab failed: {exc}") from exc
    if out.get("error"):
        raise LabUnavailable(str(out["error"]))
    return out


def analyze_table(table: dict) -> list[dict]:
    """The table's findings: ``[{severity, kind, row?, column?, message}]``.
    Empty when the lab is unavailable — the save is not blocked on tooling."""
    try:
        return list(run({"op": "analyze", "table": table}).get("findings") or [])
    except LabUnavailable as exc:
        logger.warning("[rule-lab] table not analysed: %s", exc)
        return []


def simulate(*, model: str, rules: list[dict], record: dict, event: str = "create",
             previous: dict | None = None, user: dict | None = None, focus: str | None = None) -> dict:
    return run({"op": "simulate", "model": model, "rules": rules, "record": record, "event": event,
                "previous": previous, "user": user, "focus": focus})


__all__ = ["LabUnavailable", "analyze_table", "run", "simulate"]

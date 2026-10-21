"""Every fix leaves a guard: the try that failed and then passed, kept so the
application's own checks hold it from then on.

Claude Code's fix of the Publish dialog left a test that fails on the old
code and passes on the new; Smith's fixes left nothing behind (2026-10-17).
A generated app has no test files, but it has the try Smith used to prove
the fix — a screen opened as a role, a process run with an input, a request
— and that try can be run again by `run_checks guards` and by the checks
after a hand-over. Stored per app in `.forge/smith/guards.jsonl`, one per
try identity (a later fix of the same try replaces the earlier guard).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PATH = Path(".forge") / "smith" / "guards.jsonl"
KEEP = 200


def _path(output_dir: str | Path) -> Path:
    return Path(output_dir) / PATH


def _identity(tool: str, args: dict) -> str:
    a = args or {}
    return "|".join([tool, str(a.get("workflow") or a.get("path") or a.get("route") or ""),
                     str(a.get("method") or ""), str(a.get("as") or "").lower()])


def load(output_dir: str | Path) -> list[dict]:
    path = _path(output_dir)
    if not path.exists():
        return []
    out = []
    for line in path.read_text("utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("tool"):
            out.append(row)
    return out


def record(output_dir: str | Path, ask: str, observations: list) -> dict | None:
    """Keep this turn's fix as a guard: the try, its failure before and its
    pass after. None when the turn was not a fix. Never raises."""
    try:
        from services.smith.account import fix_evidence
        ev = fix_evidence(observations)
        if ev is None:
            return None
        passed, failed = ev["passed"], ev["failed"]
        args = {k: v for k, v in (passed.args or {}).items() if v not in (None, "")}
        row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "ask": " ".join((ask or "").split())[:200], "tool": passed.tool, "args": args,
               "before": " ".join((failed.said or "").split("\n", 1)[0].split())[:200],
               "after": " ".join((passed.said or "").split("\n", 1)[0].split())[:200]}
        rows = [r for r in load(output_dir) if _identity(r.get("tool", ""), r.get("args") or {})
                != _identity(row["tool"], row["args"])]
        rows.append(row)
        path = _path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows[-KEEP:]) + "\n", "utf-8")
        return row
    except Exception:  # noqa: BLE001
        logger.warning("[guards] could not record the fix", exc_info=True)
        return None


def run(bench: Any, doc: dict, *, only_routes: list[str] | None = None) -> dict:
    """Run every guard again on the bench: `{total, green, red, lines}`; a red
    line starts with ✗ so `trials.failed` reads it."""
    from services.smith import trials
    rows = load(bench.output_dir)
    if only_routes:
        wanted = {str(r).strip().lower() for r in only_routes}
        rows = [r for r in rows if str((r.get("args") or {}).get("route") or (r.get("args") or {}).get("path") or "").lower() in wanted]
    green: list[str] = []
    red: list[str] = []
    for r in rows:
        said = trials.run(str(r["tool"]), dict(r.get("args") or {}), bench=bench, doc=doc)
        label = f"{r['tool']} {json.dumps(r.get('args') or {}, default=str)[:120]} (fixed for: {r.get('ask') or '?'})"
        if trials.failed(said):
            red.append(f"  {trials.CHECK_RED} {label}: {' '.join(said.split(chr(10), 1)[0].split())[:160]} — it was "
                       f"“{r.get('after')}” when fixed")
        else:
            green.append(label)
    head = (f"checks · guards: {len(green)} of {len(rows)} earlier fixes still hold"
            + (f", {len(red)} do not" if red else "")) if rows else "checks · guards: no earlier fix to hold"
    return {"total": len(rows), "green": green, "red": red, "lines": [head, *red]}


__all__ = ["record", "load", "run", "PATH"]

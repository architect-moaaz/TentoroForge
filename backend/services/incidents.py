"""What went wrong on the platform, as a record the cockpit shows.

A turn the host killed, a build a restart stopped, a fault the fix loop
found to be the platform's and not the app's: each was visible within
seconds in a ledger, a kernel log or a scorecard, and nobody read any of
them for eleven hours (pcn4owv7, 2026-10-15). One file, one line per
incident, newest shown first in the cockpit's Overview.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

FILE = "incidents.jsonl"
KEEP = 2000


def _path() -> Path:
    from services.project_paths import OUTPUT_ROOT
    return Path(OUTPUT_ROOT) / "_platform" / FILE


def record(kind: str, app: str, detail: str, **extra: Any) -> dict[str, Any]:
    """One incident on the record. Never raises: the record is a bonus to
    the work that noticed, not a condition of it."""
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": str(kind), "app": str(app or ""),
           "detail": str(detail or "")[:600], **{k: v for k, v in extra.items() if v not in (None, "")}}
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return row


def recent(limit: int = 100) -> list[dict[str, Any]]:
    """The newest incidents first."""
    try:
        lines = _path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines[-KEEP:]):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
        if len(out) >= limit:
            break
    return out

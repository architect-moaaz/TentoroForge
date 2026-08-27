"""Substrate gap log — append-only JSONL of every ``extension_needed``
verdict.

Team reviews the log weekly. Any gap that appears in ≥3 briefs across
≥2 weeks graduates to a first-class primitive via a JSON edit to the
relevant vocabulary file. Never speculative — substrate grows on
evidence. See spec P1 "Coverage verdicts" and plan IRF-M2-T2.

The writer is deliberately dumb: line-oriented JSONL, one entry per
call, timestamp stamped here (not passed by callers — every entry
uses ``datetime.now()`` at write time so entries are trustworthy).

Path is ``backend/telemetry/substrate_gap_log.jsonl`` by default; the
env var ``FORGE_SUBSTRATE_GAP_LOG`` overrides for tests.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "telemetry" / "substrate_gap_log.jsonl"


def _resolve_path() -> Path:
    override = os.environ.get("FORGE_SUBSTRATE_GAP_LOG")
    if override:
        return Path(override)
    return _DEFAULT_PATH


def append(entry: dict[str, Any]) -> None:
    """Append one entry. Timestamp is stamped here (never trusted from
    the caller). Parent dir is created on demand. Writes with newline
    separator — one JSON object per line, standard JSONL.

    Never raises on filesystem hiccups — this is telemetry, must not
    block generation. Callers that need write confirmation should
    check with :func:`read_all` afterward.
    """
    stamped = dict(entry)
    stamped["ts"] = datetime.now(timezone.utc).isoformat()
    path = _resolve_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(stamped, sort_keys=True, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        # Never block generation on telemetry failure.
        return


def read_all() -> list[dict[str, Any]]:
    """Return all logged entries in order. Empty list when the file
    doesn't exist yet."""
    path = _resolve_path()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines rather than crash the reader —
                # this happens if a process was killed mid-write.
                continue
    return entries


def iter_entries() -> Iterator[dict[str, Any]]:
    """Yield entries lazily — for large logs the review page uses this
    instead of read_all()."""
    path = _resolve_path()
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def clear() -> None:
    """Test-only. Truncate the log file. Never call in production
    code — the log is append-only by contract, review-driven, human-
    owned."""
    path = _resolve_path()
    if path.exists():
        path.write_text("", encoding="utf-8")

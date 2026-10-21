"""What earlier turns on this application learned, kept for the next one.

Every turn started from the Blueprint slice and the catalogue with no memory of
the last: a file read on Tuesday was read again on Wednesday, a try that
failed was repeated, a fault already found was found again. The person's own
comparison (2026-10-17): the thing that made Claude fast was a notebook —
knowing where everything was from the time before.

One line per turn, appended when the turn ends: what was asked, what was read
(by name), what was tried and what it showed, what was changed, what was left
not right. The newest few are put on top of the next turn's page. Bounded in
entries and in characters; never a transcript.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PATH = Path(".forge") / "smith" / "notebook.jsonl"
#: How many turns the next one is shown, and how much of them.
SHOWN = 6
MAX_CHARS = 3500
#: How many lines a notebook keeps on disk before the oldest go.
KEEP = 200


def _path(output_dir: str | Path) -> Path:
    return Path(output_dir) / PATH


def _first(text: Any, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def entry_for(ask: str, observations: list, out: Any) -> dict:
    """The one line this turn leaves: deterministic, from the observations."""
    from services.smith import tools
    reads: list[str] = []
    tries: list[str] = []
    changes: list[str] = []
    for o in observations or []:
        tool = str(getattr(o, "tool", "") or "")
        args = getattr(o, "args", None) or {}
        where = str(args.get("path") or args.get("route") or args.get("section") or args.get("workflow")
                    or args.get("entity") or args.get("file") or "")
        if tools.is_trial(tool):
            tries.append(_first(f"{tool} {where}: {(getattr(o, 'said', '') or '').split(chr(10), 1)[0]}", 180))
        elif tools.is_write(tool):
            why = args.get("because") or args.get("why") or args.get("brief") or ""
            changes.append(_first(f"{tool} {where}" + (f" — {why}" if why else ""), 160))
        elif getattr(o, "status", "") == "read" and where:
            if f"{tool} {where}" not in reads:
                reads.append(f"{tool} {where}")
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ask": _first(ask, 240),
        "status": str(getattr(out, "status", "") or ""),
        "said": _first(getattr(out, "said", ""), 300),
        "touched": [str(t) for t in (getattr(out, "touched", None) or [])][:8],
        "reads": reads[:10],
        "tries": tries[:6],
        "changes": changes[:6],
        "finding": _first(getattr(out, "finding", ""), 240),
    }


def record(output_dir: str | Path, ask: str, observations: list, out: Any) -> dict | None:
    """Append this turn's line. Never raises; a notebook is a note, not the turn."""
    try:
        row = entry_for(ask, observations, out)
        if not (row["reads"] or row["tries"] or row["changes"] or row["said"]):
            _drop_partial(output_dir)
            return None
        path = _path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text("utf-8").splitlines() if path.exists() else []
        lines.append(json.dumps(row, ensure_ascii=False))
        path.write_text("\n".join(lines[-KEEP:]) + "\n", "utf-8")
        _drop_partial(output_dir)
        return row
    except Exception:  # noqa: BLE001
        logger.warning("[notebook] could not record the turn", exc_info=True)
        return None


PARTIAL = Path(".forge") / "smith" / "notebook.partial.json"


def checkpoint(output_dir: str | Path, ask: str, observations: list) -> None:
    """What the running turn has read and tried so far, written each step.

    A turn the process loses — the host's out-of-memory killer, a restart
    mid-turn (13 such ledgers on forge-v3 in the two weeks to 2026-10-17) —
    never reaches `record`, and the next turn started from nothing again.
    The checkpoint is replaced by the real line when the turn ends.
    """
    try:
        row = entry_for(ask, observations, None)
        if not (row["reads"] or row["tries"] or row["changes"]):
            return
        row["status"] = "lost"
        path = Path(output_dir) / PARTIAL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, ensure_ascii=False), "utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("[notebook] checkpoint skipped", exc_info=True)


def _drop_partial(output_dir: str | Path) -> None:
    try:
        (Path(output_dir) / PARTIAL).unlink(missing_ok=True)
    except OSError:
        pass


def _partial(output_dir: str | Path) -> dict | None:
    path = Path(output_dir) / PARTIAL
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text("utf-8"))
        return row if isinstance(row, dict) else None
    except (OSError, ValueError):
        return None


def entries(output_dir: str | Path) -> list[dict]:
    path = _path(output_dir)
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text("utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def recall(output_dir: str | Path, *, shown: int = SHOWN, max_chars: int = MAX_CHARS) -> str:
    """The block the next turn's page opens with, or "" when nothing is known."""
    rows = entries(output_dir)[-shown:]
    lost = _partial(output_dir)
    if lost is not None:
        rows = (rows + [lost])[-shown:]
    if not rows:
        return ""
    lines = ["WHAT EARLIER TURNS ON THIS APPLICATION LEARNED (newest first; read before reading "
             "the code again — a file named here was read then, a try named here was made then, and "
             "what is marked left was not right when that turn ended):"]
    for row in reversed(rows):
        when = str(row.get("at") or "")[:16].replace("T", " ")
        bits = [f"- {when} asked: {row.get('ask') or '?'}"]
        if row.get("changes"):
            bits.append("changed: " + "; ".join(row["changes"]))
        if row.get("tries"):
            bits.append("tried: " + "; ".join(row["tries"]))
        if row.get("reads"):
            bits.append("read: " + ", ".join(row["reads"]))
        if row.get("status") == "lost":
            bits.insert(1, "(this turn was lost before it ended — the process working on it went away; "
                           "what it had read and tried is below, and nothing it meant to change landed)")
        if row.get("finding"):
            bits.append("left: " + row["finding"])
        elif row.get("status") in ("asked", "needs_user"):
            bits.append("ended on a question: " + (row.get("said") or ""))
        elif row.get("status") not in ("resolved", "lost", "") and row.get("said"):
            # WHAT IT SAID IT WOULD DO NEXT IS ITS OWN NEXT STEP. TCommerce's
            # turn named "read /cart's code" as what it had not got to, and the
            # carry-on rewrote the product page instead (ihf6pjga, 2026-10-06).
            bits.append("ended saying (do what this names first on a carry-on): " + row["said"])
        lines.append("  ".join(bits))
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars - 1].rstrip() + "…"


__all__ = ["record", "recall", "checkpoint", "entries", "entry_for", "PATH", "PARTIAL"]

"""The ask a turn could not act on, kept until the turn that can.

A change is often two turns. Smith is asked for "a simple arithmetic
calculator that does not store the values", cannot tell where it should live,
and asks; the person answers "a new page at /calculator" — with a chip, now,
so the answer is exactly the label Smith offered. The next turn then acts on
that answer ALONE: it was the whole of `user_message`, and it became the new
page's purpose and the composer's only subject. A workforce dashboard came
back, twice, and the sentence that asked for a calculator was never in the
Blueprint at all.

The conversation is not the fix. The definition folds every user turn into one
brief because a definition is written from everything said; a change turn must
not, or a field added an hour ago would qualify a screen composed now. What
belongs together is narrower: the ask Smith could not act on, and the answer
to the question it asked about that ask.

So the ask is recorded at the moment Smith asks — a fact, not an inference
from the shape of the text — and taken by the next turn, which carries it into
the seam as part of the request. Nothing is left behind: `take` removes it, so
an ask that is answered, abandoned or superseded cannot reach a later turn.

On disk rather than in memory because a session is built per request: the
answer arrives in a new process, often after a reload.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PENDING_PATH = Path(".forge") / "pending-ask.json"

#: Long enough for the sentence that asked and the clarification it drew,
#: several times over; short enough that a runaway loop cannot grow a file.
MAX_CHARS = 4000


def _path(output_dir: str | Path) -> Path:
    return Path(output_dir) / PENDING_PATH


def remember(output_dir: str | Path, ask: str) -> None:
    """Keep `ask` as the ask the next turn is answering. Best effort."""
    text = str(ask or "").strip()[:MAX_CHARS]
    if not text:
        return
    try:
        path = _path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ask": text}, indent=2), "utf-8")
    except Exception as exc:  # noqa: BLE001 — carrying the ask is a courtesy
        logger.warning("[smith] could not record the pending ask: %s", exc)


def take(output_dir: str | Path) -> str:
    """The recorded ask, removed as it is read. "" when there is none.

    Removed rather than read, because an ask that survived its answer would
    qualify every later turn: "the calculator" would still be in the request
    when the next change is about a nurse.
    """
    path = _path(output_dir)
    try:
        raw = json.loads(path.read_text("utf-8"))
        ask = str((raw or {}).get("ask") or "").strip() if isinstance(raw, dict) else ""
    except FileNotFoundError:
        return ""
    except Exception as exc:  # noqa: BLE001 — an unreadable note is no note
        logger.warning("[smith] pending ask unreadable: %s", exc)
        ask = ""
    clear(output_dir)
    return ask


def clear(output_dir: str | Path) -> None:
    try:
        _path(output_dir).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smith] could not clear the pending ask: %s", exc)


def joined(carried: str, message: str) -> str:
    """The turn's whole ask: what was asked for, then the answer to Smith's
    question about it. Blank-safe and never doubled."""
    first = str(carried or "").strip()
    last = str(message or "").strip()
    if not first:
        return last
    if not last or last in first:
        return first
    return f"{first}\n\n{last}"


__all__ = ["remember", "take", "clear", "joined", "PENDING_PATH"]

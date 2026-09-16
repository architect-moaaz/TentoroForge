"""A yes, remembered between the turn that asks for it and the turn that acts.

"Get rid of complaints" retires the entity, the screens built on it, the
workflows that act on it and their buttons on every other screen. The
dependency set is computed before any of it happens — `entity_change.dependents`
— and it was never shown to anyone. The person found out by looking.

WHY A RECORD AND NOT A FLAG IN THE MESSAGE. The turn that says "go ahead" is a
new request in a new process: read on its own it is the same ask again, so the
gate would fire again and the two of them would loop. What is kept is the
FINGERPRINT of the exact operation that was described — verb and target — so a
yes only lets through the thing that was actually shown, and a yes to
something else is not a yes to this.

Taken as it is read, like `pending_ask`: a permission that outlives its
question is a permission nobody gave.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PENDING_PATH = Path(".forge") / "pending-confirm.json"

#: Whole-message agreement. Not "yes, but change the name first" — that is a
#: new request, and treating it as consent would act on the wrong thing.
_YES = frozenset({
    "yes", "y", "go ahead", "go ahead.", "do it", "confirm", "confirmed",
    "proceed", "ok", "okay", "yes please", "yes do it", "sure", "carry on",
    "go on", "that's fine", "thats fine", "remove it", "delete it", "yes, go ahead",
})

#: What the chips say. The first is the yes the gate is looking for.
YES_LABEL = "Go ahead"
NO_LABEL = "No, leave it"


def is_yes(message: str) -> bool:
    m = " ".join((message or "").strip().lower().rstrip(".!").split())
    return m in _YES or m == YES_LABEL.lower()


def fingerprint(verb: str, target: str) -> str:
    """What was shown, so a yes cannot let something else through."""
    return f"{str(verb or '').strip().lower()}:{' '.join(str(target or '').lower().split())}"


def _path(output_dir: str | Path) -> Path:
    return Path(output_dir) / PENDING_PATH


def remember(output_dir: str | Path, fp: str) -> None:
    try:
        path = _path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fingerprint": fp}, indent=2), "utf-8")
    except Exception as exc:  # noqa: BLE001 — a gate that cannot be written asks again
        logger.warning("[smith] could not record the pending confirmation: %s", exc)


def take(output_dir: str | Path) -> str:
    """The fingerprint awaiting a yes, removed as it is read."""
    try:
        raw = json.loads(_path(output_dir).read_text("utf-8"))
        fp = str((raw or {}).get("fingerprint") or "") if isinstance(raw, dict) else ""
    except FileNotFoundError:
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smith] pending confirmation unreadable: %s", exc)
        fp = ""
    clear(output_dir)
    return fp


def clear(output_dir: str | Path) -> None:
    try:
        _path(output_dir).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smith] could not clear the pending confirmation: %s", exc)


def granted(output_dir: str | Path, message: str, verb: str, target: str) -> bool:
    """Whether THIS operation was described last turn and agreed to now."""
    return take(output_dir) == fingerprint(verb, target) and is_yes(message)


__all__ = ["granted", "remember", "take", "clear", "is_yes", "fingerprint",
           "YES_LABEL", "NO_LABEL", "PENDING_PATH"]

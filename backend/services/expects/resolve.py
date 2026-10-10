"""Which controls do what a statement says, in words.

A step says "choose the second option and save it"; the screen has controls.
The first time, a small model reads the screen's controls and picks the ones
that do it, the way a person would. What it picked is kept as a recipe — each
control by its description (role, name, field, where it sits), never by a
selector or a position — and replayed without a model after that. A recipe
whose control is no longer on the screen is resolved again.

The model only finds controls. Whether what happened is right is judged by
code (`runner.judge`), never here.
"""
from __future__ import annotations

import hashlib
import json
import threading
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RESOLVE_MODEL = "claude-haiku-4-5-20251001"
#: Rounds of look-then-act one step gets: a choice can reveal the next control.
ROUNDS = 4
_DESCRIBE = ("role", "name", "field", "type", "placeholder", "within", "href")


def describe(control: dict) -> dict:
    """A control by what a person would know it by."""
    return {k: control[k] for k in _DESCRIBE if control.get(k) not in (None, "")}


def find(desc: dict, controls: list[dict]) -> int | None:
    """The control on a fresh look that a remembered description names: all
    of its description, else its role, name and field, else its role and name
    when only one control has them."""
    def agree(c: dict, keys: tuple[str, ...]) -> bool:
        return all(str(c.get(k) or "") == str(desc.get(k) or "") for k in keys)
    for keys in (tuple(desc), ("role", "name", "field", "within"), ("role", "name", "field"), ("role", "name")):
        hits = [c for c in controls if agree(c, keys) and not c.get("disabled")]
        if len(hits) == 1 or (hits and keys == tuple(desc)):
            return int(hits[0]["idx"])
    return None


def _shown(look: dict) -> str:
    rows = []
    for c in look.get("controls") or []:
        bits = [f"#{c['idx']}", c.get("role", "")]
        if c.get("name"):
            bits.append(repr(c["name"]))
        for k in ("field", "type", "placeholder", "value", "within", "href"):
            if c.get(k) not in (None, ""):
                bits.append(f"{k}={c[k]!r}")
        if c.get("options"):
            bits.append("options=" + json.dumps(c["options"][:20]))
        for k in ("checked", "pressed", "selected", "disabled"):
            if c.get(k) not in (None, False, ""):
                bits.append(f"{k}={c[k]}")
        rows.append(" ".join(str(b) for b in bits if b))
    return "\n".join(rows)


ASK = (
    "You are using a web application for a person, as they would. They want to do this on the screen "
    "below:\n\n  {what}\n\n(It is one step of: \"{says}\".)\n\n{done}"
    "The screen ({url}) shows:\n---\n{text}\n---\n\nIts controls, numbered:\n{controls}\n\n"
    "Reply with JSON only: {{\"actions\": [{{\"idx\": <number>, \"do\": \"click\"|\"fill\"|\"select\"|"
    "\"check\"|\"uncheck\"|\"press\"|\"upload\", \"value\": <text for fill, the option's text for select, a key "
    "for press, \"picture\" or \"document.pdf\" for upload on a file control>}}], \"done\": <true when these actions finish what they want to do>, \"cannot\": <empty, or "
    "why nothing on this screen can do it>}}. Use only controls listed. Do only what they want — not the "
    "steps after it. If an earlier action already did part of it, do the rest. A control that already shows "
    "what they want needs no action — a quantity already at the number they want is left as it is. When the screen asks for a field they did "
    "not mention, fill it with what a person would enter there."
)


def ask_model(what: str, says: str, look: dict, done: list[str], about: list[str] | None = None) -> dict:
    from services.llm_client import complete
    about_line = ("The records it is about — when the screen lists several, act on these, by their names: "
                  + "; ".join(about) + "\n\n") if about else ""
    prompt = about_line + ASK.format(what=what, says=says, url=look.get("url", ""),
                        text=str(look.get("text") or "")[:2500], controls=_shown(look)[:9000],
                        done=("Already done for this step: " + "; ".join(done) + "\n\n") if done else "")
    raw = ""
    for attempt in (1, 2):
        try:
            raw = complete(model=RESOLVE_MODEL, max_tokens=800, temperature=0, content=prompt)
            break
        except Exception as exc:  # noqa: BLE001 — a dropped connection is tried once more
            if attempt == 2 or "connection" not in str(exc).lower():
                raise
    m = re.search(r"\{.*\}", str(raw or ""), re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except ValueError:
        out = {}
    if not isinstance(out, dict):
        out = {}
    out.setdefault("actions", [])
    return out


class Recipes:
    """The controls each statement's steps were found to be, kept beside the
    app (`.forge/expects/recipes.json`), keyed by the step's words so a
    changed step is resolved afresh."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.rows: dict[str, list[dict]] = json.loads(path.read_text())
        except (OSError, ValueError):
            self.rows = {}

    @staticmethod
    def key(statement: str, index: int, what: str) -> str:
        return f"{statement}:{index}:{hashlib.sha1(what.encode()).hexdigest()[:10]}"

    def get(self, key: str) -> list[dict] | None:
        return self.rows.get(key)

    _lock = threading.Lock()

    def put(self, key: str, actions: list[dict]) -> None:
        # ONE WRITER, AND WHAT THE OTHER BENCH WROTE IS KEPT: two runners
        # resolve statements side by side (`expects.build.BENCHES`).
        with self._lock:
            self.rows[key] = actions
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({**self._on_disk(), **self.rows}, indent=1))

    def _on_disk(self) -> dict:
        try:
            rows = json.loads(self.path.read_text())
            return rows if isinstance(rows, dict) else {}
        except (OSError, ValueError):
            return {}

    def drop(self, key: str) -> None:
        if self.rows.pop(key, None) is not None:
            self.path.write_text(json.dumps(self.rows, indent=1))


__all__ = ["describe", "find", "ask_model", "Recipes", "RESOLVE_MODEL", "ROUNDS"]

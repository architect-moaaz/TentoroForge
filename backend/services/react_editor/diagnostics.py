"""The compiler's words into a person's.

`typecheck` returns lines like ``view.tsx(12,7): error TS2322: Type '"big"' is
not assignable to type '"sm" | "lg" | undefined'.`` — exact, and unreadable to
the person the editor is for. Each becomes a finding with the file, the line,
the raw message for the Advanced view, and a plain sentence for everyone else
that says what happened and what to do next (UX-004).
"""
from __future__ import annotations

import re
from typing import Any

_LINE = re.compile(r"^(?P<file>[\w./-]+)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>TS\d+): (?P<msg>.*)$")

_PLAIN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Type '(?P<got>[^']*)' is not assignable to type '(?P<want>[^']*)'"),
     "{where}: {got} is not something the app accepts here — it expects {want}."),
    (re.compile(r"Cannot find name '(?P<name>[^']*)'"),
     "{where}: uses “{name}”, which this page does not have yet. Ask Smith to add it, or undo."),
    (re.compile(r"Property '(?P<name>[^']*)' does not exist on type"),
     "{where}: “{name}” is not something this page's data has."),
    (re.compile(r"Cannot find module '(?P<mod>[^']*)'"),
     "{where}: the page refers to “{mod}”, which this application does not include."),
    (re.compile(r"is missing the following properties from type[^:]*: (?P<props>.*)$"),
     "{where}: something required is missing — {props}."),
    (re.compile(r"Property '(?P<name>[^']*)' is missing in type"),
     "{where}: “{name}” is required here and has not been given."),
    (re.compile(r"Expected \d+ arguments?, but got \d+"),
     "{where}: this action is not given everything it needs."),
    (re.compile(r"JSX element '(?P<tag>[^']*)' has no corresponding closing tag"),
     "{where}: the “{tag}” block is not closed properly."),
    (re.compile(r"'(?P<what>[^']*)' is declared but its value is never read"),
     "{where}: “{what}” is no longer used."),
]


def _shorten(t: str, n: int = 60) -> str:
    t = t.strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def plain(message: str, where: str) -> str:
    for pattern, template in _PLAIN:
        m = pattern.search(message)
        if m:
            fields = {k: _shorten(v) for k, v in m.groupdict().items()}
            return template.format(where=where, **fields)
    return f"{where}: {_shorten(message, 160)}"


def finding(raw: str) -> dict[str, Any]:
    m = _LINE.match(raw.strip())
    if not m:
        return {"file": None, "line": None, "code": None, "raw": raw,
                "plain": f"This page: {_shorten(raw, 160)}", "severity": "must-fix"}
    file, line = m.group("file"), int(m.group("line"))
    what = {"view.tsx": "the page", "load.ts": "what the page loads", "page.tsx": "the page's route"}.get(file, file)
    where = f"Line {line} of {what}"
    return {"file": file, "line": line, "code": m.group("code"), "raw": raw,
            "plain": plain(m.group("msg"), where), "severity": "must-fix"}


def findings(raw_lines: list[str]) -> list[dict[str, Any]]:
    return [finding(r) for r in raw_lines]

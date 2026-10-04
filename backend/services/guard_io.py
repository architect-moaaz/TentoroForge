"""Read and write a JSON file the way its author wrote it.

A guard that rewrites a page or a workflow must change what it means to and
nothing else: same indent, same escaping, same trailing newline, and an
atomic replace so a crash never leaves half a file. ``dump_like`` mirrors the
original text's conventions; ``write_like`` writes through a temp file.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any


def read_raw(path: str) -> str:
    """The file's text with its line endings untouched (text mode would turn
    CRLF into LF before ``dump_like`` could see it)."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def dump_like(raw: str | None, obj: Any) -> str:
    """Serialize ``obj`` with the conventions of ``raw`` (the file's current
    text): indent width (or compact), non-ASCII escaping, trailing newline."""
    raw = raw or ""
    m = re.search(r"\n( +|\t)\"", raw)
    if m:
        indent: Any = "\t" if m.group(1) == "\t" else len(m.group(1))
        kw: dict = {"indent": indent}
    elif "\n" in raw.strip():
        kw = {"indent": 2}
    elif raw.strip():
        kw = {"separators": (", ", ": ")} if re.search(r'", "|": "', raw) else {"separators": (",", ":")}
    else:
        kw = {"indent": 2}
    text = json.dumps(obj, ensure_ascii=("\\u" in raw), **kw)
    if raw.endswith("\n") or not raw:
        text += "\n"
    if "\r\n" in raw:
        text = text.replace("\n", "\r\n")
    return text


def write_atomic(path: str, text: str) -> None:
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_like(path: str, raw: str | None, obj: Any) -> None:
    write_atomic(path, dump_like(raw, obj))

"""The documents a user supplied instead of typing, kept beside the Blueprint.

§5 lets an application be described by handing over a specification as well
as by typing; §14 makes what the document said requirements EVIDENCE, distinct
from what the person said. The first version folded the document text — with
the instruction telling the agent how to read it — into `application.description`,
which is the user's own words. The prompt scaffolding then surfaced in the
Blueprint viewer, in every `changeHistory[].userRequest`, and in Smith's own
context as if the user had typed it.

Stored here instead, in the order they arrived, so that every run of the
definition — the first, a clarified re-run, the build after approval — can
put the same labelled block in front of the agents, and the description
stays the description. Numbered as the agents cite them: `document 1` is
the first file in this directory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

DOCUMENT_DIR = Path(".forge") / "documents"

#: The nodes shown the documents. The requirements agent turns them into
#: requirements with `document N` evidence; the application model names the
#: product from them. A page or a schema agent works from the requirements
#: those two produced, and a forty-page specification on every call would be
#: paid for on every call.
READS_DOCUMENTS = frozenset({"requirements", "application_model"})
_NAME = re.compile(r"^document-(\d+)\.md$")


def directory(output_dir: str | Path) -> Path:
    return Path(output_dir) / DOCUMENT_DIR


def _entries(output_dir: str | Path) -> list[tuple[int, Path]]:
    root = directory(output_dir)
    if not root.is_dir():
        return []
    out = []
    for p in root.iterdir():
        m = _NAME.match(p.name)
        if m and p.is_file():
            out.append((int(m.group(1)), p))
    return sorted(out)


def texts(output_dir: str | Path) -> list[str]:
    """The stored documents, first-arrived first — `document 1` is index 0."""
    return [p.read_text("utf-8") for _, p in _entries(output_dir)]


def store(output_dir: str | Path, documents: Iterable[str]) -> list[Path]:
    """Keep `documents`, skipping blanks and any text already stored.

    Idempotent on resend: the panel carries the same file on every turn of a
    clarifying exchange, and a second copy would be `document 2` — a
    different citation for the same evidence.
    """
    blocks = [str(t).strip() for t in (documents or []) if str(t or "").strip()]
    if not blocks:
        return []
    known = texts(output_dir)
    next_n = (_entries(output_dir)[-1][0] + 1) if _entries(output_dir) else 1
    root = directory(output_dir)
    written: list[Path] = []
    for block in blocks:
        if block in known:
            continue
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"document-{next_n}.md"
        path.write_text(block, "utf-8")
        written.append(path)
        known.append(block)
        next_n += 1
    return written


def labelled(documents: Iterable[str]) -> str:
    """The block an agent reads: each document under its citation label."""
    blocks = [str(t).strip() for t in (documents or []) if str(t or "").strip()]
    if not blocks:
        return ""
    parts = ["SUPPLIED DOCUMENTS \u2014 the user provided these rather than "
             "typing them. Treat them as requirements evidence (\u00a714), not "
             "as conversation:"]
    for i, block in enumerate(blocks, start=1):
        parts.append(f"\n--- document {i} ---\n{block}")
    return "\n".join(parts)


def addendum(output_dir: str | Path | None, node: str) -> str:
    """The labelled block for `node`, or "" when it reads none or none exist."""
    if not output_dir or node not in READS_DOCUMENTS:
        return ""
    block = labelled(texts(output_dir))
    return f"\n\n{block}" if block else ""

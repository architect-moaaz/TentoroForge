"""What the person said, carried to every agent a turn briefs.

Smith briefs a specialist in its own words — one line, what it took the ask
to mean. What it left out was lost: the agent never saw the person's message.
The turn sets it here once; every brief Smith hands on carries it beside
Smith's reading, so the agent can tell the two apart.
"""
from __future__ import annotations

from contextvars import ContextVar

#: The ask of the turn in progress: the person's message (with any ask it
#: continues), or the platform's fault when the turn is unattended.
ASKED: ContextVar[str] = ContextVar("smith_asked", default="")


def with_their_words(brief: str) -> str:
    """`brief` with the turn's ask beside it, unless it already holds it."""
    said = " ".join((ASKED.get() or "").split())
    brief = brief or ""
    if not said or said in " ".join(brief.split()):
        return brief
    return (f"{brief}\n\nThe request as it was made, in its own words — what the brief above "
            f"is Smith's reading of: \"{said[:2000]}\"")

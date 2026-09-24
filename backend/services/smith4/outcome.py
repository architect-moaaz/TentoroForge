"""What one step, and one turn, produce."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Outcome:
    """The shape every seam's result is read into, and the shape a turn returns.

    ``status`` in {"resolved", "asked", "needs_user", "no_op"} — the same four
    the chat surface has always shown. ``finding`` separates the two things
    ``needs_user`` means: a FINDING is something the platform PROVED about the
    work just done (git says the diff missed the named file; the composer did
    not draw what it was told; the page did not compile) and the loop acts on
    it; without one, ``needs_user`` and ``asked`` are the person's, and the turn
    ends. ``said`` is always written for the person; ``finding`` for whatever
    reads it next.
    """
    status: str
    said: str = ""
    options: list[str] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)
    diff_summary: str = ""
    finding: str = ""

    @property
    def done(self) -> bool:
        """Whether the step completed — as opposed to asked, or refused."""
        return self.status in ("resolved", "no_op")


def from_seam(out: dict[str, Any], *, ok: str = "Done.", fail: str,
              status_ok: str = "resolved") -> Outcome:
    """A seam's `{applied, reason, diff_summary, edited_paths, options, asked}`
    envelope as an Outcome. Every `services.smith.*_change.run` returns this
    shape; the adapters in `smith_session` re-read it twenty-five times."""
    if out.get("asked"):
        return Outcome(status="asked", said=str(out.get("reason") or ""),
                       options=list(out.get("options") or []))
    if not out.get("applied"):
        return Outcome(status="needs_user", said=str(out.get("reason") or fail),
                       options=list(out.get("options") or []))
    touched = list(out.get("edited_paths") or [])
    return Outcome(status=status_ok, said=str(out.get("diff_summary") or ok),
                   touched=touched, diff_summary=", ".join(touched[:8]) if touched else "")


__all__ = ["Outcome", "from_seam"]

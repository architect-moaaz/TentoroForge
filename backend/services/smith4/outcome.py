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
    #: The tools the turn called, in order — what a platform caller (self-heal,
    #: the verify pass) reports as the turn's trace.
    steps: list[str] = field(default_factory=list)

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
        reason = str(out.get("reason") or fail)
        options = list(out.get("options") or [])
        # A SEAM THAT DID NOTHING TELLS THE LOOP FIRST. "Refused 2 times and
        # nothing has been changed. The last reason was: the agent returned
        # nothing usable" was F&B's whole reply to "do them in order" — twice.
        # The loop can read why and go another way (a page's code, another
        # section); only what it cannot settle reaches the person, after what
        # landed. A result with choices is a question for the person.
        return Outcome(status="needs_user", said=reason, options=options,
                       finding="" if options else reason)
    touched = list(out.get("edited_paths") or [])
    return Outcome(status=status_ok, said=str(out.get("diff_summary") or ok),
                   touched=touched, diff_summary=", ".join(touched[:8]) if touched else "")


__all__ = ["Outcome", "from_seam"]

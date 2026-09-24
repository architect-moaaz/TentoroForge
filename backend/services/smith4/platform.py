"""A turn the platform starts — a crash, a failed journey, a page that did not pass.

Self-heal, the verify pass and the journey verifier used to drive the legacy
agent with a prompt and read back `{answer, question, edited_paths, trace}`.
They drive the same loop a person does now: the fault is the ask, the steps
are the same reads and writes, and what changed on disk is what the tree
says changed. This is the one adapter between those callers and `handle`,
so the shape they read stays the shape they read.

COMMITTED HERE WHEN THE CALLER SAYS SO. The verify pass tells a stalled round
from a productive one by comparing git HEAD before and after, and stamps the
round's commit; the legacy agent committed its own edits, so that worked.
The loop does not commit — a person's change is one Blueprint version and
one undo, and git is the project's, not Smith's — so a caller that measures
in commits asks for one here, staged to what the turn touched and nothing
else. Self-heal keeps its own commit, as it always did.
"""
from __future__ import annotations

import logging
from typing import Any

from services.smith4.handle import handle

logger = logging.getLogger(__name__)


def smith_result(project_id: str, output_dir: str, message: str, *,
                 history: list | None = None, attachments: list[dict] | None = None,
                 max_steps: int | None = None, reasoning: Any = None,
                 commit: bool = False, commit_message: str = "") -> dict[str, Any]:
    """Run one turn and return the legacy result shape. `history` is the
    exchange (a chat turn has one; a crash has none); `attachments` the files
    on this turn."""
    out = handle(project_id=str(project_id), output_dir=str(output_dir), message=message,
                 history=list(history or []), reasoning=reasoning, max_steps=max_steps,
                 attachments=list(attachments or []))
    touched = list(out.touched)
    if commit and touched:
        try:
            from services.fix_applier import _commit
            _commit(str(output_dir), commit_message or "smith: platform turn", git=True, paths=touched)
        except Exception:  # noqa: BLE001 — the change landed; the commit is the caller's bookkeeping
            logger.exception("[smith4] commit after platform turn failed")
    asked = out.status == "asked"
    return {
        "status": out.status,
        "answer": None if asked else (out.said or None),
        "question": out.said if asked else None,
        "edited_paths": touched,
        "trace": [{"tool": t} for t in out.steps],
        "diagnosis": None,
        "finding": out.finding,
    }


__all__ = ["smith_result"]

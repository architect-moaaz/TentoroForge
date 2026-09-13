"""What the Blueprint refused, kept where a person can read it.

A refused composition leaves nothing behind but the validator's sentence in a
ledger line: the tree it judged is gone. On Criterion Refunds v2 four intake
forms were refused three times each for "needs a Property record; nothing
there names one", after the rule had been taught to accept a form that
chooses the record — and no one could say whether the form had the select,
had it in another shape, or had nothing, because the composer's answer was
never written down. §17: what was considered must be inspectable.

One file per refusal under `.forge/refused/`, the proposals as sent to apply
and the reason they were refused. Best-effort and never in the way: a failure
to write the record does not change what apply decided.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

REFUSED_DIR = ".forge/refused"


def record_refusal(output_dir: str | Path, subject: str, attempt: int,
                   proposals: Iterable[Any], reason: str) -> Path | None:
    """Write the refused proposals and the reason; return the path, or None."""
    try:
        directory = Path(output_dir) / REFUSED_DIR
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(subject))
        path = directory / f"{stamp}-{safe}-{attempt}.json"
        path.write_text(json.dumps({
            "subject": subject, "attempt": attempt, "reason": reason,
            "proposals": [
                {"section": getattr(p, "section", None),
                 "natural_key": getattr(p, "natural_key", None),
                 "body": getattr(p, "body", p if isinstance(p, dict) else None)}
                for p in (proposals or [])
            ],
        }, indent=1, default=str), "utf-8")
        return path
    except Exception as exc:  # noqa: BLE001 — evidence, never the outcome
        logger.info("[refusals] could not record %s: %s", subject, exc)
        return None

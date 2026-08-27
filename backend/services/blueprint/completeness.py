"""§23 — how complete the Blueprint is, per dimension, as a number.

§22 gives artifacts a status; §23 asks a different question: is the *document*
finished enough to build from. A run can have every artifact APPROVED and still
be missing a whole dimension — no integrations, no reporting — and nothing in a
per-artifact status says so.

Scored from the document rather than reported by an agent, for the usual reason
(§116): an agent asked "how complete are you" answers from impression, and its
answer is exactly as good as the impression. Counting is not a judgement call.

Each dimension scores 0..1 on evidence that dimension actually exists, and the
score is deliberately blunt — it is a gate on obvious absence, not a quality
measure. A dimension that legitimately does not apply (an app with no external
integrations) will score low, which is correct: the reader should see it and
decide, rather than have the document quietly assert completeness.
"""
from __future__ import annotations

from typing import Any


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


def _present(items: Any, target: int) -> float:
    """Fraction of ``target`` present, capped at 1.0."""
    n = len(_live(items))
    return min(1.0, round(n / target, 2)) if target else (1.0 if n else 0.0)


def _mean_confidence(items: Any) -> float:
    live = [i for i in _live(items) if i.get("confidence") is not None]
    if not live:
        return 0.0
    return round(sum(i["confidence"] for i in live) / len(live), 2)


def score(doc: dict) -> dict[str, float]:
    """One score per §23 dimension. Pure: reads the document, writes nothing."""
    product = doc.get("product") or {}
    application = doc.get("application") or {}
    data = doc.get("data") or {}
    security = doc.get("security") or {}

    return {
        # Purpose and domain are prose: either stated with substance, or not.
        "applicationPurpose": 1.0 if len(
            (product.get("description") or application.get("description") or "")
        ) > 40 else 0.0,
        "domain": 1.0 if application.get("domain") else 0.0,
        "roles": _present(doc.get("roles"), 2),
        "capabilities": _present(product.get("capabilities"), 3),
        "data": _present(data.get("entities"), 3),
        "pages": _present(doc.get("pages"), 3),
        "workflows": _present(doc.get("workflows"), 2),
        "businessRules": _present(doc.get("businessRules"), 3),
        "integrations": _present(doc.get("integrations"), 1),
        # Security is not a count — a role list with no permissions guarding it
        # is the failure mode worth catching.
        "security": round(min(
            1.0,
            (0.5 if _live(doc.get("permissions")) else 0.0)
            + (0.5 if (security.get("authentication") or security.get("authorization"))
               else 0.0),
        ), 2),
        # Reporting is the dimension most often silently absent: widgets are
        # what turn a data model into something a user can read at a glance.
        "reporting": _present(doc.get("widgets"), 3),
    }


def weakest(doc: dict, limit: int = 3) -> list[tuple[str, float]]:
    """The dimensions least evidenced, worst first — what to work on next."""
    return sorted(score(doc).items(), key=lambda kv: kv[1])[:limit]


def apply_completeness(svc: Any) -> dict[str, float]:
    """Score and write. Idempotent — the same document scores the same."""
    scored = score(svc.doc)
    svc.doc["completeness"] = scored
    svc.save()
    return scored

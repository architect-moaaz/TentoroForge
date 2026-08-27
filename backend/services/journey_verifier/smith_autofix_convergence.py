"""V&F 2.0 M2 — cross-round convergence helper.

After a Smith-dispatched fix, we run Playwright a second time and
compare the two rounds to answer: "did the fault we tried to fix
actually pass this time?"

One tiny function, one small dataclass. Kept out of ``smith_autofix.py``
because it doesn't need the imports (no Smith agent, no fault_context)
and the tests are cleaner in isolation.
"""
from __future__ import annotations

from typing import Any

from services.journey_verifier.fault_classifier import ClassifiedFault


def mark_healed_faults(
    round1_faults: list[ClassifiedFault],
    round2_faults: list[dict[str, Any]],
) -> tuple[list[ClassifiedFault], list[ClassifiedFault]]:
    """Partition ``round1_faults`` into (healed, still_broken).

    A round-1 fault is considered *healed* if the same ``interaction_id``
    is either:
      1. NOT present in ``round2_faults`` (the runner only surfaces
         failing interactions in its faults list, so absence == pass), or
      2. Present in ``round2_faults`` but marked ``passed=True``
         (defensive — future runner shapes might include passing
         interactions).

    Matching is exact-string on ``interaction_id``. When a round-1 fault
    has no interaction id (``"?"``), it can never be marked healed
    reliably; those stay in ``still_broken``.
    """
    if not round1_faults:
        return [], []

    # Build the round-2 fault index by interaction_id. If an entry has
    # `passed=True` treat it as absent from the fault set.
    r2_ids_still_failing: set[str] = set()
    for raw in round2_faults or []:
        if not isinstance(raw, dict):
            continue
        iid = _interaction_id(raw)
        if not iid or iid == "?":
            continue
        if raw.get("passed") is True:
            continue
        r2_ids_still_failing.add(iid)

    healed: list[ClassifiedFault] = []
    still_broken: list[ClassifiedFault] = []
    for cf in round1_faults:
        iid = (cf.interaction_id or "").strip()
        if not iid or iid == "?":
            still_broken.append(cf)
            continue
        if iid in r2_ids_still_failing:
            still_broken.append(cf)
        else:
            healed.append(cf)
    return healed, still_broken


def _interaction_id(raw: dict[str, Any]) -> str:
    """Extract the interaction id from a raw fault dict (same shape the
    classifier consumes)."""
    interaction = raw.get("interaction") or {}
    if isinstance(interaction, dict):
        iid = interaction.get("id")
        if isinstance(iid, str) and iid:
            return iid
    for key in ("interaction_id", "id"):
        v = raw.get(key)
        if isinstance(v, str) and v:
            return v
    return "?"

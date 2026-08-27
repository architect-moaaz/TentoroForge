"""Signature-moves detector — Sprint 6 of Forge Great Again.

The page critic (Sprint 3) already scores the SIGNATURE MOVES dimension
via LLM judgement. Sprint 6 adds a DETERMINISTIC check that runs first:
walk the schema, count how many of the brief's committed signature
moves actually appear, and fail-loud if fewer than the mandated
minimum (default 2) were applied.

Why deterministic AND LLM?
  · The LLM critic is noisy. Sometimes it forgets to check for
    signature moves. A regex is not smart, but it never forgets.
  · Deterministic gaps carry a specific "you didn't apply move X"
    message that's directly actionable in the REVISE round.

Detection strategy
------------------
Signature-move ``render`` functions modify schema nodes in specific
ways (add a variant, wrap in a specific container, tag with a data
attribute). Rather than duplicate each render's logic, this detector
uses two loose signals:

  1. **Name appearance**: the move's ``kind`` (e.g. ``"ledger_row"``)
     appears as a substring in the serialized schema. Matches when the
     render adds a class, data attribute, or variant name derived from
     the kind — a very common pattern.
  2. **Keyword aliases**: a per-move alias list captures common
     alternative surface forms (e.g. ``ledger_row`` → also matches
     ``"ledger"``, ``"hairline"``). Keeps detection tolerant of
     stylistic naming.

The detector is deliberately lossy — it undercounts, never overcounts.
Undercount → LLM critic gets a chance to disagree via prose. Overcount
would silently mask a real problem.
"""
from __future__ import annotations

import json
import os
from typing import Iterable

_FLAG = "FORGE_PAGE_SIGNATURE_MOVES_GATE"
_MIN_APPLIED_DEFAULT = 2


def signature_moves_gate_enabled() -> bool:
    """Read the opt-in flag. Default OFF for shadow rollout — off means
    the detector still runs and reports in the critique payload, but
    doesn't ESCALATE the gap to HIGH severity. Flipping to 1 makes
    missing signature moves a HIGH-severity gap that triggers REVISE."""
    return os.getenv(_FLAG, "0").strip() == "1"


def min_signature_moves_required() -> int:
    """How many committed signature moves must appear on a page."""
    raw = os.getenv("FORGE_PAGE_SIGNATURE_MOVES_MIN")
    if raw is None:
        return _MIN_APPLIED_DEFAULT
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _MIN_APPLIED_DEFAULT
    return max(0, n)


# ── Per-move detection aliases ──────────────────────────────────────────
#
# Kind → list of substrings that indicate the move was applied. All
# lowercase; the detector normalizes the haystack the same way. Add
# entries as new moves ship. When a move isn't listed here, the detector
# falls back to just its ``kind`` string.

_MOVE_ALIASES: dict[str, tuple[str, ...]] = {
    "ledger_row":        ("ledger", "hairline", "mono-row"),
    "keyline_breadcrumb": ("keyline", "breadcrumb-keyline"),
    "velocity_sparkline": ("velocity", "sparkline"),
    "status_stripe":     ("status-stripe", "left-stripe"),
    "card_elevation":    ("elevated", "elevation-", "shadow-md", "shadow-lg"),
    "warm_serif_h1":     ("warm-serif", "font-serif", "display-serif"),
}


def detect_signature_moves(
    schema: dict,
    committed_kinds: Iterable[str] | None = None,
) -> dict:
    """Walk ``schema`` and detect which committed signature moves appear.

    Args:
        schema: The page schema dict.
        committed_kinds: The move kinds the design brief committed to.
            When None, all registered move kinds are considered eligible
            (loose gate — anything counts).

    Returns:
        {
          "expected": [<kind>, ...],     # committed set (sorted)
          "detected": [<kind>, ...],     # subset actually found
          "missing":  [<kind>, ...],     # expected - detected
          "min_required":   int,         # threshold
          "meets_minimum":  bool,        # detected count >= min_required
        }
    """
    committed = _resolve_committed_kinds(committed_kinds)
    haystack = _schema_to_haystack(schema)

    detected: list[str] = []
    for kind in committed:
        if _kind_appears(kind, haystack):
            detected.append(kind)

    min_required = min_signature_moves_required()
    detected_sorted = sorted(detected)
    return {
        "expected": sorted(committed),
        "detected": detected_sorted,
        "missing":  sorted(set(committed) - set(detected_sorted)),
        "min_required":  min_required,
        "meets_minimum": len(detected_sorted) >= min_required,
    }


def as_critic_gap(detection: dict) -> dict | None:
    """Convert a detection result into a critic-gap dict, or None when
    the minimum was met. When the gate flag is off, severity is
    downgraded to ``medium`` (observability only). When on, HIGH so the
    REVISE loop triggers.
    """
    if not isinstance(detection, dict):
        return None
    if detection.get("meets_minimum"):
        return None
    missing = detection.get("missing") or []
    detected = detection.get("detected") or []
    min_required = detection.get("min_required") or _MIN_APPLIED_DEFAULT
    if not missing and not detected:
        return None  # No expected set to enforce.
    severity = "high" if signature_moves_gate_enabled() else "medium"
    if missing:
        note = (
            f"Signature moves under-applied ({len(detected)}/{min_required}). "
            f"Missing: {', '.join(missing)}. Apply at least "
            f"{min_required - len(detected)} more so the page carries the "
            f"app's committed visual DNA."
        )
    else:
        note = (
            f"Signature moves under-applied ({len(detected)}/{min_required}) "
            f"— every committed move showed up but the required floor was "
            f"not met. Re-apply or add another."
        )
    return {"severity": severity, "note": note}


# ── Helpers ─────────────────────────────────────────────────────────────

def _resolve_committed_kinds(committed: Iterable[str] | None) -> list[str]:
    if committed is not None:
        return [str(k).strip() for k in committed if isinstance(k, str) and str(k).strip()]
    # Fall back to the full registered set — permissive default so the
    # detector is useful even when the brief lacks a signature_moves list.
    try:
        from services.signature_moves import known_kinds
        return list(known_kinds())
    except Exception:  # noqa: BLE001
        return []


def _schema_to_haystack(schema: dict) -> str:
    """Serialize schema to lowercase JSON string for substring matching."""
    try:
        return json.dumps(schema).lower()
    except Exception:  # noqa: BLE001 — schema shape is unpredictable
        return ""


def _kind_appears(kind: str, haystack: str) -> bool:
    """True if the kind (or any of its aliases) appears as a substring."""
    if not kind or not haystack:
        return False
    needles = [kind.lower()]
    aliases = _MOVE_ALIASES.get(kind)
    if aliases:
        needles.extend(a.lower() for a in aliases)
    return any(n in haystack for n in needles)


__all__ = [
    "signature_moves_gate_enabled",
    "min_signature_moves_required",
    "detect_signature_moves",
    "as_critic_gap",
]

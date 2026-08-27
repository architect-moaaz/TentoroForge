"""Spec D Wave 1 — capability envelope for design-agent numeric emissions.

Range validators for the numeric+string design-DNA fields Wave 1 wants
the design agent to emit directly (``radius_px``, ``gutter_px``,
``shadow_scale``, ``header_align``, ``card_border``). Downstream
compilers validate against this envelope; out-of-range values are
clamped with a warning rather than crashing the render.

Kept as pure functions with no LLM — this is the deterministic
guardrail, not the intelligence. Wave 1 ships the envelope so the
migration off ``design_language.py`` / ``domain_ux_specs.py`` has a
place to land these fields BEFORE consumers are cut over. The
``envelope_report`` helper is what the design-critic pass uses to
surface issues without silently mutating the spec.

Ranges rationale
----------------
- ``radius_px``  : 0..32   — 0 = perfectly square; 32 covers a soft-pill
                             card corner. Anything beyond snaps to pill
                             (999) via the borderRadius scale.
- ``gutter_px``  : 4..64   — 4 = ultra-dense tabular; 64 = editorial
                             margin. Wider than 64 breaks 12-col grids.
- ``shadow_scale``: 0..5   — 0 = flat; 5 = maximum floating card. Ties
                             to Tailwind-style shadow steps.
- ``header_align``: {left,center,right,split}
- ``card_border`` : {none,hairline,standard,heavy}
"""
from __future__ import annotations

from typing import Any


# ── Constants (single source of truth for the ranges) ────────────────
RADIUS_PX_MIN = 0
RADIUS_PX_MAX = 32

GUTTER_PX_MIN = 4
GUTTER_PX_MAX = 64

SHADOW_SCALE_MIN = 0
SHADOW_SCALE_MAX = 5

HEADER_ALIGN_ALLOWED: frozenset[str] = frozenset({"left", "center", "right", "split"})
HEADER_ALIGN_DEFAULT = "left"

CARD_BORDER_ALLOWED: frozenset[str] = frozenset({"none", "hairline", "standard", "heavy"})
CARD_BORDER_DEFAULT = "hairline"


# ── Numeric clamps ───────────────────────────────────────────────────

def _clamp_int(v: Any, lo: int, hi: int) -> int:
    """Coerce ``v`` to int and clamp to [lo, hi]. Non-numeric falls to lo."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return lo
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n


def clamp_radius_px(v: Any) -> int:
    """Clamp a radius emission to [0, 32]. Non-numeric → 0."""
    return _clamp_int(v, RADIUS_PX_MIN, RADIUS_PX_MAX)


def clamp_gutter_px(v: Any) -> int:
    """Clamp a gutter emission to [4, 64]. Non-numeric → 4."""
    return _clamp_int(v, GUTTER_PX_MIN, GUTTER_PX_MAX)


def clamp_shadow_scale(v: Any) -> int:
    """Clamp a shadow-scale emission to [0, 5]. Non-numeric → 0."""
    return _clamp_int(v, SHADOW_SCALE_MIN, SHADOW_SCALE_MAX)


# ── Enum-shaped string validators ────────────────────────────────────

def validate_header_align(v: Any) -> str:
    """Return ``v`` if it names one of the allowed alignments, else
    :data:`HEADER_ALIGN_DEFAULT`. Case-insensitive on input; canonicalizes
    to lowercase on output."""
    if isinstance(v, str):
        low = v.strip().lower()
        if low in HEADER_ALIGN_ALLOWED:
            return low
    return HEADER_ALIGN_DEFAULT


def validate_card_border(v: Any) -> str:
    """Return ``v`` if it names one of the allowed card-border weights,
    else :data:`CARD_BORDER_DEFAULT`. Case-insensitive on input."""
    if isinstance(v, str):
        low = v.strip().lower()
        if low in CARD_BORDER_ALLOWED:
            return low
    return CARD_BORDER_DEFAULT


# ── Whole-spec walker ────────────────────────────────────────────────

_NUMERIC_FIELDS: dict[str, tuple[int, int]] = {
    "radius_px": (RADIUS_PX_MIN, RADIUS_PX_MAX),
    "gutter_px": (GUTTER_PX_MIN, GUTTER_PX_MAX),
    "shadow_scale": (SHADOW_SCALE_MIN, SHADOW_SCALE_MAX),
}

_ENUM_FIELDS: dict[str, tuple[frozenset[str], str]] = {
    "header_align": (HEADER_ALIGN_ALLOWED, HEADER_ALIGN_DEFAULT),
    "card_border": (CARD_BORDER_ALLOWED, CARD_BORDER_DEFAULT),
}


def envelope_report(spec: dict) -> dict:
    """Walk a (possibly nested) design-spec dict and report envelope
    violations without mutating the input.

    Returns::

        {
            "clamped": [{"field": ..., "from": ..., "to": ...}, ...],
            "invalid": [{"field": ..., "value": ...}, ...],
        }

    ``clamped`` = numeric out-of-range values that would be snapped
    to the nearest boundary by the ``clamp_*`` helpers. ``invalid`` =
    enum-shaped fields whose values aren't in the allowed set (they'd
    fall back to the enum default).

    Fields are matched by NAME anywhere in the tree — spec dicts nest
    (layout.gutter_px, card.card_border) and this walker is dumb on
    purpose; the field-name namespace is small and unambiguous.
    """
    if not isinstance(spec, dict):
        return {"clamped": [], "invalid": []}

    clamped: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _NUMERIC_FIELDS:
                    lo, hi = _NUMERIC_FIELDS[k]
                    try:
                        n = int(v)
                    except (TypeError, ValueError):
                        invalid.append({"field": k, "value": v})
                    else:
                        if n < lo or n > hi:
                            snapped = lo if n < lo else hi
                            clamped.append({"field": k, "from": n, "to": snapped})
                    # still recurse in case the dict has nested content
                elif k in _ENUM_FIELDS:
                    allowed, _default = _ENUM_FIELDS[k]
                    if not (isinstance(v, str) and v.strip().lower() in allowed):
                        invalid.append({"field": k, "value": v})
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(spec)
    return {"clamped": clamped, "invalid": invalid}


__all__ = [
    "RADIUS_PX_MIN", "RADIUS_PX_MAX",
    "GUTTER_PX_MIN", "GUTTER_PX_MAX",
    "SHADOW_SCALE_MIN", "SHADOW_SCALE_MAX",
    "HEADER_ALIGN_ALLOWED", "HEADER_ALIGN_DEFAULT",
    "CARD_BORDER_ALLOWED", "CARD_BORDER_DEFAULT",
    "clamp_radius_px",
    "clamp_gutter_px",
    "clamp_shadow_scale",
    "validate_header_align",
    "validate_card_border",
    "envelope_report",
]

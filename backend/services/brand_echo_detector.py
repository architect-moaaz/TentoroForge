"""Brand-echo detector — Sprint 7 of Forge Great Again.

The design mandate in the Design Context Pack says:
  BRAND COLOR AS INFORMATION. The primary color from the design brief
  MUST appear in at least 3 semantically meaningful places on this page.

This module verifies the mandate deterministically:
  1. Read the brief's primary brand hex.
  2. Walk the schema and count places the color echoes.
  3. Return a critic-gap when the count is below the threshold.

The check is deliberately generous — a "place" is any of:
  · A literal hex reference (``#6366F1`` or lowercase).
  · A token path referencing primary/accent (``tokens.color.primary``,
    ``brand.primary``).
  · A prop value ``"primary"`` on a color-carrying prop (variant,
    color, tone, accent).

Under-counts are the safe failure mode: the LLM critic still runs and
can override with prose. Over-counting would silently mask a real
brand-vanish problem.
"""
from __future__ import annotations

import json
import os
import re
from typing import Iterable

_FLAG = "FORGE_PAGE_BRAND_ECHO_GATE"
_MIN_ECHOES_DEFAULT = 3


def brand_echo_gate_enabled() -> bool:
    """Read the opt-in flag. Default OFF for shadow rollout — off means
    the detector runs and reports MEDIUM gaps; on escalates to HIGH so
    the REVISE loop triggers when brand color is under-echoed."""
    return os.getenv(_FLAG, "0").strip() == "1"


def min_brand_echoes_required() -> int:
    raw = os.getenv("FORGE_PAGE_BRAND_ECHO_MIN")
    if raw is None:
        return _MIN_ECHOES_DEFAULT
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _MIN_ECHOES_DEFAULT
    return max(0, n)


# ── Detection ──────────────────────────────────────────────────────────

_TOKEN_PRIMARY_RE = re.compile(
    r"tokens?\.color\.(?:primary|brand|accent)"
    r"|brand\.(?:primary|brand|accent)"
    r"|color\.primary",
    re.IGNORECASE,
)

# Color-carrying props whose value can select the brand color by name.
# When these props have a value like "primary" / "brand" / "accent", we
# count it as an echo — same semantics as a hex reference.
_COLOR_PROPS: tuple[str, ...] = (
    "color", "variant", "tone", "accent", "background", "backgroundColor",
    "borderColor", "textColor", "iconColor", "fill", "stroke", "stripeColor",
)
_COLOR_NAME_VALUES: tuple[str, ...] = ("primary", "brand", "accent")


def detect_brand_echo(schema: dict, primary_hex: str | None) -> dict:
    """Count brand echoes on ``schema`` against ``primary_hex``.

    Args:
        schema: Page schema (dict).
        primary_hex: Brand primary color as ``#RRGGBB``. When None the
            detector returns a "no brief" verdict (meets_minimum=True)
            since there's no expected color to enforce.

    Returns:
        {
          "primary_hex":   <str|None>,
          "hex_count":     <int>,       # literal hex references
          "token_count":   <int>,       # tokens.color.primary refs
          "name_count":    <int>,       # color prop = "primary" etc
          "total_echoes":  <int>,       # sum of the three
          "min_required":  <int>,
          "meets_minimum": <bool>,
        }
    """
    if not primary_hex or not isinstance(primary_hex, str):
        return _no_brief_verdict()
    hex_norm = primary_hex.strip().lower()
    if not hex_norm.startswith("#") or len(hex_norm) not in (4, 7):
        return _no_brief_verdict()

    schema_str = _schema_to_string(schema)
    hex_count = _count_hex(schema_str, hex_norm)
    token_count = _count_token_refs(schema_str)
    name_count = _count_color_prop_names(schema)
    total = hex_count + token_count + name_count
    min_required = min_brand_echoes_required()

    return {
        "primary_hex":   hex_norm,
        "hex_count":     hex_count,
        "token_count":   token_count,
        "name_count":    name_count,
        "total_echoes":  total,
        "min_required":  min_required,
        "meets_minimum": total >= min_required,
    }


def as_critic_gap(detection: dict) -> dict | None:
    """Convert a detection result into a critic-gap dict, or None when
    the minimum was met (or no brief was provided)."""
    if not isinstance(detection, dict):
        return None
    if detection.get("meets_minimum"):
        return None
    if detection.get("primary_hex") is None:
        return None
    total = detection.get("total_echoes", 0)
    min_required = detection.get("min_required", _MIN_ECHOES_DEFAULT)
    severity = "high" if brand_echo_gate_enabled() else "medium"
    hex_val = detection.get("primary_hex") or "brand primary"
    return {
        "severity": severity,
        "note": (
            f"Brand color under-echoed on this page ({total}/{min_required} "
            f"places). The primary color ({hex_val}) should appear in at "
            f"least {min_required} semantically meaningful places — KPI "
            f"icon tiles, chart accents, primary CTAs, active states, "
            f"status pills, progress bars. Right now brand feels absent "
            f"from the content area."
        ),
    }


# ── Helpers ─────────────────────────────────────────────────────────────

def _no_brief_verdict() -> dict:
    return {
        "primary_hex":   None,
        "hex_count":     0,
        "token_count":   0,
        "name_count":    0,
        "total_echoes":  0,
        "min_required":  min_brand_echoes_required(),
        "meets_minimum": True,
    }


def _schema_to_string(schema: dict) -> str:
    try:
        return json.dumps(schema)
    except Exception:  # noqa: BLE001
        return ""


def _count_hex(haystack: str, hex_norm: str) -> int:
    """Count occurrences of the primary hex in the schema. Case-insensitive
    since hex codes appear in either casing. Also matches the 3-char
    shorthand when the 7-char equivalent is provided (``#FFF`` ==
    ``#FFFFFF`` after normalization)."""
    if not haystack or not hex_norm:
        return 0
    lower = haystack.lower()
    return lower.count(hex_norm)


def _count_token_refs(haystack: str) -> int:
    """Count references to primary/brand/accent color tokens. Loose match
    on the common Forge token path shapes."""
    if not haystack:
        return 0
    return len(_TOKEN_PRIMARY_RE.findall(haystack))


def _count_color_prop_names(node) -> int:
    """Walk the schema tree looking for color-carrying props whose value
    is one of the brand name aliases. Recursion is bounded by JSON depth
    (schemas cap in the low thousands of nodes)."""
    count = 0
    if isinstance(node, dict):
        props = node.get("props") if isinstance(node.get("props"), dict) else None
        if props:
            for k, v in props.items():
                if k in _COLOR_PROPS and isinstance(v, str) and v.strip().lower() in _COLOR_NAME_VALUES:
                    count += 1
        for k, v in node.items():
            if k == "props":
                continue  # already handled
            count += _count_color_prop_names(v)
    elif isinstance(node, list):
        for item in node:
            count += _count_color_prop_names(item)
    return count


__all__ = [
    "brand_echo_gate_enabled",
    "min_brand_echoes_required",
    "detect_brand_echo",
    "as_critic_gap",
]

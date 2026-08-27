"""css_sanitize — extract machine-valid CSS values from LLM-polluted strings.

The design agent (and any LLM) loves annotating values: ``"0.5rem (8px)"``,
``"text-3xl (30px) — page titles"``, ``"#C4611F — terracotta"``, ``"1.6 for
body, 1.25 for headings"``. Browsers silently DROP invalid declarations, so
every annotation used to erase a design decision at render time — the single
biggest reason all generated apps converged on the default look.

Every function here is total: it returns a clean value or ``None`` (never
raises), so callers can fall back to the design-DNA value for that slot.
"""
from __future__ import annotations

import re

# --- primitives -------------------------------------------------------------

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
_LENGTH_RE = re.compile(r"-?\d*\.?\d+(?:rem|em|px|%|vh|vw|ch|pt)\b|\b0\b")
_NUMBER_RE = re.compile(r"-?\d*\.?\d+")
_MS_RE = re.compile(r"\d+\s*m?s\b")
_EM_TRACKING_RE = re.compile(r"-?\d*\.?\d+em\b")

# Tailwind text-size classes → rem (the LLM often emits these instead of CSS).
_TAILWIND_TEXT_SIZES = {
    "text-xs": "0.75rem", "text-sm": "0.875rem", "text-base": "1rem",
    "text-lg": "1.125rem", "text-xl": "1.25rem", "text-2xl": "1.5rem",
    "text-3xl": "1.875rem", "text-4xl": "2.25rem", "text-5xl": "3rem",
    "text-6xl": "3.75rem", "text-7xl": "4.5rem", "text-8xl": "6rem",
    "text-9xl": "8rem",
}

# A conservative shape for one box-shadow layer:
#   [inset] <x> <y> [blur] [spread] <color>
_SHADOW_LAYER_RE = re.compile(
    r"(?:inset\s+)?"
    r"(?:-?\d*\.?\d+(?:px|rem|em)?\s+){1,4}"
    r"(?:rgba?\([^)]*\)|hsla?\([^)]*\)|#[0-9a-fA-F]{3,8}|[a-zA-Z]+)"
)

# Font-family names: quoted strings or bare identifier runs.
_FONT_NAME_RE = re.compile(r"'[^']+'|\"[^\"]+\"|[A-Za-z][A-Za-z0-9 +-]*[A-Za-z0-9]")
_GENERIC_FAMILIES = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy",
    "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace",
}


def extract_hex(value: object) -> str | None:
    """First #rrggbb (or #rgb, expanded) anywhere in the string.

    ``"#C4611F — warm terracotta"`` → ``"#c4611f"``.
    """
    if not isinstance(value, str):
        return None
    m = _HEX_RE.search(value)
    if not m:
        return None
    h = m.group(0).lower()
    if len(h) == 4:  # #rgb → #rrggbb
        h = "#" + "".join(ch * 2 for ch in h[1:])
    return h


def extract_css_length(value: object) -> str | None:
    """First CSS length token. ``"0.5rem (8px)"`` → ``"0.5rem"``.

    Also maps Tailwind text-size classes: ``"text-3xl (30px)"`` → ``"1.875rem"``.
    Bare numbers are rejected (ambiguous units) except literal 0.
    """
    if isinstance(value, (int, float)):
        return "0" if value == 0 else None
    if not isinstance(value, str):
        return None
    for cls, rem in _TAILWIND_TEXT_SIZES.items():
        if cls in value:
            return rem
    m = _LENGTH_RE.search(value)
    return m.group(0) if m else None


def extract_number(value: object, lo: float | None = None, hi: float | None = None) -> float | None:
    """First float in the string, optionally clamped to [lo, hi].

    ``"1.6 for body, 1.25 for headings"`` → ``1.6``.
    """
    if isinstance(value, (int, float)):
        n = float(value)
    elif isinstance(value, str):
        m = _NUMBER_RE.search(value)
        if not m:
            return None
        n = float(m.group(0))
    else:
        return None
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def extract_ms(value: object) -> str | None:
    """First duration. ``"150ms for hovers"`` → ``"150ms"``."""
    if not isinstance(value, str):
        return None
    m = _MS_RE.search(value)
    if not m:
        return None
    token = m.group(0).replace(" ", "")
    return token if token.endswith("ms") else token.replace("s", "000ms")


def extract_letter_spacing(value: object) -> str | None:
    """``"-0.02em (tight)"`` → ``"-0.02em"``; ``"normal"`` → ``"0"``."""
    if not isinstance(value, str):
        return None
    if value.strip().lower() in ("normal", "none"):
        return "0"
    m = _EM_TRACKING_RE.search(value)
    return m.group(0) if m else None


def extract_shadow(value: object) -> str | None:
    """Valid box-shadow layers only. ``"0 1px 3px rgba(0,0,0,.1) — cards"`` →
    the matched layer(s); prose around/after layers is discarded.
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.lower() in ("none", "0"):
        return "none"
    layers = _SHADOW_LAYER_RE.findall(v)
    return ", ".join(s.strip() for s in layers) if layers else None


def extract_font_stack(value: object, fallback_generic: str = "sans-serif") -> str | None:
    """Rebuild a clean font stack from a possibly-annotated string.

    ``"Inter — excellent legibility"`` → ``"'Inter', sans-serif"``
    ``"'Fraunces', Georgia, serif"``   → unchanged (already clean)
    Stops at the first token that looks like prose (contains an em-dash
    segment or is lowercase multi-word commentary).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    # Cut at the first annotation marker — everything after is commentary.
    head = re.split(r"\s+—|\s+-\s+|\(", value, maxsplit=1)[0]
    names: list[str] = []
    generics: list[str] = []
    for raw in head.split(","):
        raw = raw.strip().strip("'\"")
        if not raw:
            continue
        low = raw.lower()
        if low in _GENERIC_FAMILIES:
            if low not in generics:
                generics.append(low)
            continue
        # A real family name: letters/digits/spaces, reasonably short, not prose.
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9 ]{0,30}", raw) and len(raw.split()) <= 4:
            names.append(raw)
    if not names:
        return None
    quoted = ", ".join(f"'{n}'" for n in names)
    tail = ", ".join(generics) if generics else fallback_generic
    return f"{quoted}, {tail}"


def extract_weight(value: object) -> str | None:
    """``"700 (bold)"`` → ``"700"``; ``"bold"`` → ``"700"``."""
    named = {"thin": "100", "light": "300", "normal": "400", "regular": "400",
             "medium": "500", "semibold": "600", "bold": "700", "black": "900"}
    if isinstance(value, (int, float)):
        n = int(value)
        return str(n) if 100 <= n <= 1000 else None
    if not isinstance(value, str):
        return None
    low = value.strip().lower()
    for name, num in named.items():
        if low.startswith(name):
            return num
    m = re.search(r"\b([1-9]\d{2})\b", value)
    return m.group(1) if m else None

"""WCAG-style color-contrast + saturation helpers for the vocab composer.

Pure module — no I/O, no LLM, deterministic in its inputs. Used by
:mod:`services.vocab_composer` to validate LLM-proposed palette hex
values: the composer no longer restricts palette hexes to the union of
candidate preset palettes; it lets the LLM propose novel colors as long
as they meet a real accessibility bar (contrast ratio against the
composite bg) and stay within the app's tone (a saturation cap driven
by the brief's ``identity.register``).

Reference:
  * WCAG 2.x contrast formula — https://www.w3.org/TR/WCAG21/#contrast-minimum
  * Relative-luminance uses the sRGB linearization curve.

The saturation helper reads HSL saturation on ``[0, 1]``. It's a coarse
signal — an accent + badge that both land ``> 0.9`` on a "calm" brief
reliably look aggressive; anything ``<= 0.55`` reads restrained. The
composer uses that cheap-and-cheerful signal instead of a full color
psychology model.
"""
from __future__ import annotations


__all__ = [
    "parse_hex",
    "relative_luminance",
    "contrast_ratio",
    "saturation",
    "saturation_cap_for_register",
]


def parse_hex(value: str | None) -> tuple[int, int, int] | None:
    """Return ``(r, g, b)`` in ``0..255`` for a ``#RRGGBB`` string, or None.

    Accepts values with or without leading ``#``. Case-insensitive.
    Returns ``None`` on any invalid input — bad type, wrong length,
    non-hex characters. Never raises.

    Only 6-character hex is accepted. Short-form ``#RGB`` is rejected
    on purpose: every consumer in the composer emits full ``#RRGGBB``,
    and short-form would smuggle in a second parsing path with its
    own edge cases.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.startswith("#"):
        s = s[1:]
    if len(s) != 6:
        return None
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        return None
    return (r, g, b)


def _channel_linear(c8: int) -> float:
    """sRGB linearization for one channel (0..255 → 0.0..1.0)."""
    c = c8 / 255.0
    if c <= 0.03928:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance for an ``(r, g, b)`` triple in 0..255."""
    r, g, b = rgb
    return (
        0.2126 * _channel_linear(r)
        + 0.7152 * _channel_linear(g)
        + 0.0722 * _channel_linear(b)
    )


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """Return the WCAG contrast ratio between two hex colors.

    Ranges from ``1.0`` (identical luminance) to ``21.0``
    (black vs white). Returns ``1.0`` on unparseable input — a caller
    that gets ``1.0`` on a supposedly high-contrast pair should also
    check :func:`parse_hex` itself; the composer treats ``1.0`` as
    "does not clear any bar" which is the right conservative default.
    """
    a = parse_hex(hex_a)
    b = parse_hex(hex_b)
    if a is None or b is None:
        return 1.0
    la = relative_luminance(a)
    lb = relative_luminance(b)
    lighter = max(la, lb)
    darker = min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def saturation(rgb: tuple[int, int, int]) -> float:
    """HSL saturation on ``[0.0, 1.0]``.

    Grey colors (equal r=g=b) return ``0.0``. Pure primary colors
    (``#FF0000``, ``#00FF00``, ``#0000FF``) return ``1.0``. Midtones
    of a single hue return ``1.0`` too — HSL saturation is agnostic to
    lightness, so a deep navy and a pastel blue both read "saturated"
    if their component spread is wide relative to their midpoint.
    """
    r, g, b = (c / 255.0 for c in rgb)
    hi = max(r, g, b)
    lo = min(r, g, b)
    if hi == lo:
        return 0.0
    delta = hi - lo
    lightness = (hi + lo) / 2.0
    if lightness <= 0.5:
        return delta / (hi + lo)
    return delta / (2.0 - hi - lo)


# --------------------------------------------------------------------- #
# Tone → saturation cap
# --------------------------------------------------------------------- #

# Register adjectives that call for restrained, low-saturation palettes.
# A "calm" or "clinical" brief should never sport a neon accent — the
# saturation cap is what enforces that on LLM-proposed hexes.
_CALM_REGISTERS: frozenset[str] = frozenset({
    "calm", "warm", "soft", "professional", "clinical",
    "restrained", "quiet", "grounded", "editorial", "considered",
})

# Register adjectives that permit loud, high-saturation palettes.
_BOLD_REGISTERS: frozenset[str] = frozenset({
    "bold", "playful", "energetic", "vibrant", "loud", "electric",
    "confident",
})

_CALM_CAP = 0.55
_BOLD_CAP = 0.95
_DEFAULT_CAP = 0.75


def _normalize_register_tokens(register: object) -> list[str]:
    """Coerce a brief.identity.register value to lowercase adjective list."""
    if register is None:
        return []
    if isinstance(register, str):
        return [register.strip().lower()] if register.strip() else []
    if isinstance(register, (list, tuple, set)):
        out: list[str] = []
        for v in register:
            if isinstance(v, str) and v.strip():
                out.append(v.strip().lower())
        return out
    return []


def saturation_cap_for_register(register: object) -> float:
    """Return the per-tone saturation cap on ``[0, 1]``.

    Rules (register wins if any token matches the corresponding bucket):

      * calm / warm / soft / professional / clinical → 0.55
      * bold / playful / energetic → 0.95
      * anything else / no register → 0.75

    The bold set wins ties — an app tagged both ``["calm", "playful"]``
    reads more playful than calm in practice; letting the tighter cap
    win would kill the playful cue.
    """
    tokens = _normalize_register_tokens(register)
    if not tokens:
        return _DEFAULT_CAP
    hits_bold = any(t in _BOLD_REGISTERS for t in tokens)
    hits_calm = any(t in _CALM_REGISTERS for t in tokens)
    if hits_bold:
        return _BOLD_CAP
    if hits_calm:
        return _CALM_CAP
    return _DEFAULT_CAP

"""Spec E Wave 2 — high-contrast palette derivation.

Emits a WCAG-AAA (≥ 7:1 fg/bg contrast) variant of the app's palette
under a ``[data-theme="high-contrast"]`` selector. The variant is
appended to the generated app's ``globals.css`` by
``interactions_css_inject.inject_polish_stylesheets`` (flag-gated,
``FORGE_POLISH_HIGH_CONTRAST``) or built ad-hoc for a specific brief.

Two public entry points:

* ``derive_high_contrast(palette)`` — pure math. Takes
  ``{brand, accent, ink, canvas}`` (all hex) and returns a matching
  dict where every fg-vs-canvas pair meets 7:1 contrast.

* ``build_high_contrast_css(palette=None)`` — renders the derived
  palette to a CSS block ready to inject. When ``palette`` is omitted
  the function uses a WCAG-safe monochromatic default (black on white
  / white on black) so the block is always emittable, even before
  brief-time palette derivation.

Contrast maths follows WCAG 2.1 relative-luminance rules exactly
(sRGB gamma decode → luminance → contrast ratio (L1+0.05)/(L2+0.05)).
No third-party colour library needed.
"""
from __future__ import annotations

import logging
from typing import Mapping

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WCAG contrast maths — sRGB → linear-light luminance
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(f"invalid hex colour: {hex_str!r}")
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    return (r, g, b)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def _srgb_to_linear(c: float) -> float:
    # WCAG 2.1 relative-luminance formula.
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_str: str) -> float:
    r, g, b = _hex_to_rgb(hex_str)
    rl = _srgb_to_linear(r)
    gl = _srgb_to_linear(g)
    bl = _srgb_to_linear(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG contrast ratio in [1, 21]."""
    l1 = relative_luminance(fg_hex)
    l2 = relative_luminance(bg_hex)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------------------
# Colour transforms — lighten / darken by stepping toward pure white / black
# ---------------------------------------------------------------------------


def _mix(a_hex: str, b_hex: str, t: float) -> str:
    """Linear mix in sRGB space; ``t=0`` returns a, ``t=1`` returns b."""
    ar, ag, ab = _hex_to_rgb(a_hex)
    br, bg, bb = _hex_to_rgb(b_hex)
    r = int(round(ar + (br - ar) * t))
    g = int(round(ag + (bg - ag) * t))
    b = int(round(ab + (bb - ab) * t))
    return _rgb_to_hex(r, g, b)


def _step_toward(colour: str, target: str, target_ratio: float, against: str) -> str:
    """Step ``colour`` toward ``target`` until ``contrast_ratio(colour,
    against) >= target_ratio``. Bounded to 20 steps (0.05 mix each) to
    guarantee termination; returns the last try even if it never hits
    target (caller inspects the ratio if it cares)."""
    best = colour
    for i in range(1, 21):
        t = i * 0.05
        cand = _mix(colour, target, t)
        if contrast_ratio(cand, against) >= target_ratio:
            return cand
        best = cand
    return best


# ---------------------------------------------------------------------------
# Public palette derivation
# ---------------------------------------------------------------------------

_DEFAULT_PALETTE: dict[str, str] = {
    "brand":  "#2563eb",
    "accent": "#7c3aed",
    "ink":    "#111827",
    "canvas": "#ffffff",
}


def derive_high_contrast(
    palette: Mapping[str, str] | None = None,
    *,
    target_ratio: float = 7.0,
) -> dict[str, str]:
    """Return a WCAG-AAA-contrast variant of ``palette``.

    Guarantees ``contrast_ratio(out['ink'], out['canvas']) >= target_ratio``
    and the same for ``brand``/``accent`` against the canvas. Never
    raises — falls back to black-on-white when the input is unusable.
    """
    src: dict[str, str] = dict(_DEFAULT_PALETTE)
    if palette:
        for key, val in palette.items():
            if isinstance(val, str) and val.strip():
                try:
                    _hex_to_rgb(val)
                    src[key] = val
                except ValueError:
                    pass

    canvas = src["canvas"]
    # Determine whether the canvas is "light" or "dark" — steer text
    # colours toward the opposite pole to gain contrast.
    canvas_lum = relative_luminance(canvas)
    dark_bg = canvas_lum < 0.5
    text_pole = "#ffffff" if dark_bg else "#000000"

    # Bump canvas toward pure white/black to gain the extra headroom
    # we'll need against the tinted foregrounds.
    canvas_out = canvas
    if dark_bg and canvas_lum > 0.02:
        canvas_out = _mix(canvas, "#000000", 0.6)
    elif not dark_bg and canvas_lum < 0.98:
        canvas_out = _mix(canvas, "#ffffff", 0.6)

    def _push(fg: str) -> str:
        # Push each foreground toward the opposite pole until it clears
        # 7:1 against the (possibly-adjusted) canvas.
        return (
            fg
            if contrast_ratio(fg, canvas_out) >= target_ratio
            else _step_toward(fg, text_pole, target_ratio, canvas_out)
        )

    return {
        "brand":  _push(src["brand"]),
        "accent": _push(src["accent"]),
        "ink":    _push(src["ink"]),
        "canvas": canvas_out,
    }


# ---------------------------------------------------------------------------
# CSS emission
# ---------------------------------------------------------------------------


def build_high_contrast_css(
    palette: Mapping[str, str] | None = None,
    *,
    target_ratio: float = 7.0,
) -> str:
    """Render a ``[data-theme="high-contrast"]`` CSS block.

    Idempotent + deterministic — the same input always produces the
    same bytes. Safe to call at any time (no palette → uses a
    black-on-white default so the block is always emittable).
    """
    variant = derive_high_contrast(palette, target_ratio=target_ratio)
    return (
        '[data-theme="high-contrast"] {\n'
        f'  --color-brand: {variant["brand"]};\n'
        f'  --color-primary: {variant["brand"]};\n'
        f'  --color-accent: {variant["accent"]};\n'
        f'  --color-foreground: {variant["ink"]};\n'
        f'  --color-ink: {variant["ink"]};\n'
        f'  --color-background: {variant["canvas"]};\n'
        f'  --color-canvas: {variant["canvas"]};\n'
        # Force the focus ring to the max-contrast text colour so it\n'
        # remains visible against the high-contrast canvas.\n'
        f'  --focus-ring-color: {variant["ink"]};\n'
        '  --focus-ring-width: 3px;\n'
        '  --focus-ring-offset: 3px;\n'
        '}\n'
    )


__all__ = [
    "derive_high_contrast",
    "build_high_contrast_css",
    "contrast_ratio",
    "relative_luminance",
]

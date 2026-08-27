"""Derive a complete UI palette from a single primary color.

Strategy:
- Primary: as given
- Secondary: provided hint OR derived as a hue ~150° complementary
- Accent: ~30° analogous to primary
- Background: near-white with primary's hue at very low saturation
- Surface: pure white
- Text-primary: near-black (always, for AA contrast)
- Text-secondary: 40% of black
- Border: 90% lightness of primary's hue
- Status: success (green), warning (amber), error (red) — fixed conventional values
"""
from __future__ import annotations
from dataclasses import dataclass
import colorsys


@dataclass(frozen=True)
class DerivedPalette:
    primary: str
    secondary: str
    accent: str
    background: str
    surface: str
    text_primary: str
    text_secondary: str
    border: str
    success: str
    warning: str
    error: str


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return _rgb_to_hex((r * 255, g * 255, b * 255))


def _hex_to_hsl(hex_str: str) -> tuple[float, float, float]:
    r, g, b = _hex_to_rgb(hex_str)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return h, s, l


def derive_palette(primary: str, secondary_hint: str | None = None) -> DerivedPalette:
    h, s, l = _hex_to_hsl(primary)

    secondary = (
        secondary_hint
        if secondary_hint
        else _hsl_to_hex((h + 0.5) % 1.0, min(s, 0.6), max(0.35, min(l, 0.55)))
    )

    accent = _hsl_to_hex((h + (30 / 360)) % 1.0, min(s, 0.55), max(0.45, min(l, 0.6)))
    background = _hsl_to_hex(h, min(s, 0.08), 0.98)
    surface = "#FFFFFF"
    text_primary = "#0F172A"
    text_secondary = "#475569"
    border = _hsl_to_hex(h, min(s, 0.15), 0.88)
    success = "#22C55E"
    warning = "#F59E0B"
    error = "#EF4444"

    return DerivedPalette(
        primary=primary.upper(),
        secondary=secondary.upper(),
        accent=accent.upper(),
        background=background.upper(),
        surface=surface,
        text_primary=text_primary,
        text_secondary=text_secondary,
        border=border.upper(),
        success=success,
        warning=warning,
        error=error,
    )


# Target lightness for each scale step. Calibrated to match Tailwind's
# default palette feel — 50 is near-white, 950 is near-black, 500 anchors
# to the input hex's lightness.
_SCALE_LIGHTNESS = {
    "50":  0.97, "100": 0.93, "200": 0.85, "300": 0.74, "400": 0.58,
    # "500" intentionally absent — preserved from input
    "600": 0.36, "700": 0.28, "800": 0.21, "900": 0.15, "950": 0.07,
}


def derive_scale(primary_hex: str) -> dict[str, str]:
    """Return a Tailwind-style 11-step colour scale from a single primary hex.

    The input is anchored at the 500 step. Other steps share hue + saturation
    and shift lightness to the targets in `_SCALE_LIGHTNESS`. Neutral inputs
    (very low saturation) produce a grey ramp without colour cast.
    """
    h, s, _l = _hex_to_hsl(primary_hex)
    out: dict[str, str] = {"500": primary_hex.lower()}
    # Preserve neutrality — if input is barely saturated, keep it that way.
    sat = s
    for key, target_l in _SCALE_LIGHTNESS.items():
        out[key] = _hsl_to_hex(h, sat, target_l)
    return out

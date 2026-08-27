"""Spec C9 — Deterministic monogram logo generator.

Emits a minimal SVG monogram (first letter of the app name inside a
geometric container tinted from ``brief.palette.brand`` and shaped by
``brief.layout.radius``). Same brief in → same SVG out, byte-for-byte.

No generative art, no LLM in the loop. This is a functional favicon /
initial mark that every generated app can adopt when it doesn't have
an authored logo — better than nothing, unmistakably branded.

The output ships as:
  - ``public/logo.svg``          (default 64×64 mark)
  - ``public/logo-large.svg``    (256×256 for splash/hero use)
  - ``public/favicon.svg``       (16×16 optimized for tab)
  - ``public/apple-touch-icon.svg`` (rounded-square, 180×180)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _first_alnum_upper(name: str) -> str:
    for ch in name or "":
        if ch.isalnum():
            return ch.upper()
    return "?"


def _normalize_hex(hex_color: str, fallback: str = "#111827") -> str:
    """Return #RRGGBB uppercase. Fallback if malformed."""
    if not isinstance(hex_color, str):
        return fallback
    v = hex_color.strip().lstrip("#")
    if len(v) == 3 and all(c in "0123456789abcdefABCDEF" for c in v):
        v = "".join(c * 2 for c in v)
    if len(v) == 6 and all(c in "0123456789abcdefABCDEF" for c in v):
        return "#" + v.upper()
    return fallback


def _readable_text_color(bg_hex: str) -> str:
    """Return #000000 or #FFFFFF whichever contrasts better with ``bg_hex``.

    Uses per-channel relative-luminance thresholding — same rule shadcn
    ships. Ensures the monogram letter is always legible."""
    h = _normalize_hex(bg_hex)
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    # WCAG relative luminance approximation.
    def _chan(c: int) -> float:
        c1 = c / 255.0
        return c1 / 12.92 if c1 <= 0.03928 else ((c1 + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * _chan(r) + 0.7152 * _chan(g) + 0.0722 * _chan(b)
    return "#FFFFFF" if lum < 0.5 else "#111827"


def _radius_for_size(size: int, radius_kind: str) -> int:
    """Return the corner radius in px for a size-x-size mark.

    ``radius_kind`` comes from ``brief.layout.radius`` — sharp_2 / soft_8 / pill.
    """
    r = (radius_kind or "").strip().lower()
    if r == "sharp_2":
        return max(2, size // 32)
    if r == "pill":
        return size // 2  # full round
    # soft_8 (default) or unknown
    return max(6, size // 8)


# ────────────────────────────────────────────────────────────
# SVG rendering
# ────────────────────────────────────────────────────────────

def render_monogram_svg(
    letter: str,
    *,
    brand_hex: str,
    size: int = 64,
    radius_px: int | None = None,
    include_xml_decl: bool = False,
) -> str:
    """Return the SVG source for a monogram.

    Deterministic — same inputs produce the same string every time.
    ``letter`` is not normalized; caller decides case. ``radius_px``
    defaults to ``size / 8`` when None (soft_8-ish).
    """
    r = radius_px if radius_px is not None else max(6, size // 8)
    bg = _normalize_hex(brand_hex)
    fg = _readable_text_color(bg)
    # Font size scales with the container; 60% of side is a legible
    # monogram sweet spot for one letter.
    font_size = int(size * 0.58)
    # Anchor text at the geometric centre. dy=0.34em nudges it down
    # to visually centre (font metrics push the baseline slightly high).
    xml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" if include_xml_decl else ""
    return (
        f"{xml}<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 {size} {size}\" "
        f"width=\"{size}\" height=\"{size}\" role=\"img\" aria-label=\"{letter}\">"
        f"<rect width=\"{size}\" height=\"{size}\" rx=\"{r}\" ry=\"{r}\" fill=\"{bg}\"/>"
        f"<text x=\"50%\" y=\"50%\" dy=\"0.34em\" text-anchor=\"middle\" "
        f"font-family=\"system-ui, -apple-system, Segoe UI, Roboto, sans-serif\" "
        f"font-weight=\"700\" font-size=\"{font_size}\" fill=\"{fg}\" "
        f"letter-spacing=\"-0.02em\">{letter}</text></svg>"
    )


# ────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────

def generate_logo_set(
    output_dir: str,
    *,
    app_name: str,
    brand_hex: str,
    radius_kind: str = "soft_8",
) -> dict:
    """Write the full monogram SVG set into ``output_dir/public/``.

    Args:
        output_dir: generated app root (``public/`` is created).
        app_name: display name — first alphanumeric letter becomes the monogram.
        brand_hex: e.g. ``brief.palette.brand``.
        radius_kind: sharp_2 | soft_8 | pill (from ``brief.layout.radius``).

    Returns ``{files, letter, brand, radius_kind}``.
    Safe when ``public/`` doesn't exist — creates it. Overwrites any
    existing SVGs (deterministic content, so re-runs are idempotent
    in output even though the mtime updates).
    """
    root = Path(output_dir)
    pub = root / "public"
    try:
        pub.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[logo] mkdir failed for %s: %s", pub, exc)
        return {"files": 0, "letter": "", "brand": "", "radius_kind": radius_kind}

    letter = _first_alnum_upper(app_name)
    brand = _normalize_hex(brand_hex)

    outputs = (
        # (filename, size, corner-radius override)
        ("logo.svg",            64,   _radius_for_size(64, radius_kind)),
        ("logo-large.svg",      256,  _radius_for_size(256, radius_kind)),
        ("favicon.svg",         16,   _radius_for_size(16, radius_kind)),
        # Apple touch icon uses squircle-ish rounded square (~22% of side).
        ("apple-touch-icon.svg", 180, max(20, int(180 * 0.22))),
    )

    written = 0
    for filename, size, radius_px in outputs:
        svg = render_monogram_svg(
            letter, brand_hex=brand, size=size, radius_px=radius_px,
            include_xml_decl=True,
        )
        p = pub / filename
        try:
            p.write_text(svg, encoding="utf-8")
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[logo] write failed %s: %s", p, exc)

    return {
        "files": written, "letter": letter, "brand": brand,
        "radius_kind": radius_kind,
    }


__all__ = ["generate_logo_set", "render_monogram_svg"]

"""Deterministic mapper from ``DesignBrief`` to a design-spec dict.

Spec A Slice 1 (see ``docs/superpowers/specs/2026-08-07-brief-canonical.md``).

Purpose: the platform's *sole* design authority. Brief in → design-spec
out. No LLM, no disk I/O, pure function. Consumed by ``globals_writer``
(the CSS-emission side of the current design pipeline) so downstream
never sees the brief directly, only its compiled spec.

The output shape matches what ``design_agent`` produces today, so
downstream consumers don't need to change in Slice 1 — this module is
a drop-in replacement for the LLM call. Later slices delete
``design_agent`` and rewire.
"""
from __future__ import annotations

import logging

from schemas.design_brief import DesignBrief, Palette

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Color helpers
# --------------------------------------------------------------------------- #


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """`#RRGGBB` → `(r, g, b)` ints in 0..255. Raises ValueError on bad input."""
    v = hex_color.strip()
    if not (v.startswith("#") and len(v) == 7):
        raise ValueError(f"expected #RRGGBB hex, got {hex_color!r}")
    try:
        r, g, b = int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16)
    except ValueError as exc:
        raise ValueError(f"invalid hex digits in {hex_color!r}") from exc
    return r, g, b


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """`(r, g, b)` ints → `#RRGGBB` uppercase. Clamps to 0..255."""
    r = max(0, min(255, int(round(r))))
    g = max(0, min(255, int(round(g))))
    b = max(0, min(255, int(round(b))))
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """RGB (0..255) → HSL (h 0..360, s 0..1, l 0..1)."""
    rn, gn, bn = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(rn, gn, bn), min(rn, gn, bn)
    l = (mx + mn) / 2.0
    d = mx - mn
    if d == 0:
        return 0.0, 0.0, l
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == rn:
        h = ((gn - bn) / d + (6.0 if gn < bn else 0.0)) * 60.0
    elif mx == gn:
        h = ((bn - rn) / d + 2.0) * 60.0
    else:
        h = ((rn - gn) / d + 4.0) * 60.0
    return h, s, l


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    """HSL (h 0..360, s 0..1, l 0..1) → RGB (0..255)."""
    if s == 0:
        v = int(round(l * 255))
        return v, v, v
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    def _hue_to_rgb(t: float) -> float:
        t = t % 1.0
        if t < 1/6:
            return p + (q - p) * 6 * t
        if t < 1/2:
            return q
        if t < 2/3:
            return p + (q - p) * (2/3 - t) * 6
        return p
    hn = h / 360.0
    r = _hue_to_rgb(hn + 1/3)
    g = _hue_to_rgb(hn)
    b = _hue_to_rgb(hn - 1/3)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


# Per-stop lightness curve, expressed as (direction, t) where t is the
# fraction of the distance from the base lightness toward white (light)
# or black (dark). Using a base-relative curve rather than absolute
# targets guarantees monotonicity regardless of the base color's
# lightness — critical because brand colors range from dark navy
# (L≈0.37) to light amber (L≈0.55).
_SHADE_CURVE: dict[str, tuple[str, float]] = {
    "50":  ("light", 0.95),
    "100": ("light", 0.85),
    "200": ("light", 0.70),
    "300": ("light", 0.50),
    "400": ("light", 0.25),
    "500": ("base",  0.0),   # base hex preserved verbatim
    "600": ("dark",  0.20),
    "700": ("dark",  0.40),
    "800": ("dark",  0.60),
    "900": ("dark",  0.78),
    "950": ("dark",  0.90),
}


def _shade_scale(base_hex: str) -> dict[str, str]:
    """Produce a Tailwind-style 50..950 shade dict from a base color.

    The base hex is preserved verbatim at the ``"500"`` stop (matters for
    Figma round-trip fidelity). Other stops shift lightness toward white
    (for 50..400) or black (for 600..950), keeping hue and saturation
    intact. Base-relative interpolation guarantees monotonicity for any
    base — a dark-navy brand still shades correctly.
    """
    r, g, b = _hex_to_rgb(base_hex)
    h, s, base_l = _rgb_to_hsl(r, g, b)
    out: dict[str, str] = {}
    for stop, (direction, t) in _SHADE_CURVE.items():
        if direction == "base":
            out[stop] = base_hex.upper()
            continue
        if direction == "light":
            target_l = base_l + (1.0 - base_l) * t
        else:  # dark
            target_l = base_l * (1.0 - t)
        rr, gg, bb = _hsl_to_rgb(h, s, target_l)
        out[stop] = _rgb_to_hex(rr, gg, bb)
    return out


# Tint hue biases applied when deriving neutrals. These are subtle — a
# "cool" neutral shouldn't read as blue, it should read as *grey with a
# whisper of blue*. Values chosen for visible-but-quiet effect.
_TINT_HUES = {
    "warm":    30.0,   # orange-ish
    "cool":    220.0,  # blue-ish
    "neutral": 0.0,    # unused (saturation goes to 0)
}
_TINT_SATURATION = 0.05  # 5% — subtle


# Absolute lightness targets for the neutral scale. Neutrals build a
# family from scratch (not a variant of some base color), so a fixed
# lightness ladder is correct — the family reads coherently 50→950.
_NEUTRAL_L: dict[str, float] = {
    "50":  0.97, "100": 0.93, "200": 0.85, "300": 0.75, "400": 0.62,
    "500": 0.50, "600": 0.42, "700": 0.34, "800": 0.26, "900": 0.18,
    "950": 0.10,
}


def _derive_neutrals(palette: Palette) -> dict[str, str]:
    """Neutral shade scale that respects ``palette.neutrals_tint``.

    Neutrals aren't a variant of the brand color — they're a family
    (background chrome, borders, text). A ``cool`` neutral scale is grey
    with a whisper of blue at every stop; ``warm`` shifts every stop
    toward orange; ``neutral`` is pure grey.
    """
    tint = palette.neutrals_tint.value if hasattr(palette.neutrals_tint, "value") else palette.neutrals_tint
    hue = _TINT_HUES.get(tint, 0.0)
    sat = 0.0 if tint == "neutral" else _TINT_SATURATION
    out: dict[str, str] = {}
    for stop, target_l in _NEUTRAL_L.items():
        rr, gg, bb = _hsl_to_rgb(hue, sat, target_l)
        out[stop] = _rgb_to_hex(rr, gg, bb)
    return out


# Semantic colors are universal (green=success, amber=warning, red=error,
# blue=info) — these are cross-domain HTML/CSS conventions, not per-domain
# intelligence, so a small fixed palette is correct. If a future spec wants
# brief-authored semantic colors, that's a schema extension, not a
# per-industry catalog.
_SEMANTIC_COLORS = {
    "success": "#10B981",  # emerald-500
    "warning": "#F59E0B",  # amber-500
    "error":   "#EF4444",  # red-500
    "info":    "#3B82F6",  # blue-500
}


def _default_semantic_colors() -> dict[str, str]:
    """Universal semantic colors (success / warning / error / info)."""
    return dict(_SEMANTIC_COLORS)


# --------------------------------------------------------------------------- #
# Typography helpers
# --------------------------------------------------------------------------- #


def _parse_scale_ratio(scale_str: str) -> float:
    """Extract the numeric ratio from a name like ``"conservative_1.20"``.

    Falls back to 1.25 (major third — a safe conservative default) when
    the string has no parseable ratio. This isn't a per-name lookup — it's
    parsing the number the LLM chose.
    """
    # Find the last underscore-separated segment and try to parse it as a float.
    if "_" not in scale_str:
        return 1.25
    tail = scale_str.rsplit("_", 1)[1]
    try:
        ratio = float(tail)
    except ValueError:
        return 1.25
    # Reject nonsense values that would produce unreadable type.
    if not (1.05 <= ratio <= 2.0):
        return 1.25
    return ratio


def _resolve_scale(scale_str: str) -> dict[str, str]:
    """Type scale as ``{"caption","body","h3","h2","h1"}`` in rem strings.

    body anchors at 1rem. caption steps down one, headings step up.
    """
    ratio = _parse_scale_ratio(scale_str)
    body_rem = 1.0
    return {
        "caption": f"{round(body_rem / ratio, 4):g}rem",
        "body":    f"{body_rem:g}rem",
        "h3":      f"{round(body_rem * ratio, 4):g}rem",
        "h2":      f"{round(body_rem * ratio ** 2, 4):g}rem",
        "h1":      f"{round(body_rem * ratio ** 3, 4):g}rem",
    }


# --------------------------------------------------------------------------- #
# Layout helpers
# --------------------------------------------------------------------------- #


# Radius scale per brief.layout.radius. The enum vocabulary is small on
# purpose (sharp / soft / pill are semantically distinct), but each named
# value expands to sm/md/lg because different surfaces read best at
# different corner treatments — a Card and a Button in the same app use
# different sizes even at the same "sharp" intent.
_RADIUS_MAP = {
    "sharp_2": {"sm": 2,   "md": 2,   "lg": 4},
    "soft_8":  {"sm": 4,   "md": 8,   "lg": 12},
    "pill":    {"sm": 4,   "md": 999, "lg": 999},
}


def _radius_scale(radius) -> dict[str, int]:
    """Map ``brief.layout.radius`` to per-size px values."""
    key = radius.value if hasattr(radius, "value") else radius
    return dict(_RADIUS_MAP.get(key, _RADIUS_MAP["soft_8"]))


# ── Spec D Wave 4 — snap-to-nearest helpers ─────────────────────────
#
# Brief author (with Wave 4 flag on) emits continuous numeric values
# (radius_px, density_pt) alongside the enum buckets. These helpers
# take the numeric intent and produce the same {sm, md, lg} dicts the
# renderers already consume — so we honor the LLM's semantic authoring
# without discarding the renderer's actual token vocabulary.

def snap_radius_px(px: int | None) -> str | None:
    """Snap a raw radius_px value to the nearest Radius enum key.

    Returns None when input is None so callers can fall back to the
    existing enum-based path. Bounded ranges:
      0..3   → sharp_2
      4..15  → soft_8
      16+    → pill
    """
    if px is None:
        return None
    try:
        p = int(px)
    except (TypeError, ValueError):
        return None
    if p < 0:
        return "sharp_2"
    if p <= 3:
        return "sharp_2"
    if p <= 15:
        return "soft_8"
    return "pill"


def radius_scale_from_px(px: int) -> dict[str, int]:
    """Compute a full sm/md/lg scale from a single px anchor.

    md is the anchor; sm is smaller; lg is larger. For the pill case
    (px >= 16), the shape reads as "fully rounded" so md/lg both go to 999.
    """
    if px >= 16:
        return {"sm": max(4, px // 4), "md": 999, "lg": 999}
    return {
        "sm": max(1, px // 2),
        "md": max(1, px),
        "lg": max(1, int(px * 1.5)),
    }


# Layout output helpers — prefer brief_to_design_spec Wave 4 numeric
# authoring (radius_px, density_pt) when present; fall back to the
# enum-based paths otherwise. Both paths produce identical shapes so
# downstream consumers don't need to branch.

def _layout_output(l) -> dict:
    """Return layout.{density, radius, grid} respecting Wave 4 numerics."""
    px = getattr(l, "radius_px", None)
    if isinstance(px, int):
        radius = radius_scale_from_px(px)
    else:
        radius = _radius_scale(l.radius)
    density = l.density.value if hasattr(l.density, "value") else l.density
    return {"density": density, "radius": radius, "grid": l.grid}


def _border_radius_output(l) -> dict:
    """Legacy top-level borderRadius: same source of truth as _layout_output.radius."""
    px = getattr(l, "radius_px", None)
    if isinstance(px, int):
        scale = radius_scale_from_px(px)
    else:
        scale = _radius_scale(l.radius)
    return {
        "sm": f"{scale['sm']}px",
        "md": f"{scale['md']}px",
        "lg": f"{scale['lg']}px",
    }


# Density snap: pt (spacing unit) → the enum vocabulary. Compact
# clusters at 2..5pt; comfortable at 6..10; spacious at 11..16;
# spacious_for_touch at 17+.
def snap_density_pt(pt: int | None) -> str | None:
    if pt is None:
        return None
    try:
        p = int(pt)
    except (TypeError, ValueError):
        return None
    if p <= 5:
        return "compact"
    if p <= 10:
        return "comfortable"
    if p <= 16:
        return "spacious"
    return "spacious_for_touch"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def brief_to_design_spec(brief: DesignBrief) -> dict:
    """Deterministic mapping ``DesignBrief`` → design-spec dict.

    Output shape matches what ``agents.design_agent`` produces today so
    downstream consumers (``shell_templates.extract_tokens``,
    ``agents.design_agent._rewrite_globals_root``, ``save_design_spec``)
    work unchanged. Legacy consumers expect FLAT hex keys at
    ``colorPalette`` root (``primary``, ``accent``, ``sidebarBg``, etc.);
    shade scales live under ``colorPalette._scales`` for future
    consumers that want the full ladder.

    Pure function: same brief in → same dict out, byte-for-byte.
    """
    p = brief.palette
    t = brief.typography
    l = brief.layout
    modes = {m.value if hasattr(m, "value") else m for m in brief.identity.modes}

    # Slice A (2026-08-13) — VisualLock override.
    # When the brief carries a populated visual_lock, its hex/font values
    # are the source of truth and downstream re-derivation is bypassed.
    # We resolve the effective colors + font families up front, then let
    # the shade/typography scale helpers operate on the resolved values.
    lock = getattr(brief, "visual_lock", None)
    lock_active = bool(lock and lock.is_active())
    if lock_active:
        lp = lock.palette
        # Prefer lock values; fall back to brief palette per-key so a
        # partial lock never leaves the app with holes. The lock's
        # `accent` becomes BOTH primary and accent hue for
        # monochromatic presets — brief_to_design_spec's `brand` slot
        # is the primary CTA colour; `accent` is the badge/highlight,
        # which the lock exposes as `badge`.
        brand_hex   = lp.get("accent", p.brand)
        accent_hex  = lp.get("badge",  p.accent)
        bg_hex      = lp.get("bg",     p.surface_bg)
        surface_hex = lp.get("subtle", p.surface_elevated)
        fg_hex      = lp.get("fg",     p.foreground_primary)
        muted_hex   = lp.get("muted",  p.foreground_muted)
        semantic = _default_semantic_colors()
        # Semantic overrides — the lock exposes danger/success verbatim.
        if lp.get("danger"):
            semantic["error"] = lp["danger"]
        if lp.get("success"):
            semantic["success"] = lp["success"]
        logger.info("[visual-lock] applied preset=%s", getattr(lock, "preset_name", "?"))
    else:
        brand_hex   = p.brand
        accent_hex  = p.accent
        bg_hex      = p.surface_bg
        surface_hex = p.surface_elevated
        fg_hex      = p.foreground_primary
        muted_hex   = p.foreground_muted
        semantic = _default_semantic_colors()

    brand_scale = _shade_scale(brand_hex)
    accent_scale = _shade_scale(accent_hex)
    neutral_scale = _derive_neutrals(p)

    # Flat legacy keys — what shell_templates + globals_writer + save_design_spec expect.
    # Sidebar tokens derived from the brand so the app's chrome carries the brief's
    # brand hue (was falling back to hardcoded #1A2940 near-black otherwise).
    color_palette: dict = {
        # Brand + accent + neutrals — pulled straight from the brief
        # (or the visual_lock override when active).
        "primary":       brand_hex,
        "accent":        accent_hex,
        "background":    bg_hex,
        "surface":       surface_hex,
        "border":        neutral_scale["200"],
        "muted":         muted_hex,
        "textPrimary":   fg_hex,
        "textSecondary": muted_hex,
        # Sidebar chrome — dark variant of brand so the sidebar reads as
        # a coherent extension of the brand palette instead of a stock dark navy.
        "sidebarBg":     brand_scale["900"],
        "sidebarText":   "#FFFFFF",
        # Semantic — universal green/amber/red/blue cross-domain conventions.
        **semantic,
        # Shade scales for future consumers that want the full ladder.
        "_scales": {
            "brand":   brand_scale,
            "accent":  accent_scale,
            "neutral": neutral_scale,
        },
    }

    # Resolve font families with visual_lock overrides.
    if lock_active:
        _lt = lock.typography
        display_family = _lt.get("display", t.display_family) or t.display_family
        body_family    = _lt.get("body",    t.body_family)    or t.body_family
        # utility_family: prefer lock.mono when present, else the brief.
        utility_family = _lt.get("mono", t.utility_family)
    else:
        display_family = t.display_family
        body_family    = t.body_family
        utility_family = t.utility_family

    return {
        "colorPalette": color_palette,
        "typography": {
            "display": {
                "family":  display_family,
                "weights": list(t.display_weights),
            },
            "body": {
                "family":  body_family,
                "weights": list(t.body_weights),
            },
            "utility": {
                "family":  utility_family,
            },
            "scale": _resolve_scale(t.scale),
            # Legacy flat keys for consumers (design_agent._register_from_spec_fonts,
            # _rewrite_globals_root typography injection) that read families this way.
            "fontFamily":        body_family,
            "headingFontFamily": display_family,
            "bodyWeight":        t.body_weights[0] if t.body_weights else 400,
            "headingWeight":     t.display_weights[-1] if t.display_weights else 700,
        },
        "layout": _layout_output(l),
        # Legacy top-level borderRadius — _rewrite_globals_root reads this to set --radius.
        "borderRadius": _border_radius_output(l),
        "modes": {
            "light": "light" in modes,
            "dark":  "dark" in modes,
        },
        # Spec C4 — motion tokens. Values come verbatim from the brief so
        # the LLM's per-domain choice (formal-technical vs playful-consumer)
        # reaches CSS as concrete numbers instead of an enum bucket.
        "motion": {
            "durationFastMs":   brief.motion.duration_fast_ms,
            "durationMediumMs": brief.motion.duration_medium_ms,
            "durationSlowMs":   brief.motion.duration_slow_ms,
            "easeOut":          brief.motion.ease_out,
            "easeInOut":        brief.motion.ease_in_out,
            "reduceMotionRespect": brief.motion.reduce_motion_respect,
        },
        # Spec C8 — responsive priority. Shell composers respect
        # primary_form_factor + layout_variants; unknown layout_variants
        # get rejected by the shell composer before code is emitted.
        "responsive": {
            "primaryFormFactor":   brief.responsive.primary_form_factor,
            "breakpointsPriority": list(brief.responsive.breakpoints_priority),
            "layoutVariants":      list(brief.responsive.layout_variants),
        },
        # Spec D Wave 3 — cta_hierarchy (brief-authored). When absent,
        # downstream readers fall back to cta_defaults.defaults_for_register.
        # When present, flows into design_spec so schema_prompt.py's
        # `design_spec.get("cta_hierarchy") or defaults_for_register(...)`
        # pattern picks up the brief-authored version verbatim.
        **({"cta_hierarchy": {
            "primary":   brief.cta_hierarchy.primary.model_dump(),
            "secondary": brief.cta_hierarchy.secondary.model_dump(),
            "tertiary":  brief.cta_hierarchy.tertiary.model_dump(),
        }} if brief.cta_hierarchy is not None else {}),
    }


__all__ = [
    "brief_to_design_spec",
]

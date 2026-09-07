"""design_compiler — transforms the planner's design-spec.json into a
project-specific tokens.custom.json for the runtime to consume.

This module currently exposes only the color-ramp helper. The full
field-mapping orchestration lands in Tasks 23-24.

The ramp generator scales an anchor color's lightness along Tailwind v3's
standard 11-stop curve, preserving hue + saturation. Designers familiar
with Tailwind get predictable output; LLM-generated palettes don't drift
into illegible contrast extremes.
"""
from __future__ import annotations

import colorsys
import re

# Tailwind v3 lightness curve. Stops 50–400 use absolute lightness values;
# stops 600–950 are computed as multipliers of the anchor's lightness so
# bright/dark anchors don't lose their identity at the dark end.
_LIGHT_STOPS = {
    "50":  0.97,
    "100": 0.93,
    "200": 0.87,
    "300": 0.78,
    "400": 0.68,
}
_DARK_MULTIPLIERS = {
    "600": 0.87,
    "700": 0.73,
    "800": 0.60,
    "900": 0.47,
    "950": 0.30,
}

_HEX_RE = re.compile(r"^#?([0-9a-f]{6})$", re.IGNORECASE)


def _hex_to_hsl(hex_str: str) -> tuple[float, float, float]:
    """Convert #rrggbb to (hue, saturation, lightness), each in 0..1.

    Raises ValueError on malformed input.
    """
    m = _HEX_RE.match(hex_str.strip())
    if not m:
        raise ValueError(f"Invalid hex color: {hex_str!r}")
    h_str = m.group(1)
    r = int(h_str[0:2], 16) / 255.0
    g = int(h_str[2:4], 16) / 255.0
    b = int(h_str[4:6], 16) / 255.0
    # colorsys.rgb_to_hls returns (h, l, s) — note HLS not HSL field order.
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert (hue, saturation, lightness) in 0..1 to #rrggbb."""
    # colorsys uses HLS (hue, lightness, saturation) — note the field order.
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#{:02x}{:02x}{:02x}".format(
        round(r * 255), round(g * 255), round(b * 255)
    )


def _triplet(h: float, s_pct: int, l_pct: int) -> str:
    """Format a CSS ``H S% L%`` channel triplet from hue-in-0..1 + int S/L %."""
    return f"{round(h * 360) % 360} {s_pct}% {l_pct}%"


def derive_structural_tokens(palette: dict | None) -> dict[str, str]:
    """Derive the neutral *structural* tokens (border, input, ring, muted,
    foreground, card/popover) from the palette's brand hue, as ``H S% L%``
    triplets ready for a light-theme ``:root``.

    Why: a generated app looks cohesive only when its greys are tinted toward the
    brand hue — a teal product wants faintly teal borders and text, not generic
    slate. The LLM authors these inconsistently (why editor≠app today), so we
    compute them deterministically from the palette instead. The brand hue comes
    from ``primary`` (falling back to ``accent``/``secondary``/``background``);
    an unusable palette falls back to a neutral slate so callers never crash.

    Slice A (2026-08-13) — when the palette carries an explicit
    ``background``/``surface``/``textPrimary``/``muted``/``border`` from a
    visual_lock, we snap ``--card``, ``--popover``, ``--foreground`` and
    friends to those hexes instead of the hue-tinted triplet. The lock's
    intent is a specific look; re-deriving under the hood re-introduces
    the drift the lock exists to prevent.
    """
    palette = palette or {}

    def _hsl_of(*keys: str) -> tuple[float, float, float] | None:
        for k in keys:
            v = palette.get(k)
            if isinstance(v, str) and v.strip().startswith("#"):
                try:
                    return _hex_to_hsl(v)
                except ValueError:
                    continue
        return None

    brand = _hsl_of("primary", "accent", "secondary", "background")
    # Neutral slate fallback hue (~215°) when no usable brand color is present.
    hue = brand[0] if brand else (215 / 360)
    # The focus ring keeps the primary's own saturation (clamped to a visible min).
    ring_sat = max(30, min(90, round((brand[1] if brand else 0.2) * 100)))

    # ── Accent hue ────────────────────────────────────────────────────
    # If the palette ships a distinct accent hex (Morning Mist:
    # terracotta; Studio Blush: sage), use it. Otherwise derive a
    # complementary hue (+150°) so buttons, tags, badges, active nav
    # dots don't all resolve to the same brand green. Without this every
    # single accent-tinted UI element is the primary color and the app
    # reads monotone.
    accent_hsl = _hsl_of("accent")
    if accent_hsl:
        a_hue, a_sat, a_l = accent_hsl
        accent_sat = max(35, min(85, round(a_sat * 100)))
        accent_l = max(38, min(62, round(a_l * 100)))
    else:
        # Complementary (analogue-triadic) rotation from the primary hue.
        # +150° lands in a warm/opposite band relative to most brand hues
        # (green → magenta-red, blue → orange, purple → yellow-green).
        a_hue = (hue + 150 / 360) % 1.0
        accent_sat = max(45, min(75, ring_sat))
        accent_l = 55
    accent_fg_l = 12 if accent_l >= 45 else 96  # dark accent → light fg, and vice-versa

    # ── Semantic tokens (success / warning / danger / info) ───────────
    # These are UX signals — universal meanings, NOT tinted primary. A
    # green primary previously made `--success` invisible against
    # background because both were sage; a red primary made
    # `--danger` merge with the brand.
    # Hues are hand-picked to read reliably against light backgrounds:
    # success 145° (grass), warning 38° (amber), danger 358° (crimson),
    # info 210° (azure).

    # Slice A — resolve lock overrides for structural-token slots the
    # palette already carries as hex. Falls back to the hue-tinted
    # triplet when the slot is not locked.
    def _hex_triplet_or(*keys: str, fallback: str) -> str:
        for k in keys:
            v = palette.get(k)
            if isinstance(v, str) and v.strip().startswith("#"):
                try:
                    h_, s_, l_ = _hex_to_hsl(v)
                    return _triplet(h_, round(s_ * 100), round(l_ * 100))
                except ValueError:
                    continue
        return fallback

    return {
        # Hairline chrome — brand-tinted borders. Bumped from 16%/88% to
        # 22%/82%: the previous value was ~95% Lab contrast against
        # `--card`=100%, near-invisible → cards read as flat rectangles.
        # Bumping saturation + darkening lightness gives real visual
        # separation without turning borders opaque.
        "--border": _hex_triplet_or("border",
            fallback=_triplet(hue, 22, 82)),
        "--input":  _hex_triplet_or("border",
            fallback=_triplet(hue, 22, 82)),
        # Muted surfaces + secondary text, same hue family. `--muted`
        # stays hue-derived — it's a *filled* muted row/surface, so
        # snapping to whatever the palette calls `surface` would make
        # cards and muted rows collapse to the same colour.
        "--muted": _triplet(hue, 14, 96),
        "--muted-foreground": _hex_triplet_or("muted", "textSecondary",
            fallback=_triplet(hue, 12, 44)),
        # Primary text — dark, brand-tinted (not pure black).
        "--foreground": _hex_triplet_or("textPrimary",
            fallback=_triplet(hue, 24, 16)),
        # Cards/popovers: white with the tint carried in their foreground.
        "--card": _hex_triplet_or("surface",
            fallback=_triplet(hue, 30, 100)),
        "--card-foreground": _hex_triplet_or("textPrimary",
            fallback=_triplet(hue, 24, 16)),
        "--popover": _hex_triplet_or("surface",
            fallback=_triplet(hue, 30, 100)),
        "--popover-foreground": _hex_triplet_or("textPrimary",
            fallback=_triplet(hue, 24, 16)),
        # Focus ring tracks the primary hue + saturation.
        "--ring": _triplet(hue, ring_sat, 62),
        # ── Accent (a distinct-hue counterpoint to primary) ──
        "--accent": _triplet(a_hue, accent_sat, accent_l),
        "--accent-foreground": _triplet(a_hue, min(accent_sat, 20), accent_fg_l),
        # ── Semantic (universal meanings, independent hues) ──
        "--success": _triplet(145 / 360, 55, 40),
        "--success-foreground": _triplet(145 / 360, 20, 98),
        "--warning": _triplet(38 / 360, 92, 50),
        "--warning-foreground": _triplet(38 / 360, 40, 14),
        "--destructive": _triplet(358 / 360, 72, 50),
        "--destructive-foreground": _triplet(358 / 360, 20, 98),
        "--info": _triplet(210 / 360, 82, 48),
        "--info-foreground": _triplet(210 / 360, 20, 98),
    }


def hsl_ramp(anchor_hex: str) -> dict[str, str]:
    """Generate an 11-stop color ramp from an anchor hex color.

    Args:
        anchor_hex: hex color (#rrggbb) that becomes stop 500.

    Returns:
        Dict keyed by stop label ("50", "100", ..., "950") to hex strings.

    Raises:
        ValueError if anchor_hex isn't a valid hex color.
    """
    h, s, l_anchor = _hex_to_hsl(anchor_hex)
    out: dict[str, str] = {}
    for stop, l in _LIGHT_STOPS.items():
        out[stop] = _hsl_to_hex(h, s, l)
    out["500"] = anchor_hex.lower() if anchor_hex.startswith("#") else f"#{anchor_hex.lower()}"
    for stop, mult in _DARK_MULTIPLIERS.items():
        out[stop] = _hsl_to_hex(h, s, l_anchor * mult)
    return out


# === Field mappers ===

def _map_color_palette(palette: dict) -> dict:
    """Convert design-spec.colorPalette into tokens.color sub-tree.

    Every value passes through ``extract_hex`` first, so an annotated color
    ("#C4611F — warm terracotta") still themes the app instead of silently
    deleting the ramp (the bug that shipped default-blue apps).
    """
    from services.css_sanitize import extract_hex

    out: dict = {}

    def _hex(key: str) -> str | None:
        return extract_hex(palette.get(key))

    # Primary/secondary/accent: full 11-stop ramps
    for key in ("primary", "secondary", "accent"):
        anchor = _hex(key)
        if anchor:
            try:
                out[key] = hsl_ramp(anchor)
            except ValueError:
                # Fall back to defaults silently — caller logs.
                pass

    # Synthesize secondary from primary too — same rationale, +30° hue
    # rotation gives an analogous colour that reads as related-but-different.
    if "secondary" not in out and "primary" in out:
        prim_hex = extract_hex(palette.get("primary")) or ""
        if prim_hex:
            try:
                ph, ps, pl = _hex_to_hsl(prim_hex)
                s_hue = ((ph * 360) + 30) % 360
                s_hex = _hsl_to_hex(s_hue / 360, ps, pl)
                out["secondary"] = hsl_ramp(s_hex)
            except (ValueError, TypeError):
                pass

    # Synthesize accent from primary when the palette didn't ship one.
    # Without this, chart series that call ``var(--color-accent-500)``
    # fall back to inherit or an implicit `currentColor`, so every
    # multi-series chart reads as one blob — worst-case monotone. The
    # complementary hue (+150° rotation) is opposite enough on the
    # colour wheel to read as a distinct swatch on any brand.
    if "accent" not in out and "primary" in out:
        prim_hex = extract_hex(palette.get("primary")) or ""
        if prim_hex:
            try:
                ph, ps, pl = _hex_to_hsl(prim_hex)
                a_hue = ((ph * 360) + 150) % 360
                # Keep saturation and lightness in the primary's neighbourhood
                # so the two hues feel like they belong to the same palette
                # rather than a random clash.
                a_hex = _hsl_to_hex(a_hue / 360, ps, pl)
                out["accent"] = hsl_ramp(a_hex)
            except (ValueError, TypeError):
                pass

    # Status colors: 3-stop ramps (50, 500, 700)
    for key in ("success", "warning", "error", "info"):
        anchor = _hex(key)
        if anchor:
            try:
                full = hsl_ramp(anchor)
                out[key] = {stop: full[stop] for stop in ("50", "500", "700")}
            except ValueError:
                pass

    # Surface levels
    surface = {}
    if _hex("background"):    surface["0"] = _hex("background")
    if _hex("surface"):       surface["1"] = _hex("surface")
    if _hex("surfaceHover"):  surface["2"] = _hex("surfaceHover")
    if surface:
        out["surface"] = surface

    # Border / muted (single-default groups)
    if _hex("border"):
        out["border"] = {"default": _hex("border")}
    if _hex("muted"):
        out["muted"] = {"default": _hex("muted")}

    # Text levels
    text = {}
    if _hex("textPrimary"):    text["primary"]    = _hex("textPrimary")
    if _hex("textSecondary"):  text["secondary"]  = _hex("textSecondary")
    if _hex("textTertiary"):   text["tertiary"]   = _hex("textTertiary")
    if text:
        out["text"] = text

    # Sidebar
    sidebar = {}
    if _hex("sidebarBg"):          sidebar["bg"]     = _hex("sidebarBg")
    if _hex("sidebarText"):        sidebar["text"]   = _hex("sidebarText")
    if _hex("sidebarActiveItem"):  sidebar["active"] = _hex("sidebarActiveItem")
    if sidebar:
        out["sidebar"] = sidebar

    return out


def _map_typography(typography: dict) -> dict:
    """Convert design-spec.typography into tokens.typography sub-tree.

    Every value is sanitized to machine CSS: font stacks are rebuilt from
    annotated strings ("Inter — excellent legibility"), scale entries map
    Tailwind classes ("text-3xl (30px) — page titles") to rem, line-height
    extracts the first number from prose. Invalid entries are DROPPED so the
    runtime's defaults (or the design-DNA merge-base) fill them.
    """
    from services.css_sanitize import (
        extract_css_length, extract_font_stack, extract_letter_spacing,
        extract_number, extract_weight,
    )

    out: dict = {}

    # Font family — split body/heading if planner provides both
    body_font = extract_font_stack(typography.get("fontFamily")) \
        or "Inter, system-ui, sans-serif"
    heading_font = extract_font_stack(typography.get("headingFontFamily")) \
        or body_font
    out["font"] = {"body": body_font, "heading": heading_font}

    # Weight
    out["weight"] = {
        "body": extract_weight(typography.get("bodyWeight")) or "400",
        "heading": extract_weight(typography.get("headingWeight")) or "600",
    }

    # Scale — sanitize each entry; drop hopeless ones (defaults fill them).
    scale_in = typography.get("scale") or {}
    scale_out: dict = {}
    if isinstance(scale_in, dict):
        for k, v in scale_in.items():
            clean = extract_css_length(v)
            if clean:
                scale_out[k] = clean
    out["scale"] = scale_out

    # Line height — extract the first sane number from possible prose.
    lh = extract_number(typography.get("lineHeight"), 1.0, 2.2) or 1.5
    lh_tight = extract_number(typography.get("headingLineHeight"), 0.9, 1.6) or 1.25
    out["lineHeight"] = {"tight": str(lh_tight), "normal": str(lh)}

    # Letter spacing
    ls = extract_letter_spacing(typography.get("letterSpacing")) or "0"
    ls_heading = extract_letter_spacing(typography.get("headingLetterSpacing")) or "-0.02em"
    out["letterSpacing"] = {"heading": ls_heading, "body": ls}

    # Numeric voice — MetricTile/Stat read typography.numeric for KPI values.
    # Without this group the tile falls back to inherit (and the un-guarded
    # legacy dist crashed outright). Family follows the body stack; tabular
    # figures on when the spec asks for them.
    out["numeric"] = {
        "family": extract_font_stack(typography.get("numericFontFamily")) or body_font,
        "tabular": bool(typography.get("tabularNumbers", True)),
    }

    return out


# Density multiplier table for spacing.
_DENSITY_MULTIPLIERS = {
    "compact": 0.75,
    "comfortable": 1.0,
    "spacious": 1.25,
}

# Default spacing scale in rem (matches defaultTokens 13-stop scale).
_DEFAULT_SPACING_REM = {
    "0":  0.0,
    "1":  0.25,
    "2":  0.5,
    "3":  0.75,
    "4":  1.0,
    "6":  1.5,
    "8":  2.0,
    "12": 3.0,
    "16": 4.0,
    "24": 6.0,
    "32": 8.0,
    "48": 12.0,
    "64": 16.0,
}


def _map_spacing(spacing: dict, density: str = "comfortable") -> dict:
    """Convert design-spec.spacing into tokens.spacing sub-tree.

    The numeric scale is hardcoded (the design-spec usually just describes
    the scale rather than enumerating it), and density is applied as a
    multiplier. Semantic aliases (page/card/section/element/input) are
    passed through verbatim.
    """
    multiplier = _DENSITY_MULTIPLIERS.get(density, 1.0)
    out: dict = {}

    # Numeric scale (multiplied by density)
    for stop, base_rem in _DEFAULT_SPACING_REM.items():
        out[stop] = f"{base_rem * multiplier}rem"

    # Semantic aliases — only when they sanitize to a real CSS length
    # (the LLM emits prose like "px-6 py-8 on desktop" here; dropping keeps
    # the runtime defaults instead of shipping invalid declarations).
    from services.css_sanitize import extract_css_length
    semantic = {}
    for spec_key, name in (("pagePadding", "page"), ("cardPadding", "card"),
                           ("sectionGap", "section"), ("elementGap", "element"),
                           ("inputGap", "input")):
        clean = extract_css_length(spacing.get(spec_key))
        if clean:
            semantic[name] = clean
    if semantic:
        out["semantic"] = semantic

    return out


# Corner-radius family per design register (mirrors packages/library registers).
_REGISTER_RADIUS_SCALE = {
    "workday": "sharp", "linear": "sharp",
    "stripe": "soft", "default": "soft",
    "notion": "round", "figma": "round",
}
# Numeric radius fallback (matches defaultTokens) so the Tailwind rounded-* scale
# never loses its values when the design-spec omits borderRadius.
_DEFAULT_RADIUS = {"sm": "0.25rem", "md": "0.5rem", "lg": "0.75rem", "xl": "1rem", "full": "9999px"}


def _resolve_radius_scale(design_spec: dict) -> str:
    """The corner-radius family ("sharp" | "soft" | "round") for the app.

    Honors an explicit design-spec override, else derives from the register.
    "sharp" is a REAL, honored choice now — the earlier floor-to-soft existed
    only to mask a merge bug (tokens.radius omitting `scale`), which is fixed:
    compile() always emits radius WITH its scale. Squared corners are a core
    part of several archetypes (fintech/dev-tools/logistics/legal) and of the
    premium look the platform previously shipped.
    """
    raw = (design_spec.get("radiusScale")
           or (design_spec.get("borderRadius") or {}).get("scale"))
    if raw in ("sharp", "soft", "round"):
        return raw
    return _REGISTER_RADIUS_SCALE.get((design_spec.get("register") or "").lower(), "soft")


def _map_radius(border_radius: dict, scale: str = "soft") -> dict:
    """design-spec.borderRadius → tokens.radius, always carrying the `scale`
    family. Every value is sanitized ("0.5rem (8px)" → "0.5rem"); invalid
    entries keep their defaults instead of shipping broken CSS."""
    from services.css_sanitize import extract_css_length

    out = dict(_DEFAULT_RADIUS)
    for k, v in (border_radius or {}).items():
        if k not in _DEFAULT_RADIUS:
            continue
        clean = extract_css_length(v)
        if clean:
            out[k] = clean
    out["scale"] = scale
    return out


def _map_shadow(shadows: dict) -> dict:
    """design-spec.shadows → tokens.shadow, each value validated as a real
    box-shadow (prose suffixes stripped; hopeless values dropped)."""
    from services.css_sanitize import extract_shadow

    out = {}
    for k, v in shadows.items():
        if k not in ("sm", "md", "lg", "xl"):
            continue
        clean = extract_shadow(v)
        if clean:
            out[k] = clean
    return out


def _map_motion(animation: dict) -> dict:
    """Convert design-spec.animation into tokens.motion sub-tree.

    The planner emits `duration` as a freeform string ("150ms for X, 300ms
    for Y") so we extract the first two ms values. If only one ms value is
    present, both fast and normal default to it. If none, we fall back to
    150ms/300ms.
    """
    duration_str = animation.get("duration", "")
    matches = re.findall(r"(\d+)\s*ms", duration_str)
    fast = f"{matches[0]}ms" if len(matches) >= 1 else "150ms"
    normal = f"{matches[1]}ms" if len(matches) >= 2 else (fast if matches else "300ms")
    return {
        "duration": {"fast": fast, "normal": normal},
        "easing": {"standard": animation.get("easing", "cubic-bezier(0.4, 0, 0.2, 1)")},
    }


def _map_imagery(imagery: dict) -> dict:
    """Convert design-spec.imagery into tokens.imagery sub-tree."""
    return {
        "login":     imagery.get("loginBackground", ""),
        "dashboard": imagery.get("dashboardHero", ""),
        "style": {
            "emptyState": imagery.get("emptyStateStyle", "geometric"),
            "icon":       imagery.get("iconStyle",       "outline"),
            "avatar":     imagery.get("avatarStyle",     "initials"),
        },
    }


def _map_status(status_colors: dict) -> dict:
    """Convert design-spec.statusColors into tokens.semantic.status sub-tree.

    The planner emits keyed entries like `{Pending: {color, label}}`; we
    flatten to `{pending: <color>}` (lowercased entity names).
    """
    from services.css_sanitize import extract_hex
    out = {}
    for entity, info in status_colors.items():
        if isinstance(info, dict) and "color" in info:
            raw = info["color"]
            # Hex (possibly annotated) OR a bare CSS named color ("green").
            clean = extract_hex(raw)
            if not clean and isinstance(raw, str) and re.fullmatch(r"[a-zA-Z]{3,20}", raw.strip()):
                clean = raw.strip().lower()
            if clean:
                out[entity.lower()] = clean
    return out


# === Orchestrator ===

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _merge_spec(base: dict, over: dict) -> dict:
    """Deep-merge ``over`` on top of ``base`` (dicts recurse; other values from
    ``over`` win when they are non-empty). Lists are treated as scalars."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_spec(out[k], v)
        elif v not in (None, "", {}, []):
            out[k] = v
    return out


def compile(design_spec: dict, dna: dict | None = None) -> dict:
    """Transform a design-spec dict into a tokens.custom.json dict.

    Pure function — never raises. Missing sections are silently skipped
    (caller falls back to defaultTokens). Logs WARNING on invalid input.

    When a design DNA is provided, its ``to_design_spec`` form is merged
    UNDER the agent's spec first (agent values win where present; DNA fills
    every gap) — so a partially-parsed or prose-degraded LLM spec still
    yields a complete, distinct identity instead of silently reverting to
    the default look.
    """
    if dna:
        try:
            from services.design_dna import to_design_spec
            base = to_design_spec(dna)
            design_spec = _merge_spec(base, design_spec or {})
        except Exception as e:  # DNA must never break compilation
            logger.warning("design_compiler: DNA merge failed: %s", e)

    out: dict = {}

    palette = design_spec.get("colorPalette") or {}
    if palette:
        try:
            out["color"] = _map_color_palette(palette)
        except Exception as e:
            logger.warning("design_compiler: _map_color_palette failed: %s", e)

    typography = design_spec.get("typography") or {}
    if typography:
        try:
            out["typography"] = _map_typography(typography)
        except Exception as e:
            logger.warning("design_compiler: _map_typography failed: %s", e)

    spacing = design_spec.get("spacing") or {}
    density = (design_spec.get("layout") or {}).get("density", "comfortable")
    if spacing:
        try:
            out["spacing"] = _map_spacing(spacing, density=density)
        except Exception as e:
            logger.warning("design_compiler: _map_spacing failed: %s", e)

    # Always emit radius WITH its `scale` family — the shallow token merge would
    # otherwise drop the register's scale to undefined (→ sharp corners everywhere).
    try:
        out["radius"] = _map_radius(design_spec.get("borderRadius") or {},
                                    scale=_resolve_radius_scale(design_spec))
    except Exception as e:
        logger.warning("design_compiler: _map_radius failed: %s", e)

    shadows = design_spec.get("shadows") or {}
    if shadows:
        try:
            out["shadow"] = _map_shadow(shadows)
        except Exception as e:
            logger.warning("design_compiler: _map_shadow failed: %s", e)

    animation = design_spec.get("animation") or {}
    if animation:
        try:
            out["motion"] = _map_motion(animation)
        except Exception as e:
            logger.warning("design_compiler: _map_motion failed: %s", e)

    imagery = design_spec.get("imagery") or {}
    if imagery:
        try:
            out["imagery"] = _map_imagery(imagery)
        except Exception as e:
            logger.warning("design_compiler: _map_imagery failed: %s", e)

    status = design_spec.get("statusColors") or {}
    if status:
        try:
            out["semantic"] = {"status": _map_status(status)}
        except Exception as e:
            logger.warning("design_compiler: _map_status failed: %s", e)

    layout = design_spec.get("layout") or {}
    if layout:
        try:
            out["layout"] = {
                "nav":     layout.get("navigation", "sidebar"),
                "density": layout.get("density", "comfortable"),
            }
        except Exception as e:
            logger.warning("design_compiler: layout mapping failed: %s", e)

    # --- Wave-2 personality knobs -----------------------------------------
    # These top-level scalars exist in defaultTokens and drive the component
    # hooks (useDensity/useElevation/useMotionLevel) — but were never emitted,
    # so every app rendered the default comfortable/layered/subtle personality.
    _density = (layout or {}).get("density") or design_spec.get("density")
    if _density in ("compact", "comfortable", "spacious"):
        out["density"] = _density
    _elevation = design_spec.get("elevation")
    if _elevation in ("flat", "bordered", "layered", "floating"):
        out["elevation"] = _elevation
    _motion_level = design_spec.get("motionLevel")
    if _motion_level in ("none", "subtle", "expressive"):
        out["motionLevel"] = _motion_level
    _scale_mode = design_spec.get("scaleMode")
    if _scale_mode in ("compact", "balanced", "display") and "typography" in out:
        out["typography"]["scaleMode"] = _scale_mode

    return out


def compile_to_file(design_spec: dict, output_path: str, dna: dict | None = None) -> None:
    """Compile and write the result to disk as JSON.

    Creates parent directories if needed. Never raises (logs on failure).
    """
    try:
        tokens = compile(design_spec, dna=dna)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        logger.info("design_compiler: wrote %s (%d bytes)",
                    output_path, len(json.dumps(tokens)))
    except Exception as e:
        logger.error("design_compiler: compile_to_file failed for %s: %s",
                     output_path, e)

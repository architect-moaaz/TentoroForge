"""Deterministic aggregator: Figma design context → DesignBrief.

Spec A Slice 6a. Wraps the output of ``services.figma_context`` (a
sorted, deduped dict of colors/fonts/font_sizes/border_radii/spacings
extracted from a Figma styles.json) into a validated ``DesignBrief``
with ``source="figma"`` and ``locked_fields`` populated on the
extracted palette/typography/layout fields.

Zero LLM in the chain. Colors are role-inferred by frequency +
neutral-detection; typography by declaration order (largest count
wins for body vs display where distinguishable); radius snapped to
the brief's enum vocabulary. Uncertain fields fall back to sane
neutrals (which are NOT locked — the LLM brief editor may refine).

Contract: for any Figma project, ``brief.palette.brand ==
figma_ctx.colors[<most-frequent-non-neutral>]`` byte-exact. Slice 6c
already enforces that ``brand`` locked ⇒ Smith cannot edit it.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from schemas.design_brief import (
    DesignBrief,
    Identity,
    Layout,
    Palette,
    SignatureMove,
    Typography,
)
from services.design_brief_antipatterns import BASE_ANTI_PATTERNS


class BriefFromFigmaError(RuntimeError):
    """Raised when Figma context is too sparse to build a valid brief."""


# --------------------------------------------------------------------------- #
# Color role inference
# --------------------------------------------------------------------------- #


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    v = hex_color.strip().lstrip("#")
    if len(v) != 6:
        raise ValueError(f"invalid hex: {hex_color!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _is_neutral(hex_color: str) -> bool:
    """R/G/B within 15 of each other → grey-family (neutral)."""
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except ValueError:
        return False
    return abs(r - g) < 15 and abs(g - b) < 15 and abs(r - b) < 15


def _norm_hex(hex_color: str) -> str:
    """`#f00` or `f00000` or ` #FF0000 ` → `#FF0000`."""
    v = hex_color.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return "#" + v.upper()


def _avg_lightness(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)
    return (r + g + b) / 3 / 255.0


def _pick_palette(colors: list[str]) -> dict[str, str]:
    """From a list of hex strings, pick roles: brand, accent, and
    neutrals (surface_bg, surface_elevated, foreground_primary,
    foreground_muted, neutrals_base).

    Rules (all frequency-based, deterministic):
    - Brand: most-frequent non-neutral color.
    - Accent: second-most-frequent non-neutral (falls back to brand
      if there's only one).
    - Neutrals: from the neutral subset, pick by lightness:
      - surface_bg: lightest neutral (~white/near-white)
      - surface_elevated: pure white if present, else lightest
      - foreground_primary: darkest neutral (~near-black)
      - foreground_muted: mid-lightness neutral
      - neutrals_base: mid-light neutral

    Raises BriefFromFigmaError if no non-neutral colors present.
    """
    normed = [_norm_hex(c) for c in colors if isinstance(c, str) and c.strip()]
    if not normed:
        raise BriefFromFigmaError("no colors in figma_ctx.design_tokens.colors")

    non_neutral = Counter(h for h in normed if not _is_neutral(h))
    neutrals = list(dict.fromkeys(h for h in normed if _is_neutral(h)))

    if not non_neutral:
        raise BriefFromFigmaError("no non-neutral colors — cannot pick brand")

    ranked = non_neutral.most_common()
    brand = ranked[0][0]
    accent = ranked[1][0] if len(ranked) > 1 else brand

    # Sort neutrals by lightness for role assignment.
    by_light = sorted(neutrals, key=_avg_lightness)  # dark → light
    if by_light:
        foreground_primary = by_light[0]  # darkest
        surface_bg = by_light[-1]         # lightest
        # Pick a mid-lightness neutral for muted foreground.
        mid_idx = len(by_light) // 2
        foreground_muted = by_light[mid_idx] if mid_idx > 0 and mid_idx < len(by_light) - 1 else by_light[0]
        surface_elevated = "#FFFFFF" if "#FFFFFF" in neutrals else by_light[-1]
        neutrals_base = by_light[max(0, len(by_light) - 2)]
    else:
        # No neutrals at all — synthesize sane defaults.
        foreground_primary = "#111827"
        surface_bg = "#FAFBFC"
        surface_elevated = "#FFFFFF"
        foreground_muted = "#6B7280"
        neutrals_base = "#F3F4F6"

    return {
        "brand": brand,
        "accent": accent,
        "neutrals_base": neutrals_base,
        "surface_bg": surface_bg,
        "surface_elevated": surface_elevated,
        "foreground_primary": foreground_primary,
        "foreground_muted": foreground_muted,
    }


def _infer_neutrals_tint(brand_hex: str) -> str:
    """Bias the neutral scale toward warm/cool based on brand hue.

    Blue/green/purple brand → cool neutrals.
    Red/orange/yellow brand → warm neutrals.
    """
    r, g, b = _hex_to_rgb(brand_hex)
    if b > r:
        return "cool"
    if r > b:
        return "warm"
    return "neutral"


# --------------------------------------------------------------------------- #
# Typography inference
# --------------------------------------------------------------------------- #


def _pick_typography(fonts: list[str]) -> dict[str, Any]:
    """Assign display/body/utility from a list of font families.

    - 1 font: display = body = utility_family (that font).
    - 2 fonts: [0]=display, [1]=body, no utility.
    - 3+ fonts: [0]=display, [1]=body, [2]=utility (or first mono-like
      family for utility).
    """
    clean = [f.strip() for f in fonts if isinstance(f, str) and f.strip()]
    if not clean:
        return {
            "display_family": "system-ui",
            "body_family": "system-ui",
            "utility_family": None,
        }
    if len(clean) == 1:
        return {
            "display_family": clean[0],
            "body_family": clean[0],
            "utility_family": clean[0],
        }
    if len(clean) == 2:
        return {
            "display_family": clean[0],
            "body_family": clean[1],
            "utility_family": None,
        }
    # 3+ — prefer any font with "Mono" in name for utility slot.
    mono_candidates = [f for f in clean if "mono" in f.lower()]
    utility = mono_candidates[0] if mono_candidates else clean[2]
    return {
        "display_family": clean[0],
        "body_family": clean[1],
        "utility_family": utility,
    }


# --------------------------------------------------------------------------- #
# Layout inference (radius snap)
# --------------------------------------------------------------------------- #


def _snap_radius(px_values: list[float]) -> str:
    """Snap a list of Figma border-radius px values to the brief's
    Radius enum vocabulary.

    - Max radius < 4 → sharp_2
    - Max radius >= 100 (or 999) → pill
    - Otherwise → soft_8
    """
    if not px_values:
        return "soft_8"
    max_r = max(px_values)
    if max_r <= 4:
        return "sharp_2"
    if max_r >= 100:
        return "pill"
    return "soft_8"


def _snap_density(spacings: list[float]) -> str:
    """Snap Figma spacings to a density enum.

    Tighter spacing → compact.
    """
    if not spacings:
        return "comfortable"
    positives = [s for s in spacings if s > 0]
    if not positives:
        return "comfortable"
    smallest = min(positives)
    if smallest <= 4:
        return "compact"
    if smallest <= 8:
        return "comfortable"
    return "spacious"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def brief_from_figma(figma_ctx: dict, domain: str) -> DesignBrief:
    """Deterministic aggregator from Figma context → DesignBrief.

    Args:
        figma_ctx: output of ``services.figma_context.extract_figma_context``;
            must contain ``design_tokens.colors``, ``fonts``, etc.
        domain: classified domain label (from discovery).

    Returns:
        A validated ``DesignBrief`` with ``identity.source="figma"``
        and per-field ``locked_fields`` populated on palette / typography
        / layout. Downstream editors (Smith edit_brief) will refuse to
        mutate the locked fields.

    Raises:
        BriefFromFigmaError: figma_ctx is too sparse to produce a valid
            brief (no colors, no non-neutral colors, etc.).
    """
    tokens = (figma_ctx or {}).get("design_tokens") or {}
    if not tokens:
        raise BriefFromFigmaError("figma_ctx missing design_tokens")

    palette_kwargs = _pick_palette(tokens.get("colors") or [])
    tint = _infer_neutrals_tint(palette_kwargs["brand"])
    palette = Palette(
        **palette_kwargs,
        neutrals_tint=tint,
        locked_fields={
            "brand", "accent", "surface_bg", "surface_elevated",
            "foreground_primary", "neutrals_base",
        },
    )

    typo_kwargs = _pick_typography(tokens.get("fonts") or [])
    typography = Typography(
        **typo_kwargs,
        locked_fields={"display_family", "body_family"},
    )

    layout = Layout(
        density=_snap_density(tokens.get("spacings") or []),
        radius=_snap_radius(tokens.get("border_radii") or []),
        grid="12col",
        locked_fields={"radius"},
    )

    identity = Identity(
        domain=domain,
        register=["structured"],
        voice="warm_precise",
        modes=["light", "dark"],
        source="figma",
    )

    return DesignBrief(
        identity=identity,
        palette=palette,
        typography=typography,
        layout=layout,
        # Schema requires ≥1 signature move — Figma IS the signature.
        signature_moves=[
            SignatureMove(kind="figma_source", detail="palette + type + radius extracted verbatim from Figma"),
        ],
        anti_patterns=BASE_ANTI_PATTERNS,
    )


__all__ = ["brief_from_figma", "BriefFromFigmaError"]

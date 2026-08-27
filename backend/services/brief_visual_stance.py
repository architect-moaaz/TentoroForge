"""Shared brief-reader for design-authorship values.

Spec D Wave 1 — this is the single reader every legacy design-authoring
caller (design_agent, design_compiler, ux_spec_generator, phase_gates,
generate.py) checks BEFORE falling back to the legacy DNA / language /
domain-UX modules. When the brief has already authored what a design
value is (palette, visual stance, layout numerics, taglines, product
name), the caller stays out of its way — the brief wins, verbatim.

The helpers:

  - :func:`load_brief_from(output_dir) -> DesignBrief | None`
      Reads ``contracts/brief.json`` off disk. Re-export of
      :func:`services.design_brief_to_prompt.load_brief_from_disk` so
      callers don't need to import two modules.

  - :func:`get_palette(brief) -> dict`
      ``{brand, accent, ink, canvas, muted}`` with brief hexes; sensible
      neutral defaults fill in any missing field.

  - :func:`get_visual_stance(brief) -> dict`
      ``{hue_range, temperature, shape_vocab, principles}`` from
      ``identity.visual_stance`` (Wave 1 field); empty defaults when
      the field is absent.

  - :func:`get_layout_numerics(brief) -> dict`
      ``{radius_px, gutter_px, density_pt, shadow_scale, header_align,
      card_border}`` derived from the brief's layout enums and Wave 4
      numeric companions. Values snap into the capability envelope's
      accepted ranges.

  - :func:`get_taglines(brief) -> list[str]`
      ``identity.auth_taglines`` (Wave 1 field), or ``[]``.

  - :func:`get_product_names(brief) -> list[str]`
      ``identity.product_name_candidates`` (Wave 1 field), or ``[]``.

  - :func:`get_tone_intensity(brief) -> float | None`
      ``identity.tone_intensity`` (Wave 1 round-2 field). Returns
      ``None`` when the brief is silent so callers can distinguish
      "author wants quiet" (0.0) from "author didn't say".

  - :func:`get_compliance_flags(brief) -> list[str]`
      ``identity.compliance_flags`` (Wave 1 round-2 field) as a list
      of lowercase strings; ``[]`` when absent.

  - :func:`get_foreground_hint(brief) -> str | None`
      ``palette.foreground_hint`` (Wave 1 round-2 field) — a hex
      override for the contrast-guardrail's `_fg_for` computation.
      Returns None when unset. Callers use it verbatim.

  - :func:`get_nav_language(brief) -> str | None`
      ``layout.nav_language`` (Wave 1 round-2 enum) as its raw string
      value (``chrome_heavy`` | ``chrome_light`` | ``invisible``), or
      ``None`` when unset. Callers gate nav-CSS injection off it.

Every helper is a pure function. Nothing raises; a missing brief, a
missing sub-field, or a malformed blob returns the documented default
(empty dict / ``None`` / ``[]``). Callers use them as:
"did the brief author this value? If yes, respect it verbatim; otherwise
fall back to the legacy DNA / language / domain-UX derivation."
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from schemas.design_brief import DesignBrief
from services.design_brief_to_prompt import load_brief_from_disk


# ---------------------------------------------------------------------------
# Defaults — mirror the ranges in services/design_capability_envelope.py.
# Values are sensible neutral defaults for callers that need something when
# the brief is absent or silent, without pulling in the full envelope module.
# ---------------------------------------------------------------------------

_DEFAULT_PALETTE: dict[str, str] = {
    "brand": "#3B82F6",     # neutral blue
    "accent": "#8B5CF6",    # neutral violet
    "ink": "#0F172A",       # near-black
    "canvas": "#FFFFFF",    # white
    "muted": "#64748B",     # slate
}

_DEFAULT_STANCE: dict[str, Any] = {
    "hue_range": None,
    "temperature": None,
    "shape_vocab": None,
    "principles": [],
}

# Layout numerics — kept in lock-step with design_capability_envelope's
# ranges but replicated here so this helper stays a thin brief reader.
_DEFAULT_LAYOUT_NUMERICS: dict[str, Any] = {
    "radius_px": 8,           # matches Radius.soft_8
    "gutter_px": 16,          # matches "comfortable" density
    "density_pt": 12,         # matches Density.comfortable
    "shadow_scale": 1,        # subtle default
    "header_align": "left",
    "card_border": "hairline",
}

# Enum → numeric snap tables for layout values that the brief carries as
# an enum bucket instead of a continuous number. Keep them small and
# obvious — brief_to_design_spec has the sophisticated snap; here we
# just need a "good enough" default when the numeric companion is absent.
_RADIUS_ENUM_TO_PX: dict[str, int] = {
    "sharp_2": 2,
    "soft_8": 8,
    "pill": 32,   # envelope max — anything beyond snaps to pill
}

_DENSITY_ENUM_TO_PT: dict[str, int] = {
    "compact": 8,
    "comfortable": 12,
    "spacious": 16,
    "spacious_for_touch": 20,
}

_DENSITY_ENUM_TO_GUTTER: dict[str, int] = {
    "compact": 12,
    "comfortable": 16,
    "spacious": 24,
    "spacious_for_touch": 32,
}


# ---------------------------------------------------------------------------
# Loader (re-export)
# ---------------------------------------------------------------------------

def load_brief_from(output_dir: str | Path) -> DesignBrief | None:
    """Convenience alias for :func:`load_brief_from_disk`.

    Reads ``contracts/brief.json`` under ``output_dir`` and returns the
    parsed :class:`DesignBrief`. Returns ``None`` on missing file /
    malformed JSON / schema mismatch — never raises.
    """
    return load_brief_from_disk(output_dir)


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def get_palette(brief: DesignBrief | None) -> dict[str, str]:
    """Return the brief's palette with the five keys generic callers need.

    Keys: ``brand``, ``accent``, ``ink``, ``canvas``, ``muted``.

      - ``brand``  = ``palette.brand``           (primary action)
      - ``accent`` = ``palette.accent``          (attention moments)
      - ``ink``    = ``palette.foreground_primary``
      - ``canvas`` = ``palette.surface_bg``
      - ``muted``  = ``palette.foreground_muted``

    Any missing field falls back to a neutral default so callers can rely
    on all five keys being present.
    """
    out = dict(_DEFAULT_PALETTE)
    if brief is None:
        return out
    p = getattr(brief, "palette", None)
    if p is None:
        return out
    for src, dst in (
        ("brand", "brand"),
        ("accent", "accent"),
        ("foreground_primary", "ink"),
        ("surface_bg", "canvas"),
        ("foreground_muted", "muted"),
    ):
        v = getattr(p, src, None)
        if isinstance(v, str) and v.strip():
            out[dst] = v.strip()
    return out


def get_visual_stance(brief: DesignBrief | None) -> dict[str, Any]:
    """Return ``identity.visual_stance`` fields, with empty defaults.

    Shape: ``{hue_range, temperature, shape_vocab, principles}``. When
    the brief has no ``visual_stance``, every field is its zero-value
    (``None`` for the free-form strings, ``[]`` for principles).
    """
    out: dict[str, Any] = dict(_DEFAULT_STANCE)
    out["principles"] = []  # fresh list per call — never share the default
    if brief is None:
        return out
    ident = getattr(brief, "identity", None)
    if ident is None:
        return out
    stance = getattr(ident, "visual_stance", None)
    if stance is None:
        return out
    for k in ("hue_range", "temperature", "shape_vocab"):
        v = getattr(stance, k, None)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    principles = getattr(stance, "principles", None)
    if isinstance(principles, list):
        out["principles"] = [
            str(p).strip() for p in principles
            if p is not None and str(p).strip()
        ]
    return out


def get_layout_numerics(brief: DesignBrief | None) -> dict[str, Any]:
    """Return the brief's layout numerics, snapping enums where needed.

    Shape: ``{radius_px, gutter_px, density_pt, shadow_scale,
    header_align, card_border}``. The brief's Wave 4 numeric fields
    (``radius_px``, ``density_pt``) win when present; otherwise the
    enum bucket (``layout.radius``, ``layout.density``) snaps to a
    representative numeric value. Fields the brief does not carry
    (``gutter_px`` derived from density; ``shadow_scale``,
    ``header_align``, ``card_border``) return sensible defaults.
    """
    out: dict[str, Any] = dict(_DEFAULT_LAYOUT_NUMERICS)
    if brief is None:
        return out
    layout = getattr(brief, "layout", None)
    if layout is None:
        return out
    # Wave 4 numeric radius wins over the enum bucket.
    r_px = getattr(layout, "radius_px", None)
    if isinstance(r_px, int) and r_px >= 0:
        out["radius_px"] = r_px
    else:
        r_enum = getattr(layout, "radius", None)
        r_val = getattr(r_enum, "value", None) if r_enum is not None else None
        if isinstance(r_val, str) and r_val in _RADIUS_ENUM_TO_PX:
            out["radius_px"] = _RADIUS_ENUM_TO_PX[r_val]
    # Wave 4 numeric density wins over the enum bucket.
    d_pt = getattr(layout, "density_pt", None)
    if isinstance(d_pt, int) and d_pt >= 0:
        out["density_pt"] = d_pt
    else:
        d_enum = getattr(layout, "density", None)
        d_val = getattr(d_enum, "value", None) if d_enum is not None else None
        if isinstance(d_val, str) and d_val in _DENSITY_ENUM_TO_PT:
            out["density_pt"] = _DENSITY_ENUM_TO_PT[d_val]
    # Gutter is derived from the density enum — brief has no dedicated field.
    d_enum = getattr(layout, "density", None)
    d_val = getattr(d_enum, "value", None) if d_enum is not None else None
    if isinstance(d_val, str) and d_val in _DENSITY_ENUM_TO_GUTTER:
        out["gutter_px"] = _DENSITY_ENUM_TO_GUTTER[d_val]
    return out


def get_taglines(brief: DesignBrief | None) -> list[str]:
    """Return ``identity.auth_taglines`` (Wave 1 field) or ``[]``."""
    if brief is None:
        return []
    ident = getattr(brief, "identity", None)
    if ident is None:
        return []
    tags = getattr(ident, "auth_taglines", None)
    if not isinstance(tags, list):
        return []
    return [str(t).strip() for t in tags if t is not None and str(t).strip()]


def get_product_names(brief: DesignBrief | None) -> list[str]:
    """Return ``identity.product_name_candidates`` (Wave 1 field) or ``[]``."""
    if brief is None:
        return []
    ident = getattr(brief, "identity", None)
    if ident is None:
        return []
    names = getattr(ident, "product_name_candidates", None)
    if not isinstance(names, list):
        return []
    return [str(n).strip() for n in names if n is not None and str(n).strip()]


def get_tone_intensity(brief: DesignBrief | None) -> float | None:
    """Return ``identity.tone_intensity`` (Wave 1 round-2 field) or ``None``.

    ``None`` means the brief did not author a value — callers should
    fall back to the archetype-driven personality default. ``0.0`` is
    a real authored value (quietest possible app) and MUST NOT be
    conflated with the "silent" case.
    """
    if brief is None:
        return None
    ident = getattr(brief, "identity", None)
    if ident is None:
        return None
    v = getattr(ident, "tone_intensity", None)
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN guard
        return None
    return max(0.0, min(1.0, f))


def get_compliance_flags(brief: DesignBrief | None) -> list[str]:
    """Return ``identity.compliance_flags`` (Wave 1 round-2 field) or ``[]``.

    Values are lowercase-normalized by the schema validator; this
    helper defensively re-normalizes so callers can rely on it.
    """
    if brief is None:
        return []
    ident = getattr(brief, "identity", None)
    if ident is None:
        return []
    flags = getattr(ident, "compliance_flags", None)
    if not isinstance(flags, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f is None:
            continue
        s = str(f).strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def get_foreground_hint(brief: DesignBrief | None) -> str | None:
    """Return ``palette.foreground_hint`` (Wave 1 round-2 field) or ``None``.

    A #RRGGBB hex override for the on-brand foreground/label color.
    Callers use it verbatim to bypass the runtime contrast calc.
    """
    if brief is None:
        return None
    palette = getattr(brief, "palette", None)
    if palette is None:
        return None
    hint = getattr(palette, "foreground_hint", None)
    if not isinstance(hint, str):
        return None
    v = hint.strip()
    if not v:
        return None
    return v.upper()


def get_nav_language(brief: DesignBrief | None) -> str | None:
    """Return ``layout.nav_language`` raw enum value, or ``None``.

    Values: ``chrome_heavy`` | ``chrome_light`` | ``invisible``. Callers
    gate nav-CSS injection off this — ``invisible`` should suppress
    the per-skin block entirely.
    """
    if brief is None:
        return None
    layout = getattr(brief, "layout", None)
    if layout is None:
        return None
    nl = getattr(layout, "nav_language", None)
    if nl is None:
        return None
    # Enum → raw string; also accept plain strings for safety.
    val = getattr(nl, "value", nl)
    if not isinstance(val, str):
        return None
    v = val.strip().lower()
    return v or None


__all__ = [
    "load_brief_from",
    "get_palette",
    "get_visual_stance",
    "get_layout_numerics",
    "get_taglines",
    "get_product_names",
    "get_tone_intensity",
    "get_compliance_flags",
    "get_foreground_hint",
    "get_nav_language",
]

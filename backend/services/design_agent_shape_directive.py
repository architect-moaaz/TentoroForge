"""IRF-M3-T7: hero + density directive injected into design_agent prompt.

Turns `plan.app_shape.layout.hero` and `plan.app_shape.layout.density` (from
the four-axis substrate) into a HARD-CONSTRAINT prompt block. The design agent
receives concrete guidance for each hero/density combination rather than the
generic 'be opinionated about density' advice.

Empty string when no app_shape is present — a plan without the substrate gets
byte-identical prompt behavior to before.

Hero vocabulary comes from `backend/shapes/vocabulary.json:layout.hero` (11
values); density from `layout.density` (spacious / comfortable / dense). The
`dense` primitive maps to the design-spec's own `compact` density value —
downstream consumers already know `compact`.
"""
from __future__ import annotations

from typing import Any


# ── vocabulary → concrete prompt guidance ────────────────────────────────

# One-sentence rendering directives per hero primitive. Each describes what
# the hero surface of the primary/landing page must LOOK LIKE, so the LLM
# can encode the choice into the design-spec + globals.css.
_HERO_GUIDANCE: dict[str, str] = {
    "none": (
        "NO hero. The primary page must start with content immediately — "
        "no banner, no gradient block, no oversized header. Reserve first-fold "
        "real estate for the interaction."
    ),
    "full-bleed-gradient": (
        "Full-bleed gradient hero on landing/detail pages: 100% viewport width, "
        "60-80vh tall, brand-hued gradient (2-3 stops from the palette), large "
        "display-face headline centred, one primary CTA."
    ),
    "media-hero": (
        "Media-hero: full-bleed image or video header (100vw, ~60vh) on hero "
        "pages, headline overlaid with tasteful scrim, one primary CTA."
    ),
    "metric-row": (
        "Metric-row hero: NO banner — the top of the primary surface is a strip "
        "of 4-6 KPI stat cards showing live numbers, headline reduced to a "
        "single small label above."
    ),
    "player-bar": (
        "Persistent player-bar: a sticky media control bar (top or bottom) is "
        "the hero surface — hero pages open with the player expanded, secondary "
        "pages keep the bar minimised at the edge."
    ),
    "map-canvas": (
        "Map-canvas hero: an interactive map fills the viewport on landing / "
        "browse pages; overlays (search, filters, pins) float above; NO banner "
        "or scrolled content above the map."
    ),
    "feed-header": (
        "Feed-header: compact hero (~120px) with brand mark, a filter/segmented "
        "control, and the feed starts immediately below — never a large hero "
        "image or gradient block."
    ),
    "now-playing": (
        "Now-playing hero: expanded now-playing card (artwork, title, controls) "
        "dominates the primary surface, secondary content queued below."
    ),
}

# density primitive → design-spec token. `dense` in the substrate vocabulary
# maps to `compact` in the design-spec (both mean tight rows/small padding).
_DENSITY_TO_SPEC: dict[str, str] = {
    "dense": "compact",
    "comfortable": "comfortable",
    "spacious": "spacious",
}

# Concrete rendering guidance per density.
_DENSITY_GUIDANCE: dict[str, str] = {
    "dense": (
        "COMPACT density — data-heavy surfaces (tables, grids) use tight row "
        "heights (32-40px), reduced padding (px-2 py-1 scale), small font "
        "sizes (13-14px body). No generous whitespace."
    ),
    "comfortable": (
        "COMFORTABLE density — standard business-app spacing (44-52px rows, "
        "px-4 py-2 padding, 14-16px body). Balanced, not tight, not airy."
    ),
    "spacious": (
        "SPACIOUS density — consumer/marketing spacing (64+px rows, generous "
        "px-6 py-4 padding, 16-18px body, plenty of vertical rhythm)."
    ),
}


# ── public API ──────────────────────────────────────────────────────────


def read_hero(plan: Any) -> str | None:
    """Return the hero primitive from plan.app_shape.layout.hero, or None."""
    if not isinstance(plan, dict):
        return None
    shape = plan.get("app_shape")
    if not isinstance(shape, dict):
        return None
    layout = shape.get("layout")
    if not isinstance(layout, dict):
        return None
    hero = layout.get("hero")
    if hero in _HERO_GUIDANCE:
        return hero
    return None


def read_density(plan: Any) -> str | None:
    """Return the density primitive from plan.app_shape.layout.density, or None."""
    if not isinstance(plan, dict):
        return None
    shape = plan.get("app_shape")
    if not isinstance(shape, dict):
        return None
    layout = shape.get("layout")
    if not isinstance(layout, dict):
        return None
    density = layout.get("density")
    if density in _DENSITY_GUIDANCE:
        return density
    return None


def spec_density_for(primitive: str | None) -> str | None:
    """Map the substrate density primitive to the design-spec token
    (compact/comfortable/spacious) — the value the LLM should emit."""
    if primitive is None:
        return None
    return _DENSITY_TO_SPEC.get(primitive)


def build_directive(plan: Any) -> str:
    """Return a hard-constraint prompt block for hero + density.

    Empty string when neither primitive is present — the design agent gets
    byte-identical prompt behavior to before.
    """
    hero = read_hero(plan)
    density = read_density(plan)
    if hero is None and density is None:
        return ""

    lines = [
        "",
        "## Shape Directive (from plan.app_shape.layout)",
        "The following are HARD CONSTRAINTS derived from the app's four-axis",
        "shape — they override generic domain defaults. Encode them in the",
        "design-spec + globals.css, not just as prose in the JSON.",
        "",
    ]
    if hero is not None:
        lines.append(f"- **hero = `{hero}`** — {_HERO_GUIDANCE[hero]}")
    if density is not None:
        spec_value = _DENSITY_TO_SPEC[density]
        lines.append(
            f"- **density = `{density}`** (emit `layout.density: \"{spec_value}\"` in "
            f"the design-spec) — {_DENSITY_GUIDANCE[density]}"
        )
    lines.append("")
    return "\n".join(lines)

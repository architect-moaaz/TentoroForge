"""UI/UX Pro Max — vendored design-knowledge injector.

Reads the vendored skill.md + CSV catalogs at ``backend/skills/ui-ux-pro-max/``
and composes a compact prompt block the design agent can append to its system
prompt. Purpose: give the LLM a curated reference (84 UI styles, 192 palettes
by product type, 74 font pairings, 98 UX guidelines) so it stops re-inventing
visual identity from scratch.

Gate: ``FORGE_UI_UX_PRO_MAX`` env var. Off by default; opt in per run.

Scope: injects only the rows relevant to the brief's product type + a compact
top-level instruction block. Full CSVs stay on disk for the designer's
research (symlinked at ``docs/design/reference/ui-ux-pro-max-data``).

Boundaries:
  * Reference-only — the LLM still authors CSS. This layer raises the floor
    (better palette recipes, real font pairings, avoids AI-safe defaults);
    the register catalog (docs/superpowers/plans/2026-08-11-register-catalog.md)
    is the ceiling-lifter that turns picks into deterministic CSS.
  * Never mutates the brief or the design spec — pure prompt composition.
  * Fails gracefully — a missing skill file returns an empty block; the
    design agent still runs.

Attribution: MIT-licensed. See backend/skills/ui-ux-pro-max/ATTRIBUTION.md.
"""

from __future__ import annotations

import csv
import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_SKILL_ROOT = Path(__file__).resolve().parent.parent / "skills" / "ui-ux-pro-max"
_DATA_DIR = _SKILL_ROOT / "data"

# Map a brief's coarse domain string → the product-type buckets used in the
# ui-ux-pro-max CSVs. Multiple bucket hits are OK — the loader picks the
# highest-scoring match. Values are checked substring-wise, case-insensitive.
_DOMAIN_TO_PRODUCT_TYPES: dict[str, tuple[str, ...]] = {
    "wellness":         ("Wellness", "Beauty", "Fitness", "Health"),
    "hospitality":      ("Hospitality", "Restaurant", "Travel", "Hotel"),
    "boutique_retail":  ("Luxury", "Boutique", "Retail"),
    "food":             ("Food", "Restaurant", "Delivery"),
    "publishing":       ("Editorial", "Publishing", "Blog", "Magazine"),
    "personal_services":("Wellness", "Beauty", "Professional Services"),
    "saas":             ("SaaS", "Micro SaaS"),
    "developer_tools":  ("Developer Tools", "Tech", "Startup"),
    "ops":              ("B2B", "Enterprise", "Dashboard"),
    "finance":          ("Fintech", "Financial", "Banking"),
    "ecommerce":        ("E-commerce", "Retail"),
    "marketplace":      ("Marketplace", "E-commerce"),
    "education":        ("Education", "EdTech", "Learning"),
    "gaming":           ("Gaming", "Entertainment"),
    "healthcare":       ("Healthcare", "Medical"),
    "professional_services": ("Professional Services", "B2B", "Consulting"),
}


def is_enabled() -> bool:
    """Whether the ui-ux-pro-max injection is on for this process.

    Accepts the same truthy values as other FORGE_* flags: 1/true/on/yes/warn/strict.
    """
    raw = (os.environ.get("FORGE_UI_UX_PRO_MAX") or "").strip().lower()
    return raw in {"1", "true", "on", "yes", "warn", "strict"}


@lru_cache(maxsize=1)
def _load_skill_content() -> str:
    """Read the vendored skill-content.md once. Cached for the process life."""
    p = _SKILL_ROOT / "skill-content.md"
    if not p.is_file():
        logger.warning("[ui-ux-pro-max] skill file missing at %s", p)
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("[ui-ux-pro-max] skill file unreadable: %s", exc)
        return ""


@lru_cache(maxsize=8)
def _load_csv(name: str) -> list[dict[str, str]]:
    """Read a vendored CSV once, cached by filename."""
    p = _DATA_DIR / name
    if not p.is_file():
        logger.warning("[ui-ux-pro-max] data missing: %s", p)
        return []
    try:
        with p.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except OSError as exc:
        logger.warning("[ui-ux-pro-max] csv unreadable %s: %s", name, exc)
        return []


def _product_types_for_domain(domain: str | None) -> tuple[str, ...]:
    """Map a brief.identity.domain string to ui-ux-pro-max product-type
    buckets. Falls back to SaaS + B2B (the safest general defaults) when the
    domain doesn't match any known bucket."""
    if not domain:
        return ("SaaS", "B2B")
    key = domain.strip().lower().replace(" ", "_").replace("-", "_")
    if key in _DOMAIN_TO_PRODUCT_TYPES:
        return _DOMAIN_TO_PRODUCT_TYPES[key]
    # Substring fallback — "wellness studio" → "wellness".
    for bucket_key, buckets in _DOMAIN_TO_PRODUCT_TYPES.items():
        if bucket_key in key:
            return buckets
    return ("SaaS", "B2B")


def _matching_rows(rows: list[dict[str, str]], column: str,
                   product_types: tuple[str, ...],
                   limit: int = 3) -> list[dict[str, str]]:
    """Score CSV rows by product-type overlap on `column`; return top `limit`.

    A row scores 1 point per product-type keyword found (case-insensitive) in
    `row[column]`. Rows scoring 0 are dropped. Ties broken by list order (the
    CSVs are hand-ordered — first rows tend to be the strongest matches).
    """
    scored: list[tuple[int, int, dict[str, str]]] = []
    lowered = [pt.lower() for pt in product_types]
    for idx, row in enumerate(rows):
        haystack = (row.get(column) or "").lower()
        if not haystack:
            continue
        score = sum(1 for pt in lowered if pt in haystack)
        if score > 0:
            scored.append((-score, idx, row))  # negate for max-heap ordering
    scored.sort()
    return [r for _, _, r in scored[:limit]]


def _fmt_palette(row: dict[str, str]) -> str:
    """Render a palette row as a compact one-liner."""
    ptype = (row.get("Product Type") or "").strip()
    slots = [
        ("primary",    row.get("Primary")),
        ("secondary",  row.get("Secondary")),
        ("accent",     row.get("Accent")),
        ("background", row.get("Background")),
        ("foreground", row.get("Foreground")),
        ("muted",      row.get("Muted")),
        ("border",     row.get("Border")),
    ]
    pairs = ", ".join(f"{k}={v.strip()}" for k, v in slots if v and v.strip())
    note = (row.get("Notes") or "").strip()
    return f"- {ptype}: {pairs}" + (f"  # {note}" if note else "")


def _fmt_typography(row: dict[str, str]) -> str:
    """Render a font-pairing row as a compact recommendation."""
    name = (row.get("Font Pairing Name") or "").strip()
    heading = (row.get("Heading Font") or "").strip()
    body = (row.get("Body Font") or "").strip()
    mood = (row.get("Mood/Style Keywords") or "").strip()
    best_for = (row.get("Best For") or "").strip()
    return f"- {name}: {heading} + {body}  ({mood})  ← {best_for}"


def _fmt_style(row: dict[str, str]) -> str:
    """Render a UI-style row as a compact recommendation."""
    style = (row.get("Type") or row.get("Style Category") or "").strip()
    keywords = (row.get("Keywords") or "").strip()[:120]
    best_for = (row.get("Best For") or "").strip()
    do_not = (row.get("Do Not Use For") or "").strip()
    return (f"- {style}: {keywords}\n"
            f"    Best for: {best_for}\n"
            f"    AVOID for: {do_not}")


def _fmt_reasoning(row: dict[str, str]) -> str:
    """Render a ui-reasoning row as a per-product-type recommendation."""
    ptype = (row.get("UI_Category") or "").strip()
    pattern = (row.get("Recommended_Pattern") or "").strip()
    style_pri = (row.get("Style_Priority") or "").strip()
    color_mood = (row.get("Color_Mood") or "").strip()
    typo_mood = (row.get("Typography_Mood") or "").strip()
    anti = (row.get("Anti_Patterns") or "").strip()
    return (f"- {ptype}: pattern={pattern}; style={style_pri}; "
            f"color={color_mood}; typo={typo_mood}\n"
            f"    Anti-patterns: {anti}")


def compose_prompt(brief_domain: str | None) -> str:
    """Build the compact ui-ux-pro-max reference block for a given brief.

    Returns an empty string when the flag is off OR when the vendored assets
    are missing — the design agent still runs unchanged in either case.
    """
    if not is_enabled():
        return ""

    product_types = _product_types_for_domain(brief_domain)
    styles = _load_csv("styles.csv")
    palettes = _load_csv("colors.csv")
    typography = _load_csv("typography.csv")
    reasoning = _load_csv("ui-reasoning.csv")

    # Compact per-section extraction: the top 3 rows per section that match
    # the brief's product-type buckets. Keeps the prompt block ~3-5KB.
    matched_reasoning = _matching_rows(reasoning, "UI_Category", product_types, limit=2)
    matched_palettes  = _matching_rows(palettes,  "Product Type", product_types, limit=3)
    matched_typo      = _matching_rows(typography, "Best For",    product_types, limit=3)
    matched_styles    = _matching_rows(styles,    "Best For",     product_types, limit=3)

    parts: list[str] = []
    parts.append("=" * 78)
    parts.append("[UI/UX PRO MAX — DESIGN KNOWLEDGE BASE]")
    parts.append(f"Reference material for domain: {brief_domain or '<unspecified>'}")
    parts.append(f"Matching product-type buckets: {', '.join(product_types)}")
    parts.append("")
    parts.append("This block is CURATED design knowledge (MIT-licensed, vendored from")
    parts.append("ui-ux-pro-max-skill). Use it as REFERENCE when authoring the design")
    parts.append("spec — palette, typography, style choice. Do NOT copy verbatim;")
    parts.append("adapt to the brief. Prefer these curated palettes/pairings over")
    parts.append("generic AI defaults (warm-cream+serif+terracotta, purple-blue gradient,")
    parts.append("brutalist-mono, glassmorphism-vibrant, etc. — regressions we've seen).")
    parts.append("")

    if matched_reasoning:
        parts.append("─── RECOMMENDED PATTERN + STYLE per product type ───────────────────")
        parts.extend(_fmt_reasoning(r) for r in matched_reasoning)
        parts.append("")

    if matched_palettes:
        parts.append("─── PROVEN PALETTES (WCAG-verified) ─────────────────────────────────")
        parts.extend(_fmt_palette(r) for r in matched_palettes)
        parts.append("")

    if matched_typo:
        parts.append("─── TYPE PAIRINGS ───────────────────────────────────────────────────")
        parts.extend(_fmt_typography(r) for r in matched_typo)
        parts.append("")

    if matched_styles:
        parts.append("─── UI STYLES (top-fit) ─────────────────────────────────────────────")
        parts.extend(_fmt_style(r) for r in matched_styles)
        parts.append("")

    parts.append("HARD RULES from this knowledge base:")
    parts.append("- Pick a proven palette from above OR derive from the brief's brand")
    parts.append("  hex using the closest palette's chord as a template.")
    parts.append("- Pick a proven type pairing from above — do NOT invent unpaired fonts.")
    parts.append("- If the recommended style says 'AVOID for <this domain>' — do not use it.")
    parts.append("- Respect anti-patterns for this product type.")
    parts.append("- Never author CSS that sets `font-size: 0` on nav/chrome selectors.")
    parts.append("- Never author `box-shadow: X X 0 0` (hard offset shadows) unless the")
    parts.append("  recommended style is brutalist AND the brief.register asks for it.")
    parts.append("- Never author `!important` layout overrides.")
    parts.append("=" * 78)

    return "\n".join(parts)


__all__ = ["compose_prompt", "is_enabled"]

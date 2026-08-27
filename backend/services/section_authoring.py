"""Code-authored section-kind catalog (Spec D Wave 6 replacement).

Retires the hand-curated 15-item template dict in ``services.section_templates``
in favor of two small helpers:

  * :func:`list_section_kinds` — returns the closed set of section kinds
    the visual-editor palette shows (hero, features, cta, ...). Same
    15 kinds as the old catalog so the frontend picker keeps its shape.

  * :func:`author_section` — given a kind, current page context, and
    (optionally) the design brief, returns a ``{id, name, category,
    description, prompt}`` dict. The ``prompt`` field is the natural-
    language authoring instruction the ``code_editor`` agent runs to
    emit the new section's JSX/TSX. When a brief is present we splice
    in the brand+accent hexes and visual stance so the section reads
    as part of the app, not a generic Tailwind demo.

No LLM roundtrip: this is a pure Python authoring pass. The
``code_editor`` agent is still the one that writes code; this helper
just replaces the fixed pool with a per-kind hardcoded default that
knows how to read the brief.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Closed kind set — mirrors the 15 categories the old ``SECTION_TEMPLATES``
# list covered. The visual-editor picker groups by ``category``.
# ---------------------------------------------------------------------------

_KINDS: list[dict[str, str]] = [
    {"id": "hero", "name": "Hero", "category": "hero",
     "description": "Full-width hero with headline, subtext, and CTA buttons"},
    {"id": "features", "name": "Features", "category": "features",
     "description": "Grid of feature cards with icons, titles, and descriptions"},
    {"id": "cta", "name": "Call to Action", "category": "cta",
     "description": "Prominent call-to-action banner with heading and button"},
    {"id": "testimonials", "name": "Testimonials", "category": "testimonials",
     "description": "Customer testimonial cards with quotes and avatars"},
    {"id": "pricing", "name": "Pricing", "category": "pricing",
     "description": "Pricing tier cards with features list and CTA"},
    {"id": "footer", "name": "Footer", "category": "footer",
     "description": "Multi-column footer with links, logo, and copyright"},
    {"id": "stats", "name": "Stats", "category": "stats",
     "description": "Row of key metrics with numbers and labels"},
    {"id": "gallery", "name": "Gallery", "category": "gallery",
     "description": "Image gallery grid with responsive columns"},
    {"id": "contact", "name": "Contact", "category": "contact",
     "description": "Contact form with input fields and submit button"},
    {"id": "faq", "name": "FAQ", "category": "faq",
     "description": "Expandable question and answer list"},
    {"id": "team", "name": "Team", "category": "team",
     "description": "Team member grid with photos, names, and roles"},
    {"id": "timeline", "name": "Timeline", "category": "timeline",
     "description": "Vertical timeline of milestones or steps"},
    {"id": "logos", "name": "Logo Cloud", "category": "logos",
     "description": "Row of partner or customer logos"},
    {"id": "video", "name": "Video", "category": "video",
     "description": "Video embed section with heading and description"},
    {"id": "subscribe", "name": "Subscribe", "category": "cta",
     "description": "Newsletter signup with email input and subscribe button"},
]


# Per-kind authoring recipes. Each entry is the base instruction the
# ``code_editor`` agent runs. The kind-neutral requirements block (use
# Tailwind, be responsive, semantic HTML, ...) is added by
# ``section_instruction_builder`` — kept there so the requirements stay
# in one place and this module stays about SECTION SHAPE.
_RECIPES: dict[str, str] = {
    "hero": (
        "Add a hero section with a centered layout. Include a large heading, "
        "a subtitle/description line below it, and two CTA buttons side by side "
        "(primary filled, secondary outline). Use a full-width container with "
        "generous vertical padding."
    ),
    "features": (
        "Add a features section with a heading and a 3-column grid of feature "
        "cards. Each card has an icon placeholder (a colored circle with a "
        "simple shape), a feature title, and a short description. Use a "
        "responsive grid that collapses to 2 columns on tablet and 1 on mobile."
    ),
    "cta": (
        "Add a call-to-action banner section with a distinct background color. "
        "Include a bold heading, a short description, and a contrasting CTA "
        "button. Center all content. The background should stand out from the "
        "rest of the page — a solid brand color or subtle gradient works well."
    ),
    "testimonials": (
        "Add a testimonials section with a heading and a grid of 3 testimonial "
        "cards. Each card has a quote text, a user avatar placeholder (colored "
        "circle with initials), user name, and their role/company. Use subtle "
        "card styling with a soft shadow and rounded corners."
    ),
    "pricing": (
        "Add a pricing section with a heading, subtitle, and 3 pricing tier "
        "cards in a row. Each card has: plan name, price with period, list of "
        "features (with checkmarks), and a CTA button. The middle/recommended "
        "card should be visually highlighted with a border or shadow."
    ),
    "footer": (
        "Add a footer section with a dark background. Include a logo/brand "
        "name on the left, 3-4 columns of navigation links (Product, Company, "
        "Resources, Legal), and a bottom bar with copyright text. Keep it "
        "responsive — stack columns on mobile."
    ),
    "stats": (
        "Add a statistics section with 4 key metrics in a row. Each stat has "
        "a large number (e.g., '10K+', '99%', '500+', '24/7') and a label "
        "below. Use a subtle background to differentiate from surrounding "
        "sections. Center the content and make it responsive."
    ),
    "gallery": (
        "Add an image gallery section with a heading and a grid of 6 image "
        "placeholders (colored rectangles with rounded corners). Use a "
        "responsive grid: 3 columns on desktop, 2 on tablet, 1 on mobile. "
        "Add subtle hover effects on each tile."
    ),
    "contact": (
        "Add a contact section with a heading, subtitle, and a form. Include "
        "fields for name, email, subject (optional), and message (textarea). "
        "Add a submit button. Optionally place contact info (email, phone, "
        "address) on the side. Use a two-column layout on desktop that stacks "
        "on mobile."
    ),
    "faq": (
        "Add an FAQ section with a heading and 5-6 question/answer pairs. "
        "Style each Q&A as a clickable item with a question text and an "
        "expand/collapse indicator. Show the answer text below when expanded. "
        "Use clean borders between items."
    ),
    "team": (
        "Add a team section with a heading and a grid of 4 team member cards. "
        "Each card has a photo placeholder (colored circle with initials), "
        "the person's name, their role/title, and optional social media icon "
        "links. Use a 4-column responsive grid."
    ),
    "timeline": (
        "Add a timeline section with a heading and a vertical stack of 4-5 "
        "milestone entries. Each entry has a date/step number, a title, and "
        "a short description, aligned along a vertical connector line."
    ),
    "logos": (
        "Add a logo cloud section — a heading like 'Trusted by' followed by "
        "a row of 5-6 monochrome logo placeholders (use simple SVGs or "
        "grey wordmark rectangles). Space them evenly and center the row."
    ),
    "video": (
        "Add a video section with a heading, a short description, and a "
        "responsive 16:9 video embed placeholder (a dark aspect-ratio "
        "container with a centered play-button icon)."
    ),
    "subscribe": (
        "Add a newsletter signup section. Include a heading like 'Stay "
        "Updated', a short description, and an email input with a subscribe "
        "button inline. Add a small privacy note below. Center everything "
        "with a moderate max width."
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_section_kinds() -> list[dict[str, str]]:
    """Return the closed set of section kinds for the palette UI.

    Each entry: ``{id, name, category, description}``. Frontend keys off
    ``id`` when the user picks a kind and posts it back as ``template_id``.
    """
    return [dict(k) for k in _KINDS]


def _find_kind(kind: str) -> dict[str, str] | None:
    for k in _KINDS:
        if k["id"] == kind or k["category"] == kind:
            return k
    return None


def _palette_hint(brief: dict | None) -> str:
    """Extract a short palette hint from a brief-shaped dict.

    Kept dict-shaped (not typed against ``DesignBrief``) so the helper
    can accept either a raw JSON blob or a model-dumped brief without
    dragging the pydantic schema into every caller.
    """
    if not isinstance(brief, dict):
        return ""
    palette = brief.get("palette") or {}
    brand = palette.get("brand")
    accent = palette.get("accent")
    canvas = palette.get("surface_bg") or palette.get("canvas")
    parts: list[str] = []
    if brand:
        parts.append(f"brand {brand}")
    if accent:
        parts.append(f"accent {accent}")
    if canvas:
        parts.append(f"canvas {canvas}")
    if not parts:
        return ""
    return "Palette: " + ", ".join(parts) + "."


def _stance_hint(brief: dict | None) -> str:
    """One-line rendering of the brief's visual stance, when present."""
    if not isinstance(brief, dict):
        return ""
    ident = brief.get("identity") or {}
    stance = ident.get("visual_stance") or {}
    if not isinstance(stance, dict):
        return ""
    bits: list[str] = []
    for key in ("temperature", "shape_vocab", "hue_range"):
        v = stance.get(key)
        if isinstance(v, str) and v.strip():
            bits.append(v.strip())
    principles = stance.get("principles") or []
    if isinstance(principles, list):
        bits.extend(str(p).strip() for p in principles if p and str(p).strip())
    if not bits:
        return ""
    return "Visual stance: " + ", ".join(bits) + "."


def author_section(
    kind: str,
    page_context: dict[str, Any] | None = None,
    brief: dict | None = None,
) -> dict[str, Any]:
    """Return an authoring recipe for a section of ``kind``.

    Args:
        kind: The section kind id (``hero``, ``features``, ...). If an
            unknown id is passed, a generic ``content`` recipe is used
            so downstream never crashes on a stale template-id request.
        page_context: Ignored today, reserved for future page-aware
            authoring (e.g. reading the current page's dominant color
            or existing section pattern). Kept in the signature so
            callers can start passing it without a follow-up migration.
        brief: A brief-shaped dict (typically ``contracts/brief.json``
            deserialized). When present, its palette + visual stance
            is spliced into the prompt so the generated section reads
            as part of THIS app.

    Returns:
        ``{id, name, category, description, prompt}``. ``prompt`` is
        the instruction to feed to the ``code_editor`` agent.
    """
    entry = _find_kind(kind)
    if entry is None:
        entry = {
            "id": kind or "content",
            "name": "Content",
            "category": "content",
            "description": f"Add a new content section ({kind})",
        }
        recipe = (
            "Add a new content section with a heading, 2-3 paragraphs of "
            "placeholder text, and an optional image placeholder. Use "
            "comfortable reading width. Keep typography hierarchy clean."
        )
    else:
        recipe = _RECIPES.get(entry["id"], _RECIPES.get(entry["category"], ""))

    palette_hint = _palette_hint(brief)
    stance_hint = _stance_hint(brief)
    tail = " ".join(bit for bit in (palette_hint, stance_hint) if bit)
    prompt = recipe if not tail else f"{recipe}\n\n{tail}"

    return {
        "id": entry["id"],
        "name": entry["name"],
        "category": entry["category"],
        "description": entry["description"],
        "prompt": prompt,
    }


__all__ = ["list_section_kinds", "author_section"]

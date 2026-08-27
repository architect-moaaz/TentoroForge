"""Cross-domain visual anti-patterns that every generated app should avoid.

These are the "AI-generated design cluster" defaults — cream + terracotta,
Inter everywhere, purple-to-blue gradient hero, etc. They're a house-style
lint rule (not per-domain intelligence): every brief inherits them.

Extracted from ``services.design_brief_anchors`` in Spec A Slice 7 so the
anchors module can be deleted while the lint rule survives. Adding to this
list is a considered decision — never remove one without eyeballing what
that AI-default cluster looks like on 3+ apps.
"""
from __future__ import annotations


BASE_ANTI_PATTERNS: list[str] = [
    "warm_cream_plus_terracotta",
    "purple_to_blue_gradient_hero",
    "inter_everywhere",
    "cream_serif_over_beige",
    "everything_centered",
    "rounded_lg_uniformly",
    "emoji_as_section_markers",
    "dashboard_dark_blue_default",
]


__all__ = ["BASE_ANTI_PATTERNS"]

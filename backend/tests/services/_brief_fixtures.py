"""Shared inline DesignBrief fixtures for the test suite.

Replaces the old ``ANCHORS["Healthcare"]`` import pattern from
``services.design_brief_anchors``. Since Spec A Slice 7 removed the
per-domain hand-authored anchors (they were the same anti-pattern as
per-industry recipes), tests that need a valid brief now use these
inline fixtures instead.
"""
from __future__ import annotations

from schemas.design_brief import DesignBrief


def healthcare_brief() -> DesignBrief:
    """A healthcare-shaped brief for tests that need a plausible palette
    and typography. Kept small — no signature moves beyond the minimum
    the schema requires."""
    return DesignBrief.model_validate({
        "identity": {
            "domain": "Healthcare",
            "register": ["calm", "trustworthy"],
            "voice": "warm_precise",
            "modes": ["light", "dark"],
        },
        "palette": {
            "brand": "#2E5C7E",
            "accent": "#0F8A6A",
            "neutrals_base": "#F5F7FA",
            "neutrals_tint": "cool",
            "surface_bg": "#FAFCFD",
            "surface_elevated": "#FFFFFF",
            "foreground_primary": "#1A2634",
            "foreground_muted": "#5A6B7A",
        },
        "typography": {
            "display_family": "IBM Plex Sans",
            "display_weights": [500, 700],
            "body_family": "IBM Plex Sans",
            "body_weights": [400, 500, 600],
            "utility_family": "IBM Plex Mono",
            "scale": "conservative_1.20",
        },
        "layout": {
            "density": "comfortable",
            "radius": "soft_8",
            "grid": "12col",
        },
        "signature_moves": [
            {"kind": "warm_serif_h1", "detail": "generous line-height display heading"},
        ],
        "anti_patterns": ["medical_blue_default", "sterile_white_grid"],
    })


__all__ = ["healthcare_brief"]

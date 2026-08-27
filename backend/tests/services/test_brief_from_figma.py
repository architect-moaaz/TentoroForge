"""Tests for services.brief_from_figma — deterministic Figma context →
DesignBrief mapper with locked_fields populated.

Spec A Slice 6a. Pure module, no LLM.
"""
from __future__ import annotations

import pytest

from services.brief_from_figma import brief_from_figma, BriefFromFigmaError


def _figma_ctx_property_mgmt() -> dict:
    """Simulated services.figma_context output for a property-mgmt Figma.

    Mimics the shape of figma-context.json.design_tokens: sorted colors,
    fonts, font sizes, border radii, spacings — pre-deduped.
    """
    return {
        "design_tokens": {
            "colors": [
                "#2D5A8E",  # frequent brand
                "#2D5A8E",
                "#2D5A8E",
                "#E8A020",  # accent (fewer occurrences)
                "#E8A020",
                "#F5F7FA",  # surface bg
                "#FFFFFF",  # surface elevated
                "#111827",  # foreground primary
                "#4B5A6E",  # foreground muted
                "#F0F2F5",  # neutral base
            ],
            "fonts": ["DM Sans", "IBM Plex Sans", "IBM Plex Mono"],
            "font_sizes": [12, 14, 16, 20, 24, 32],
            "border_radii": [2, 4],
            "spacings": [4, 8, 12, 16, 24, 32],
        },
    }


# --------------------------------------------------------------------------- #
# Top-level shape
# --------------------------------------------------------------------------- #


class TestReturnsDesignBrief:
    def test_returns_a_designbrief(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Property Management")
        assert brief.identity.domain == "Property Management"

    def test_source_is_figma(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Property Management")
        assert brief.identity.source == "figma"

    def test_empty_context_raises(self):
        with pytest.raises(BriefFromFigmaError):
            brief_from_figma({}, domain="Test")

    def test_no_colors_raises(self):
        # Need at least one non-neutral color to pick brand.
        ctx = {"design_tokens": {"colors": ["#808080"], "fonts": ["Inter"], "font_sizes": [16], "border_radii": [4], "spacings": [8]}}
        with pytest.raises(BriefFromFigmaError):
            brief_from_figma(ctx, domain="Test")


# --------------------------------------------------------------------------- #
# Palette extraction
# --------------------------------------------------------------------------- #


class TestPalette:
    def test_brand_is_most_frequent_non_neutral(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert brief.palette.brand == "#2D5A8E"

    def test_accent_is_second_non_neutral(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert brief.palette.accent == "#E8A020"

    def test_palette_hexes_are_uppercase(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        for hex_val in (
            brief.palette.brand, brief.palette.accent,
            brief.palette.neutrals_base, brief.palette.surface_bg,
            brief.palette.surface_elevated, brief.palette.foreground_primary,
            brief.palette.foreground_muted,
        ):
            assert hex_val == hex_val.upper(), hex_val

    def test_accent_falls_back_when_only_one_non_neutral(self):
        # If Figma only had one non-neutral hex, accent falls back to brand.
        ctx = {"design_tokens": {
            "colors": ["#2D5A8E", "#FFFFFF", "#808080"],
            "fonts": ["Inter"], "font_sizes": [16],
            "border_radii": [4], "spacings": [8],
        }}
        brief = brief_from_figma(ctx, domain="Test")
        assert brief.palette.brand == "#2D5A8E"
        assert brief.palette.accent == "#2D5A8E"


# --------------------------------------------------------------------------- #
# Typography extraction
# --------------------------------------------------------------------------- #


class TestTypography:
    def test_display_family_from_figma(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        # First font wins for display; second for body.
        assert brief.typography.display_family == "DM Sans"

    def test_body_family_from_figma(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert brief.typography.body_family == "IBM Plex Sans"

    def test_utility_family_optional(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert brief.typography.utility_family == "IBM Plex Mono"

    def test_single_font_all_slots_same(self):
        ctx = {"design_tokens": {
            "colors": ["#2D5A8E", "#FFFFFF"],
            "fonts": ["Inter"], "font_sizes": [16],
            "border_radii": [4], "spacings": [8],
        }}
        brief = brief_from_figma(ctx, domain="Test")
        assert brief.typography.display_family == "Inter"
        assert brief.typography.body_family == "Inter"

    def test_no_fonts_falls_back(self):
        # Figma with zero declared fonts — brief still validates.
        ctx = {"design_tokens": {
            "colors": ["#2D5A8E", "#FFFFFF"],
            "fonts": [], "font_sizes": [16],
            "border_radii": [4], "spacings": [8],
        }}
        brief = brief_from_figma(ctx, domain="Test")
        # System default is acceptable.
        assert brief.typography.body_family


# --------------------------------------------------------------------------- #
# Layout — radius snap
# --------------------------------------------------------------------------- #


class TestLayoutRadius:
    def test_small_radius_snaps_to_sharp_2(self):
        ctx = _figma_ctx_property_mgmt()
        ctx["design_tokens"]["border_radii"] = [2, 4]
        brief = brief_from_figma(ctx, domain="Test")
        assert brief.layout.radius.value == "sharp_2"

    def test_medium_radius_snaps_to_soft_8(self):
        ctx = _figma_ctx_property_mgmt()
        ctx["design_tokens"]["border_radii"] = [8, 12]
        brief = brief_from_figma(ctx, domain="Test")
        assert brief.layout.radius.value == "soft_8"

    def test_huge_radius_snaps_to_pill(self):
        ctx = _figma_ctx_property_mgmt()
        ctx["design_tokens"]["border_radii"] = [999, 9999]
        brief = brief_from_figma(ctx, domain="Test")
        assert brief.layout.radius.value == "pill"


# --------------------------------------------------------------------------- #
# Locked fields — the Figma fidelity contract
# --------------------------------------------------------------------------- #


class TestLockedFields:
    def test_brand_is_locked(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert "brand" in brief.palette.locked_fields

    def test_accent_is_locked(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert "accent" in brief.palette.locked_fields

    def test_surface_bg_is_locked(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert "surface_bg" in brief.palette.locked_fields

    def test_display_family_is_locked(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert "display_family" in brief.typography.locked_fields

    def test_body_family_is_locked(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert "body_family" in brief.typography.locked_fields

    def test_radius_is_locked(self):
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert "radius" in brief.layout.locked_fields


# --------------------------------------------------------------------------- #
# Signature moves — empty for Figma (the Figma IS the signature)
# --------------------------------------------------------------------------- #


class TestSignatureMoves:
    def test_stub_signature_move_present(self):
        # Schema requires at least 1 signature move — brief_from_figma
        # inserts a minimal "figma_source" stub since a Figma reference
        # is itself the signature.
        brief = brief_from_figma(_figma_ctx_property_mgmt(), domain="Test")
        assert len(brief.signature_moves) >= 1


# --------------------------------------------------------------------------- #
# Deterministic
# --------------------------------------------------------------------------- #


class TestDeterministic:
    def test_same_input_same_output(self):
        ctx = _figma_ctx_property_mgmt()
        a = brief_from_figma(ctx, domain="Test").model_dump_json()
        b = brief_from_figma(ctx, domain="Test").model_dump_json()
        assert a == b

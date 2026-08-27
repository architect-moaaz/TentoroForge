"""End-to-end byte-exact tests for the Figma-canonical chain.

Spec A Slice 6e: for any Figma-sourced brief, the design-spec output
of ``brief_to_design_spec`` must preserve the Figma palette + typography
byte-for-byte. No shade math, no rounding, no LLM interpretation between
Figma source and rendered CSS variable.

Chain under test:
    figma_ctx  →  brief_from_figma  →  brief_to_design_spec  →  {primary, accent, ...}

The guarantee is: the exact hex string that came out of Figma is what
the generated app's ``--primary`` CSS variable holds.
"""
from __future__ import annotations

from services.brief_from_figma import brief_from_figma
from services.brief_to_design_spec import brief_to_design_spec


def _property_mgmt_figma_ctx() -> dict:
    return {
        "design_tokens": {
            "colors": [
                "#2D5A8E", "#2D5A8E", "#2D5A8E",  # brand (most frequent)
                "#E8A020", "#E8A020",              # accent
                "#F5F7FA", "#FFFFFF",              # surfaces (light neutrals)
                "#111111", "#555555", "#F0F0F0",   # neutrals (R=G=B → definitely neutral)
            ],
            "fonts": ["DM Sans", "IBM Plex Sans", "IBM Plex Mono"],
            "font_sizes": [12, 14, 16, 20, 24, 32],
            "border_radii": [2, 4],
            "spacings": [4, 8, 12, 16, 24, 32],
        },
    }


class TestByteExactPalette:
    def test_brand_hex_survives_end_to_end(self):
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        spec = brief_to_design_spec(brief)
        # The flat legacy key is what shell_templates / globals_writer read.
        assert spec["colorPalette"]["primary"] == "#2D5A8E"
        # And the raw brief.palette.brand IS the source of truth.
        assert brief.palette.brand == "#2D5A8E"

    def test_accent_hex_survives_end_to_end(self):
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        spec = brief_to_design_spec(brief)
        assert spec["colorPalette"]["accent"] == "#E8A020"

    def test_surface_bg_survives_end_to_end(self):
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        spec = brief_to_design_spec(brief)
        assert spec["colorPalette"]["background"] == brief.palette.surface_bg
        # And that value came from a neutral in the Figma source.
        assert brief.palette.surface_bg in ["#F5F7FA", "#FFFFFF", "#F0F0F0"]

    def test_foreground_primary_survives_end_to_end(self):
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        spec = brief_to_design_spec(brief)
        assert spec["colorPalette"]["textPrimary"] == brief.palette.foreground_primary
        # Darkest neutral from Figma source.
        assert brief.palette.foreground_primary == "#111111"

    def test_shade_500_preserves_base_hex(self):
        # The shade ladder derives 50..950 from the base by lightening/darkening,
        # but the 500 stop MUST equal the base hex byte-exact (Figma-fidelity).
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        spec = brief_to_design_spec(brief)
        assert spec["colorPalette"]["_scales"]["brand"]["500"] == "#2D5A8E"
        assert spec["colorPalette"]["_scales"]["accent"]["500"] == "#E8A020"


class TestByteExactTypography:
    def test_body_family_survives_end_to_end(self):
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        spec = brief_to_design_spec(brief)
        # Flat legacy key: read by _register_from_spec_fonts.
        assert spec["typography"]["fontFamily"] == "IBM Plex Sans"
        # Nested: read by newer consumers.
        assert spec["typography"]["body"]["family"] == "IBM Plex Sans"

    def test_display_family_survives_end_to_end(self):
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        spec = brief_to_design_spec(brief)
        assert spec["typography"]["headingFontFamily"] == "DM Sans"
        assert spec["typography"]["display"]["family"] == "DM Sans"


class TestByteExactRadius:
    def test_radius_reflects_figma_source(self):
        # Small Figma radii (2, 4) → sharp_2 → --radius = 2px.
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        spec = brief_to_design_spec(brief)
        assert spec["borderRadius"]["md"] == "2px"

    def test_pill_radius_reflects_huge_figma_source(self):
        ctx = _property_mgmt_figma_ctx()
        ctx["design_tokens"]["border_radii"] = [999]
        brief = brief_from_figma(ctx, domain="Test")
        spec = brief_to_design_spec(brief)
        # pill → md 999 px per _radius_scale.
        assert spec["borderRadius"]["md"] == "999px"


class TestSourceMarking:
    def test_figma_brief_marks_source(self):
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        assert brief.identity.source == "figma"

    def test_locked_fields_populated_end_to_end(self):
        brief = brief_from_figma(_property_mgmt_figma_ctx(), domain="Test")
        # These are the fields whose values reach CSS byte-exact — the
        # design-spec must not silently mutate them via Smith or edit_brief.
        assert "brand" in brief.palette.locked_fields
        assert "accent" in brief.palette.locked_fields
        assert "display_family" in brief.typography.locked_fields
        assert "body_family" in brief.typography.locked_fields
        assert "radius" in brief.layout.locked_fields


class TestDeterministic:
    def test_full_chain_is_deterministic(self):
        ctx = _property_mgmt_figma_ctx()
        spec_a = brief_to_design_spec(brief_from_figma(ctx, domain="Test"))
        spec_b = brief_to_design_spec(brief_from_figma(ctx, domain="Test"))
        assert spec_a == spec_b

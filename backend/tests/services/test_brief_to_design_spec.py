"""Tests for services.brief_to_design_spec — deterministic
DesignBrief → design-spec dict mapping.

Spec A Slice 1. Pure module, no LLM, no disk I/O.
"""
from __future__ import annotations

import pytest

from schemas.design_brief import (
    DesignBrief,
    Identity,
    Layout,
    Palette,
    SignatureMove,
    Typography,
)
from services.brief_to_design_spec import (
    brief_to_design_spec,
    _default_semantic_colors,
    _derive_neutrals,
    _radius_scale,
    _resolve_scale,
    _shade_scale,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _brief(**overrides) -> DesignBrief:
    """Property Management-shaped brief — cool navy/amber, IBM Plex, sharp corners."""
    defaults = dict(
        identity=Identity(
            domain="Property Management",
            register=["structured", "operational"],
            voice="formal_technical",
            modes=["light", "dark"],
        ),
        palette=Palette(
            brand="#2D5A8E",
            accent="#E8A020",
            neutrals_base="#F0F2F5",
            neutrals_tint="cool",
            surface_bg="#F5F7FA",
            surface_elevated="#FFFFFF",
            foreground_primary="#111827",
            foreground_muted="#4B5A6E",
        ),
        typography=Typography(
            display_family="DM Sans",
            display_weights=[500, 700],
            body_family="IBM Plex Sans",
            body_weights=[400, 500, 600],
            utility_family="IBM Plex Mono",
            scale="tight_1.15",
        ),
        layout=Layout(
            density="compact",
            radius="sharp_2",
            grid="sidebar_plus_12col_main",
            whitespace="restrained_with_section_breaks",
        ),
        signature_moves=[
            SignatureMove(kind="ledger_row", detail="4px left-border in occupancy color"),
        ],
        anti_patterns=["dashboard_dark_blue_default", "inter_everywhere"],
    )
    defaults.update(overrides)
    return DesignBrief(**defaults)


# --------------------------------------------------------------------------- #
# Top-level shape
# --------------------------------------------------------------------------- #


class TestTopLevelShape:
    def test_returns_dict_with_expected_top_keys(self):
        spec = brief_to_design_spec(_brief())
        # Slice 4: legacy compat adds borderRadius at top level.
        # Spec C4/C8: adds motion + responsive.
        assert set(spec.keys()) == {
            "colorPalette", "typography", "layout", "modes",
            "borderRadius", "motion", "responsive",
        }

    def test_color_palette_has_flat_legacy_keys(self):
        spec = brief_to_design_spec(_brief())
        cp = spec["colorPalette"]
        # Legacy flat keys — what shell_templates/globals_writer expect.
        for k in ("primary", "accent", "background", "surface", "border",
                  "muted", "textPrimary", "textSecondary",
                  "sidebarBg", "sidebarText",
                  "success", "warning", "error", "info"):
            assert k in cp, f"missing legacy key {k!r}"

    def test_color_palette_has_scales_subkey(self):
        spec = brief_to_design_spec(_brief())
        assert "_scales" in spec["colorPalette"]
        assert set(spec["colorPalette"]["_scales"].keys()) == {"brand", "accent", "neutral"}

    def test_typography_has_expected_subkeys(self):
        spec = brief_to_design_spec(_brief())
        # Nested + flat legacy shape.
        for k in ("display", "body", "utility", "scale",
                  "fontFamily", "headingFontFamily", "bodyWeight", "headingWeight"):
            assert k in spec["typography"], f"missing typography key {k!r}"

    def test_layout_has_expected_subkeys(self):
        spec = brief_to_design_spec(_brief())
        assert set(spec["layout"].keys()) == {"density", "radius", "grid"}


# --------------------------------------------------------------------------- #
# _shade_scale
# --------------------------------------------------------------------------- #


class TestShadeScale:
    def test_returns_all_tailwind_stops(self):
        scale = _shade_scale("#2D5A8E")
        assert set(scale.keys()) == {"50", "100", "200", "300", "400", "500",
                                     "600", "700", "800", "900", "950"}

    def test_500_is_the_base_hex(self):
        # The base hex becomes the 500 shade (mid-scale).
        scale = _shade_scale("#2D5A8E")
        assert scale["500"] == "#2D5A8E"

    def test_all_values_are_uppercase_7char_hex(self):
        scale = _shade_scale("#2D5A8E")
        for shade, hex_val in scale.items():
            assert hex_val.startswith("#"), f"{shade} missing #: {hex_val}"
            assert len(hex_val) == 7, f"{shade} wrong length: {hex_val}"
            assert hex_val == hex_val.upper(), f"{shade} not uppercase: {hex_val}"

    def test_50_is_lighter_than_500(self):
        scale = _shade_scale("#2D5A8E")
        # 50 (lightest) should have higher average channel value than 500.
        def _avg(h: str) -> float:
            return sum(int(h[i:i+2], 16) for i in (1, 3, 5)) / 3
        assert _avg(scale["50"]) > _avg(scale["500"])

    def test_950_is_darker_than_500(self):
        scale = _shade_scale("#2D5A8E")
        def _avg(h: str) -> float:
            return sum(int(h[i:i+2], 16) for i in (1, 3, 5)) / 3
        assert _avg(scale["950"]) < _avg(scale["500"])

    def test_monotonically_darker_from_50_to_950(self):
        scale = _shade_scale("#2D5A8E")
        stops = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"]
        def _avg(h: str) -> float:
            return sum(int(h[i:i+2], 16) for i in (1, 3, 5)) / 3
        prev = _avg(scale[stops[0]])
        for s in stops[1:]:
            cur = _avg(scale[s])
            assert cur <= prev, f"stop {s} ({cur}) not <= prev ({prev})"
            prev = cur

    def test_lowercase_input_normalized_to_upper(self):
        scale = _shade_scale("#2d5a8e")
        assert scale["500"] == "#2D5A8E"

    def test_short_hex_rejected(self):
        with pytest.raises(ValueError):
            _shade_scale("#2D5A8")


# --------------------------------------------------------------------------- #
# _derive_neutrals — tint-aware
# --------------------------------------------------------------------------- #


class TestDeriveNeutrals:
    def test_returns_shade_scale(self):
        palette = _brief().palette
        neutrals = _derive_neutrals(palette)
        assert set(neutrals.keys()) == {"50", "100", "200", "300", "400", "500",
                                        "600", "700", "800", "900", "950"}

    def test_cool_tint_biases_blue_channel(self):
        palette = _brief(palette=Palette(
            brand="#2D5A8E", accent="#E8A020",
            neutrals_base="#808080",
            neutrals_tint="cool",
            surface_bg="#F5F7FA", surface_elevated="#FFFFFF",
            foreground_primary="#111827", foreground_muted="#4B5A6E",
        )).palette
        neutrals = _derive_neutrals(palette)
        # Cool tint: blue channel should be >= red channel at mid-shade.
        mid = neutrals["500"]
        r, g, b = int(mid[1:3], 16), int(mid[3:5], 16), int(mid[5:7], 16)
        assert b >= r, f"cool tint should have b>=r, got {mid} (r={r},b={b})"

    def test_warm_tint_biases_red_channel(self):
        palette = _brief(palette=Palette(
            brand="#2D5A8E", accent="#E8A020",
            neutrals_base="#808080",
            neutrals_tint="warm",
            surface_bg="#F5F7FA", surface_elevated="#FFFFFF",
            foreground_primary="#111827", foreground_muted="#4B5A6E",
        )).palette
        neutrals = _derive_neutrals(palette)
        mid = neutrals["500"]
        r, g, b = int(mid[1:3], 16), int(mid[3:5], 16), int(mid[5:7], 16)
        assert r >= b, f"warm tint should have r>=b, got {mid} (r={r},b={b})"

    def test_neutral_tint_has_balanced_channels(self):
        palette = _brief(palette=Palette(
            brand="#2D5A8E", accent="#E8A020",
            neutrals_base="#808080",
            neutrals_tint="neutral",
            surface_bg="#F5F7FA", surface_elevated="#FFFFFF",
            foreground_primary="#111827", foreground_muted="#4B5A6E",
        )).palette
        neutrals = _derive_neutrals(palette)
        mid = neutrals["500"]
        r, g, b = int(mid[1:3], 16), int(mid[3:5], 16), int(mid[5:7], 16)
        assert abs(r - b) <= 4, f"neutral should have balanced channels, got {mid}"


# --------------------------------------------------------------------------- #
# _default_semantic_colors — universal, not domain-specific
# --------------------------------------------------------------------------- #


class TestSemanticColors:
    def test_has_all_semantic_keys(self):
        colors = _default_semantic_colors()
        assert set(colors.keys()) == {"success", "warning", "error", "info"}

    def test_all_are_hex(self):
        colors = _default_semantic_colors()
        for k, v in colors.items():
            assert v.startswith("#") and len(v) == 7, f"{k}={v} not valid hex"


# --------------------------------------------------------------------------- #
# Typography passthrough
# --------------------------------------------------------------------------- #


class TestTypography:
    def test_display_family_passthrough(self):
        spec = brief_to_design_spec(_brief())
        assert spec["typography"]["display"]["family"] == "DM Sans"

    def test_display_weights_passthrough(self):
        spec = brief_to_design_spec(_brief())
        assert spec["typography"]["display"]["weights"] == [500, 700]

    def test_body_family_passthrough(self):
        spec = brief_to_design_spec(_brief())
        assert spec["typography"]["body"]["family"] == "IBM Plex Sans"

    def test_body_weights_passthrough(self):
        spec = brief_to_design_spec(_brief())
        assert spec["typography"]["body"]["weights"] == [400, 500, 600]

    def test_utility_family_when_present(self):
        spec = brief_to_design_spec(_brief())
        assert spec["typography"]["utility"]["family"] == "IBM Plex Mono"

    def test_utility_family_null_when_absent(self):
        brief = _brief(typography=Typography(
            display_family="DM Sans", body_family="IBM Plex Sans",
            utility_family=None, scale="tight_1.15",
        ))
        spec = brief_to_design_spec(brief)
        assert spec["typography"]["utility"]["family"] is None


# --------------------------------------------------------------------------- #
# _resolve_scale
# --------------------------------------------------------------------------- #


class TestResolveScale:
    def test_returns_dict_with_type_stops(self):
        scale = _resolve_scale("conservative_1.20")
        # Should have at least body + heading stops.
        assert "body" in scale
        assert "h1" in scale
        assert "h2" in scale
        assert "h3" in scale
        assert "caption" in scale

    def test_parses_ratio_from_name(self):
        scale = _resolve_scale("conservative_1.20")
        # Ratio is 1.20; h1 = body × 1.20 × 1.20 × 1.20 (three steps up)
        body_px = float(scale["body"].replace("rem", "")) * 16  # 1rem = 16px
        h1_px = float(scale["h1"].replace("rem", "")) * 16
        # h1 should be meaningfully larger than body
        assert h1_px > body_px * 1.5

    def test_tight_scale_smaller_than_spacious(self):
        tight = _resolve_scale("tight_1.15")
        spacious = _resolve_scale("spacious_1.333")
        tight_h1 = float(tight["h1"].replace("rem", ""))
        spacious_h1 = float(spacious["h1"].replace("rem", ""))
        assert tight_h1 < spacious_h1

    def test_unknown_named_scale_falls_back_to_conservative(self):
        # If the scale string is unrecognizable, don't crash — pick a sensible default.
        scale = _resolve_scale("garbage_string")
        assert "body" in scale
        assert "h1" in scale

    def test_arbitrary_ratio_from_name(self):
        # Any name of the form "<label>_<ratio>" should parse the ratio.
        scale = _resolve_scale("custom_1.4")
        body_rem = float(scale["body"].replace("rem", ""))
        h3_rem = float(scale["h3"].replace("rem", ""))
        # h3 = body × 1.4
        assert abs(h3_rem - body_rem * 1.4) < 0.05


# --------------------------------------------------------------------------- #
# _radius_scale
# --------------------------------------------------------------------------- #


class TestRadiusScale:
    def test_sharp_2_returns_small_px(self):
        r = _radius_scale("sharp_2")
        assert r["sm"] == 2
        assert r["md"] == 2
        assert r["lg"] <= 4

    def test_soft_8_returns_medium_px(self):
        r = _radius_scale("soft_8")
        assert r["sm"] >= 2
        assert r["md"] == 8
        assert r["lg"] >= 8

    def test_pill_returns_large_px(self):
        r = _radius_scale("pill")
        assert r["md"] >= 999

    def test_returns_all_size_keys(self):
        r = _radius_scale("sharp_2")
        assert set(r.keys()) >= {"sm", "md", "lg"}


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #


class TestModes:
    def test_light_always_true(self):
        brief = _brief(identity=Identity(
            domain="Test", register=["calm"], voice="warm_precise",
            modes=["light"],
        ))
        spec = brief_to_design_spec(brief)
        assert spec["modes"]["light"] is True

    def test_dark_true_when_declared(self):
        brief = _brief(identity=Identity(
            domain="Test", register=["calm"], voice="warm_precise",
            modes=["light", "dark"],
        ))
        spec = brief_to_design_spec(brief)
        assert spec["modes"]["dark"] is True

    def test_dark_false_when_not_declared(self):
        brief = _brief(identity=Identity(
            domain="Test", register=["calm"], voice="warm_precise",
            modes=["light"],
        ))
        spec = brief_to_design_spec(brief)
        assert spec["modes"]["dark"] is False


# --------------------------------------------------------------------------- #
# Round-trip: brief brand hex preserved as colorPalette.brand.500
# --------------------------------------------------------------------------- #


class TestRoundTrip:
    def test_brand_hex_preserved_at_primary(self):
        # Legacy consumer path (shell_templates.extract_tokens).
        spec = brief_to_design_spec(_brief())
        assert spec["colorPalette"]["primary"] == "#2D5A8E"

    def test_brand_hex_preserved_in_scale_500(self):
        # Future-consumer path — full shade ladder under _scales.
        spec = brief_to_design_spec(_brief())
        assert spec["colorPalette"]["_scales"]["brand"]["500"] == "#2D5A8E"

    def test_accent_hex_preserved(self):
        spec = brief_to_design_spec(_brief())
        assert spec["colorPalette"]["accent"] == "#E8A020"
        assert spec["colorPalette"]["_scales"]["accent"]["500"] == "#E8A020"

    def test_sidebar_bg_derived_from_brand_dark(self):
        # This is the Slice 4 fix — no more #1A2940 fallback for
        # brief-canonical projects; sidebar reads as a coherent
        # dark variant of the brand.
        spec = brief_to_design_spec(_brief())
        sidebar_bg = spec["colorPalette"]["sidebarBg"]
        brand_900 = spec["colorPalette"]["_scales"]["brand"]["900"]
        assert sidebar_bg == brand_900
        # Sanity: it IS dark (avg channel value low).
        r, g, b = int(sidebar_bg[1:3], 16), int(sidebar_bg[3:5], 16), int(sidebar_bg[5:7], 16)
        assert (r + g + b) / 3 < 80, f"{sidebar_bg} should be dark"

    def test_layout_passthrough(self):
        spec = brief_to_design_spec(_brief())
        assert spec["layout"]["density"] == "compact"
        assert spec["layout"]["grid"] == "sidebar_plus_12col_main"

    def test_borderradius_present_for_globals_writer(self):
        # _rewrite_globals_root reads spec.borderRadius.md → --radius CSS var.
        spec = brief_to_design_spec(_brief())
        assert "borderRadius" in spec
        assert spec["borderRadius"]["md"] == "2px"  # sharp_2

    def test_deterministic_same_input_same_output(self):
        # Pure function — same input, same output byte-for-byte.
        b = _brief()
        spec1 = brief_to_design_spec(b)
        spec2 = brief_to_design_spec(b)
        assert spec1 == spec2


class TestMotionAndResponsive:
    def test_motion_defaults_pass_through(self):
        spec = brief_to_design_spec(_brief())
        assert spec["motion"]["durationFastMs"] == 120
        assert spec["motion"]["durationMediumMs"] == 240
        assert spec["motion"]["durationSlowMs"] == 480
        assert spec["motion"]["reduceMotionRespect"] is True
        assert spec["motion"]["easeOut"].startswith("cubic-bezier")

    def test_motion_custom_values_pass_through_byte_exact(self):
        """Spec C4 — brief-authored numbers reach CSS verbatim, not bucketed."""
        from schemas.design_brief import Motion
        b = _brief()
        b.motion = Motion(
            duration_fast_ms=180, duration_medium_ms=320, duration_slow_ms=600,
            ease_out="cubic-bezier(0.1, 0.9, 0.2, 1.0)",
            ease_in_out="cubic-bezier(0.5, 0.0, 0.5, 1.0)",
            reduce_motion_respect=False,
        )
        spec = brief_to_design_spec(b)
        assert spec["motion"]["durationFastMs"] == 180
        assert spec["motion"]["durationMediumMs"] == 320
        assert spec["motion"]["durationSlowMs"] == 600
        assert spec["motion"]["easeOut"] == "cubic-bezier(0.1, 0.9, 0.2, 1.0)"
        assert spec["motion"]["reduceMotionRespect"] is False

    def test_responsive_defaults(self):
        spec = brief_to_design_spec(_brief())
        assert spec["responsive"]["primaryFormFactor"] == "desktop"
        assert spec["responsive"]["breakpointsPriority"] == ["desktop", "tablet", "mobile"]
        assert spec["responsive"]["layoutVariants"] == []

    def test_responsive_mobile_first(self):
        from schemas.design_brief import Responsive
        b = _brief()
        b.responsive = Responsive(
            primary_form_factor="mobile",
            breakpoints_priority=["mobile", "tablet", "desktop"],
            layout_variants=["bottom_tabs"],
        )
        spec = brief_to_design_spec(b)
        assert spec["responsive"]["primaryFormFactor"] == "mobile"
        assert spec["responsive"]["breakpointsPriority"] == ["mobile", "tablet", "desktop"]
        assert spec["responsive"]["layoutVariants"] == ["bottom_tabs"]


class TestVisualLockOverride:
    """Slice A (2026-08-13) — visual_lock.palette + typography override
    the LLM-authored fields in the emitted design-spec."""

    def _yoga_lock_brief(self):
        from services.visual_lock_presets import WELLNESS_WARM
        b = _brief()
        b.visual_lock = WELLNESS_WARM
        return b

    def test_lock_palette_wins_over_brief_palette(self):
        spec = brief_to_design_spec(self._yoga_lock_brief())
        cp = spec["colorPalette"]
        # WELLNESS_WARM values (see visual_lock_presets.py)
        assert cp["background"] == "#F5F1E8"
        assert cp["surface"] == "#EBE5D6"
        assert cp["textPrimary"] == "#2B2E28"
        assert cp["primary"] == "#5A6B4A"     # lock.accent → CTA colour
        assert cp["accent"] == "#B8935A"      # lock.badge → highlight
        assert cp["muted"] == "#8B8578"
        assert cp["error"] == "#B85A4A"       # lock.danger override

    def test_lock_typography_wins_over_brief_families(self):
        spec = brief_to_design_spec(self._yoga_lock_brief())
        ty = spec["typography"]
        assert ty["headingFontFamily"] == "Fraunces"
        assert ty["fontFamily"] == "Inter"
        assert ty["utility"]["family"] == "JetBrains Mono"
        assert ty["display"]["family"] == "Fraunces"
        assert ty["body"]["family"] == "Inter"

    def test_empty_lock_leaves_brief_values_untouched(self):
        """Backward compat: an inactive lock (default) must produce
        BYTE-IDENTICAL output to the pre-Slice-A pipeline."""
        b = _brief()
        # b.visual_lock is default (empty) — inactive
        assert b.visual_lock.is_active() is False
        spec_no_lock = brief_to_design_spec(b)
        # Same brief values reach the spec verbatim.
        assert spec_no_lock["colorPalette"]["primary"] == b.palette.brand
        assert spec_no_lock["typography"]["headingFontFamily"] == b.typography.display_family

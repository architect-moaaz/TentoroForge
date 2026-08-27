"""Tests for design_compiler.py — color ramps + (later) field mapping."""
import pytest
from services.design_compiler import hsl_ramp, _hex_to_hsl, _hsl_to_hex


class TestHexHslRoundTrip:
    """Conversion between hex and HSL must round-trip without drift."""

    @pytest.mark.parametrize("hex_in", [
        "#3b82f6",   # Tailwind blue-500
        "#22c55e",   # Tailwind green-500
        "#ef4444",   # Tailwind red-500
        "#000000",
        "#ffffff",
    ])
    def test_hex_hsl_roundtrip(self, hex_in: str):
        h, s, l = _hex_to_hsl(hex_in)
        out = _hsl_to_hex(h, s, l)
        # Allow 1-bit drift on each channel due to rounding
        assert _hex_distance(hex_in, out) <= 3, \
            f"round-trip drift > 3 bits: {hex_in} -> hsl({h:.2f},{s:.2f},{l:.2f}) -> {out}"


class TestHslRamp:
    """Generates 11-stop color ramps from a single anchor hex."""

    def test_returns_11_stops(self):
        ramp = hsl_ramp("#3b82f6")
        assert sorted(ramp.keys(), key=int) == \
            ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"]

    def test_anchor_preserved_at_500(self):
        ramp = hsl_ramp("#3b82f6")
        assert ramp["500"].lower() == "#3b82f6"

    def test_lightness_monotonic_decreasing(self):
        """Stop 50 should be the lightest; stop 950 the darkest."""
        ramp = hsl_ramp("#3b82f6")
        lightness = [_hex_to_hsl(ramp[k])[2] for k in
                     ["50", "100", "200", "300", "400", "500",
                      "600", "700", "800", "900", "950"]]
        for i in range(1, len(lightness)):
            assert lightness[i] < lightness[i - 1], \
                f"L not monotonic at stop index {i}: {lightness}"

    def test_works_with_fintech_purple_anchor(self):
        """Purple anchor (#7c3aed) — verify ramp still spans full range."""
        ramp = hsl_ramp("#7c3aed")
        l_50 = _hex_to_hsl(ramp["50"])[2]
        l_950 = _hex_to_hsl(ramp["950"])[2]
        # Stop 50 should be very light (>0.85)
        assert l_50 > 0.85
        # Stop 950 should be very dark (<0.30)
        assert l_950 < 0.30

    def test_works_with_healthcare_green_anchor(self):
        """Green anchor (#22c55e) — same range check."""
        ramp = hsl_ramp("#22c55e")
        l_50 = _hex_to_hsl(ramp["50"])[2]
        l_950 = _hex_to_hsl(ramp["950"])[2]
        assert l_50 > 0.85
        assert l_950 < 0.30

    def test_handles_invalid_hex_gracefully(self):
        """Invalid hex should raise a clear ValueError, not silently return junk."""
        with pytest.raises(ValueError):
            hsl_ramp("not-a-color")
        with pytest.raises(ValueError):
            hsl_ramp("#zzz")


def _hex_distance(a: str, b: str) -> int:
    """Sum of absolute byte differences across the two hex values."""
    a, b = a.lstrip("#"), b.lstrip("#")
    return sum(abs(int(a[i:i+2], 16) - int(b[i:i+2], 16)) for i in (0, 2, 4))


class TestMapColorPalette:
    """_map_color_palette transforms design-spec.colorPalette → tokens.color."""

    def test_primary_anchor_produces_11_stop_ramp(self):
        from services.design_compiler import _map_color_palette
        result = _map_color_palette({"primary": "#3b82f6"})
        assert "primary" in result
        assert sorted(result["primary"].keys(), key=int) == \
            ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"]

    def test_status_colors_3_stops(self):
        from services.design_compiler import _map_color_palette
        result = _map_color_palette({
            "primary": "#3b82f6",
            "success": "#22c55e",
            "error": "#ef4444",
        })
        assert sorted(result["success"].keys()) == ["50", "500", "700"]
        assert sorted(result["error"].keys()) == ["50", "500", "700"]

    def test_surface_levels_mapped(self):
        from services.design_compiler import _map_color_palette
        result = _map_color_palette({
            "primary": "#3b82f6",
            "background": "#ffffff",
            "surface": "#fafafa",
            "surfaceHover": "#f4f4f5",
        })
        assert result["surface"]["0"] == "#ffffff"
        assert result["surface"]["1"] == "#fafafa"
        assert result["surface"]["2"] == "#f4f4f5"

    def test_text_levels_mapped(self):
        from services.design_compiler import _map_color_palette
        result = _map_color_palette({
            "primary": "#3b82f6",
            "textPrimary": "#18181b",
            "textSecondary": "#52525b",
            "textTertiary": "#a1a1aa",
        })
        assert result["text"]["primary"] == "#18181b"
        assert result["text"]["secondary"] == "#52525b"
        assert result["text"]["tertiary"] == "#a1a1aa"

    def test_sidebar_mapped(self):
        from services.design_compiler import _map_color_palette
        result = _map_color_palette({
            "primary": "#3b82f6",
            "sidebarBg": "#0f172a",
            "sidebarText": "#cbd5e1",
            "sidebarActiveItem": "#1e293b",
        })
        assert result["sidebar"]["bg"] == "#0f172a"
        assert result["sidebar"]["text"] == "#cbd5e1"
        assert result["sidebar"]["active"] == "#1e293b"


class TestMapTypography:
    def test_font_family_to_body_heading(self):
        from services.design_compiler import _map_typography
        result = _map_typography({"fontFamily": "Inter, sans-serif"})
        # The sanitizer rebuilds the stack with quoted family names (annotated
        # LLM strings like "Inter — excellent legibility" become valid CSS).
        assert result["font"]["body"] == "'Inter', sans-serif"
        # When no separate heading font, heading mirrors body
        assert result["font"]["heading"] == "'Inter', sans-serif"

    def test_font_family_prose_is_sanitized(self):
        from services.design_compiler import _map_typography
        # The exact annotated value that shipped invalid CSS in a real app.
        result = _map_typography({"fontFamily": "Inter — excellent legibility"})
        assert result["font"]["body"] == "'Inter', sans-serif"

    def test_scale_passed_through(self):
        from services.design_compiler import _map_typography
        result = _map_typography({
            "fontFamily": "Inter",
            "scale": {"h1": "2rem", "h2": "1.5rem", "h3": "1.25rem", "body": "0.875rem", "caption": "0.75rem"},
        })
        assert result["scale"]["h1"] == "2rem"
        assert result["scale"]["caption"] == "0.75rem"

    def test_heading_weight(self):
        from services.design_compiler import _map_typography
        result = _map_typography({"fontFamily": "X", "headingWeight": "700"})
        assert result["weight"]["heading"] == "700"


class TestMapSpacing:
    def test_density_normal_no_multiplier(self):
        from services.design_compiler import _map_spacing
        result = _map_spacing({"scale": "4px base: 4/8/12/16/24/32"}, density="comfortable")
        # Normal density preserves values
        assert "0" in result
        assert "1" in result

    def test_density_compact_shrinks(self):
        from services.design_compiler import _map_spacing
        normal = _map_spacing({"scale": "4px base"}, density="comfortable")
        compact = _map_spacing({"scale": "4px base"}, density="compact")
        # Compact spacing values should be smaller (numeric comparison on rem values)
        # Just check that some specific stop is smaller
        n_4 = float(normal["4"].rstrip("rem"))
        c_4 = float(compact["4"].rstrip("rem"))
        assert c_4 < n_4

    def test_density_spacious_grows(self):
        from services.design_compiler import _map_spacing
        normal = _map_spacing({"scale": "4px base"}, density="comfortable")
        spacious = _map_spacing({"scale": "4px base"}, density="spacious")
        n_4 = float(normal["4"].rstrip("rem"))
        s_4 = float(spacious["4"].rstrip("rem"))
        assert s_4 > n_4

    def test_semantic_aliases_mapped(self):
        from services.design_compiler import _map_spacing
        # Real CSS lengths pass through (sanitized); Tailwind-class prose like
        # "px-6 py-8" is DROPPED — it is not valid CSS and the browser would
        # silently discard the declaration, so runtime defaults win instead.
        result = _map_spacing({
            "pagePadding": "2rem",
            "cardPadding": "1.25rem (20px)",   # annotation stripped
            "sectionGap": "gap-6",             # tailwind prose → dropped
        }, density="comfortable")
        assert "semantic" in result
        assert result["semantic"]["page"] == "2rem"
        assert result["semantic"]["card"] == "1.25rem"
        assert "section" not in result["semantic"]

    def test_semantic_tailwind_prose_dropped_entirely(self):
        from services.design_compiler import _map_spacing
        result = _map_spacing({
            "pagePadding": "px-6 py-8",
            "cardPadding": "p-5",
        }, density="comfortable")
        # Nothing sanitizes → no semantic group at all (defaults fill in).
        assert "semantic" not in result

    def test_13_stop_scale_present(self):
        from services.design_compiler import _map_spacing
        result = _map_spacing({"scale": ""}, density="comfortable")
        numeric_stops = sorted([k for k in result.keys() if k.isdigit()], key=int)
        assert numeric_stops == ["0", "1", "2", "3", "4", "6", "8", "12", "16", "24", "32", "48", "64"]


class TestMapRadiusShadowMotion:
    def test_radius_passthrough(self):
        from services.design_compiler import _map_radius
        result = _map_radius({"sm": "0.25rem", "md": "0.5rem", "lg": "0.75rem", "xl": "1rem", "full": "9999px"})
        # radius always carries its `scale` family (drives the surface radius
        # class across Card/Button/Input); values sanitize clean.
        assert result == {"sm": "0.25rem", "md": "0.5rem", "lg": "0.75rem",
                          "xl": "1rem", "full": "9999px", "scale": "soft"}

    def test_radius_annotated_values_sanitized_and_sharp_honored(self):
        from services.design_compiler import _map_radius
        result = _map_radius({"sm": "0.5rem (8px)",
                              "full": "9999px — avatars, pills"}, scale="sharp")
        assert result["sm"] == "0.5rem"
        assert result["full"] == "9999px"
        assert result["scale"] == "sharp"

    def test_shadow_passthrough(self):
        from services.design_compiler import _map_shadow
        result = _map_shadow({
            "sm": "0 1px 2px rgba(0,0,0,0.05)",
            "md": "0 4px 12px rgba(0,0,0,0.08)",
            "lg": "0 8px 25px rgba(0,0,0,0.1)",
            "xl": "0 16px 40px rgba(0,0,0,0.12)",
        })
        assert result["sm"].startswith("0 1px")

    def test_motion_split_into_normal_fast(self):
        from services.design_compiler import _map_motion
        result = _map_motion({
            "duration": "150ms for micro, 300ms for transitions",
            "easing": "cubic-bezier(0.4, 0, 0.2, 1)",
        })
        # The mapper splits "duration" string into fast/normal entries — accept
        # any reasonable parsing as long as both are present
        assert "fast" in result["duration"]
        assert "normal" in result["duration"]
        assert result["easing"]["standard"].startswith("cubic-bezier")


class TestMapImageryStatus:
    def test_imagery_login_dashboard(self):
        from services.design_compiler import _map_imagery
        result = _map_imagery({
            "loginBackground": "https://example.com/login.jpg",
            "dashboardHero": "https://example.com/hero.jpg",
            "emptyStateStyle": "geometric",
            "iconStyle": "outline",
            "avatarStyle": "initials",
        })
        assert result["login"] == "https://example.com/login.jpg"
        assert result["dashboard"] == "https://example.com/hero.jpg"
        assert result["style"]["emptyState"] == "geometric"
        assert result["style"]["icon"] == "outline"
        assert result["style"]["avatar"] == "initials"

    def test_status_colors(self):
        from services.design_compiler import _map_status
        result = _map_status({
            "Pending": {"color": "yellow", "label": "Pending"},
            "Approved": {"color": "green", "label": "Approved"},
        })
        assert result["pending"] == "yellow"
        assert result["approved"] == "green"


import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestCompile:
    """End-to-end orchestrator: design-spec dict -> tokens.custom dict."""

    def test_fintech_compiles_without_error(self):
        from services.design_compiler import compile
        spec = json.loads((FIXTURE_DIR / "fintech-design-spec.json").read_text())
        tokens = compile(spec)
        assert isinstance(tokens, dict)

    def test_fintech_produces_full_token_tree(self):
        from services.design_compiler import compile
        spec = json.loads((FIXTURE_DIR / "fintech-design-spec.json").read_text())
        tokens = compile(spec)
        # Top-level groups
        for group in ("color", "spacing", "radius", "shadow", "typography", "motion", "imagery", "semantic"):
            assert group in tokens, f"missing tokens.{group}"

    def test_fintech_color_primary_anchor_at_500(self):
        from services.design_compiler import compile
        spec = json.loads((FIXTURE_DIR / "fintech-design-spec.json").read_text())
        tokens = compile(spec)
        # Anchor (the design-spec primary) should be at color.primary.500
        # The fintech spec uses "#1d4ed8" — check it lands at stop 500
        assert tokens["color"]["primary"]["500"] == "#1d4ed8"

    def test_healthcare_compiles_without_error(self):
        from services.design_compiler import compile
        spec = json.loads((FIXTURE_DIR / "healthcare-design-spec.json").read_text())
        tokens = compile(spec)
        assert isinstance(tokens, dict)

    def test_healthcare_density_spacious_grows_spacing(self):
        from services.design_compiler import compile
        spec = json.loads((FIXTURE_DIR / "healthcare-design-spec.json").read_text())
        tokens = compile(spec)
        # spacious density -> 1.25x multiplier
        # Stop 4 (anchor 1.0rem in defaults) -> 1.25rem
        assert tokens["spacing"]["4"] == "1.25rem"

    def test_fintech_density_compact_shrinks_spacing(self):
        from services.design_compiler import compile
        spec = json.loads((FIXTURE_DIR / "fintech-design-spec.json").read_text())
        tokens = compile(spec)
        # compact density -> 0.75x multiplier
        assert tokens["spacing"]["4"] == "0.75rem"

    def test_status_colors_lowercase_entity_names(self):
        from services.design_compiler import compile
        spec = json.loads((FIXTURE_DIR / "healthcare-design-spec.json").read_text())
        tokens = compile(spec)
        # Healthcare statusColors has Active/Critical/Stable
        assert tokens["semantic"]["status"]["active"] == "green"
        assert tokens["semantic"]["status"]["critical"] == "red"
        assert tokens["semantic"]["status"]["stable"] == "blue"

    def test_compile_handles_missing_sections_gracefully(self):
        from services.design_compiler import compile
        # Minimal spec -- only colorPalette.primary, nothing else
        tokens = compile({"colorPalette": {"primary": "#3b82f6"}})
        # Compile should not raise; returns whatever sections it could fill
        assert "color" in tokens
        # Other sections optional -- present-or-absent both OK

    def test_compile_handles_empty_input(self):
        from services.design_compiler import compile
        # Completely empty input shouldn't crash
        tokens = compile({})
        assert isinstance(tokens, dict)

    def test_compile_handles_invalid_hex_silently(self):
        """Mapper logs WARNING but doesn't raise."""
        from services.design_compiler import compile
        # Invalid hex in primary -- compile shouldn't raise
        tokens = compile({"colorPalette": {"primary": "not-a-color"}})
        assert isinstance(tokens, dict)
        # primary key may be absent (since ramp generation failed silently)
        # -- that's expected fallback behavior


class TestCompileToFile:
    """compile_to_file writes the result to disk."""

    def test_compile_to_file_writes_valid_json(self, tmp_path):
        from services.design_compiler import compile_to_file
        spec = json.loads((FIXTURE_DIR / "fintech-design-spec.json").read_text())
        out_path = tmp_path / "tokens.custom.json"
        compile_to_file(spec, str(out_path))
        assert out_path.exists()
        # Re-read and verify it parses as valid JSON
        loaded = json.loads(out_path.read_text())
        assert "color" in loaded

    def test_compile_to_file_creates_parent_dirs(self, tmp_path):
        from services.design_compiler import compile_to_file
        out_path = tmp_path / "deeply" / "nested" / "tokens.custom.json"
        compile_to_file({"colorPalette": {"primary": "#3b82f6"}}, str(out_path))
        assert out_path.exists()

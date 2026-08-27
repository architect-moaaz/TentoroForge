"""css_sanitize — regression fixtures are the EXACT prose values found in real
generated apps (g4e8ksop, u6qgw1e6, 3a9v7dj4) that browsers silently dropped."""
from services.css_sanitize import (
    extract_css_length, extract_font_stack, extract_hex, extract_letter_spacing,
    extract_ms, extract_number, extract_shadow, extract_weight,
)


class TestRealWorldPoison:
    """The exact values that shipped broken."""

    def test_radius_with_px_annotation(self):        # g4e8ksop radius.sm
        assert extract_css_length("0.5rem (8px)") == "0.5rem"

    def test_radius_with_dash_commentary(self):      # g4e8ksop radius.full
        assert extract_css_length("9999px — avatars, pills, quick-feed button") == "9999px"

    def test_tailwind_scale_class(self):             # g4e8ksop scale.h1
        assert extract_css_length("text-3xl (30px) — page titles") == "1.875rem"

    def test_tailwind_scale_h3(self):                # u6qgw1e6 scale.h3
        assert extract_css_length("text-base (16px) — card titles, cat names") == "1rem"

    def test_annotated_hex(self):                    # silent ramp-deletion bug
        assert extract_hex("#C4611F — warm terracotta") == "#c4611f"

    def test_font_with_commentary(self):             # bl25qcde fontFamily
        assert extract_font_stack("Inter — excellent legibility") == "'Inter', sans-serif"

    def test_font_with_role_prose(self):             # o57ioxhc fontFamily
        got = extract_font_stack("Lora for headings (serif warmth)")
        assert got is not None and got.startswith("'Lora")

    def test_line_height_prose(self):                # globals.css invalid decl
        assert extract_number("1.6 for body, 1.25 for headings", 1.0, 2.2) == 1.6

    def test_duration_prose(self):
        assert extract_ms("150ms for hovers, 300ms for panels") == "150ms"

    def test_shadow_with_suffix(self):
        got = extract_shadow("0 1px 3px rgba(44,31,14,0.06) — subtle card lift")
        assert got == "0 1px 3px rgba(44,31,14,0.06)"


class TestCleanPassThrough:
    """Already-valid values survive untouched (no regression on good specs)."""

    def test_clean_length(self):
        assert extract_css_length("0.75rem") == "0.75rem"

    def test_clean_hex(self):
        assert extract_hex("#2d3a4a") == "#2d3a4a"

    def test_short_hex_expands(self):
        assert extract_hex("#f0a") == "#ff00aa"

    def test_clean_stack(self):
        assert extract_font_stack("'Nunito', 'Quicksand', system-ui, sans-serif") \
            == "'Nunito', 'Quicksand', system-ui, sans-serif"

    def test_multilayer_shadow(self):
        v = "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)"
        got = extract_shadow(v)
        assert got is not None and got.count("rgb") == 2

    def test_shadow_none(self):
        assert extract_shadow("none") == "none"

    def test_weight_named(self):
        assert extract_weight("bold") == "700"
        assert extract_weight("600 (semibold)") == "600"
        assert extract_weight(650) == "650"

    def test_letter_spacing(self):
        assert extract_letter_spacing("-0.02em (tight, modern)") == "-0.02em"
        assert extract_letter_spacing("normal") == "0"


class TestHopelessReturnsNone:
    """Garbage → None (caller falls back to DNA), never an exception."""

    def test_pure_prose(self):
        assert extract_css_length("comfortable padding all around") is None
        assert extract_hex("a warm terracotta tone") is None
        assert extract_shadow("soft and layered") is None
        assert extract_font_stack("") is None
        assert extract_font_stack(None) is None
        assert extract_number("no digits here") is None
        assert extract_weight("heavy-ish") is None

"""Spec D Wave 1 — capability-envelope range validator tests.

Pure functions — no fixtures, no I/O. Covers:
  * in-range pass-through,
  * over-max clamps,
  * under-min clamps,
  * non-numeric coercion,
  * invalid-enum → default,
  * envelope_report on a mixed spec.
"""
from __future__ import annotations

from services.design_capability_envelope import (
    CARD_BORDER_DEFAULT,
    HEADER_ALIGN_DEFAULT,
    clamp_gutter_px,
    clamp_radius_px,
    clamp_shadow_scale,
    envelope_report,
    validate_card_border,
    validate_header_align,
)


# ── Numeric clamps ───────────────────────────────────────────────────

class TestClampRadiusPx:
    def test_in_range_pass_through(self):
        for v in (0, 4, 8, 16, 32):
            assert clamp_radius_px(v) == v

    def test_over_max_clamps(self):
        assert clamp_radius_px(33) == 32
        assert clamp_radius_px(999) == 32

    def test_under_min_clamps(self):
        assert clamp_radius_px(-1) == 0
        assert clamp_radius_px(-100) == 0

    def test_non_numeric_falls_to_min(self):
        assert clamp_radius_px("abc") == 0
        assert clamp_radius_px(None) == 0


class TestClampGutterPx:
    def test_in_range(self):
        for v in (4, 16, 32, 64):
            assert clamp_gutter_px(v) == v

    def test_over_max(self):
        assert clamp_gutter_px(65) == 64
        assert clamp_gutter_px(1000) == 64

    def test_under_min(self):
        assert clamp_gutter_px(3) == 4
        assert clamp_gutter_px(0) == 4


class TestClampShadowScale:
    def test_in_range(self):
        for v in range(6):
            assert clamp_shadow_scale(v) == v

    def test_over_max(self):
        assert clamp_shadow_scale(6) == 5
        assert clamp_shadow_scale(99) == 5

    def test_under_min(self):
        assert clamp_shadow_scale(-1) == 0


# ── Enum-shaped strings ──────────────────────────────────────────────

class TestValidateHeaderAlign:
    def test_valid_values_pass_through(self):
        for v in ("left", "center", "right", "split"):
            assert validate_header_align(v) == v

    def test_uppercase_normalized(self):
        assert validate_header_align("LEFT") == "left"
        assert validate_header_align(" Center ") == "center"

    def test_invalid_returns_default(self):
        assert validate_header_align("middle") == HEADER_ALIGN_DEFAULT
        assert validate_header_align("") == HEADER_ALIGN_DEFAULT
        assert validate_header_align(None) == HEADER_ALIGN_DEFAULT
        assert validate_header_align(42) == HEADER_ALIGN_DEFAULT


class TestValidateCardBorder:
    def test_valid_values(self):
        for v in ("none", "hairline", "standard", "heavy"):
            assert validate_card_border(v) == v

    def test_invalid_returns_default(self):
        assert validate_card_border("bold") == CARD_BORDER_DEFAULT
        assert validate_card_border(None) == CARD_BORDER_DEFAULT


# ── envelope_report ─────────────────────────────────────────────────

class TestEnvelopeReport:
    def test_empty_spec(self):
        r = envelope_report({})
        assert r == {"clamped": [], "invalid": []}

    def test_non_dict_input_safe(self):
        r = envelope_report(None)  # type: ignore[arg-type]
        assert r == {"clamped": [], "invalid": []}

    def test_valid_spec_no_findings(self):
        spec = {"radius_px": 8, "gutter_px": 16, "shadow_scale": 2,
                "header_align": "left", "card_border": "hairline"}
        r = envelope_report(spec)
        assert r == {"clamped": [], "invalid": []}

    def test_mixed_spec_reports_findings(self):
        spec = {
            "layout": {"radius_px": 99, "gutter_px": 2},  # both out of range
            "card": {"card_border": "bold"},              # invalid enum
            "shadow_scale": "loud",                       # non-numeric
            "header_align": "left",                       # valid — no finding
        }
        r = envelope_report(spec)
        clamped_fields = {c["field"] for c in r["clamped"]}
        invalid_fields = {i["field"] for i in r["invalid"]}
        assert clamped_fields == {"radius_px", "gutter_px"}
        assert "card_border" in invalid_fields
        assert "shadow_scale" in invalid_fields

    def test_clamped_captures_from_and_to(self):
        spec = {"radius_px": 100}
        r = envelope_report(spec)
        assert r["clamped"] == [{"field": "radius_px", "from": 100, "to": 32}]

    def test_nested_lists_walked(self):
        spec = {"variants": [{"radius_px": 40}, {"radius_px": 8}]}
        r = envelope_report(spec)
        # Only the out-of-range one appears.
        assert len(r["clamped"]) == 1
        assert r["clamped"][0]["from"] == 40

"""Tests for Spec D Wave 4 — constrained-enum liberation.

Additive: voice_free / neutrals_tint_free / radius_px / density_pt
sit alongside the existing enums. brief_to_design_spec.snap_*
helpers snap continuous numeric intent to renderable tokens without
discarding what the LLM authored.
"""
from __future__ import annotations

import pytest

from schemas.design_brief import (
    DesignBrief, Identity, Layout, Palette, SignatureMove, Typography,
)
from services.brief_to_design_spec import (
    brief_to_design_spec,
    radius_scale_from_px,
    snap_density_pt,
    snap_radius_px,
)


def _brief(**layout_overrides) -> DesignBrief:
    layout_kwargs = dict(density="compact", radius="soft_8", grid="12col")
    layout_kwargs.update(layout_overrides)
    return DesignBrief(
        identity=Identity(domain="Test", register=["structured"],
                           voice="warm_precise"),
        palette=Palette(brand="#2D5A8E", accent="#E8A020",
                        neutrals_base="#F5F5F5", neutrals_tint="cool",
                        surface_bg="#FFFFFF", surface_elevated="#FFFFFF",
                        foreground_primary="#111111",
                        foreground_muted="#666666"),
        typography=Typography(display_family="X", body_family="X"),
        layout=Layout(**layout_kwargs),
        signature_moves=[SignatureMove(kind="warm_serif_h1", detail="x")],
    )


# ────────────────────────────────────────────────────────────
# Schema — new fields accepted, existing shape unchanged
# ────────────────────────────────────────────────────────────

class TestSchema:
    def test_voice_free_accepted(self):
        b = _brief()
        b.identity.voice_free = "warm and precise, quietly editorial"
        assert b.identity.voice_free == "warm and precise, quietly editorial"

    def test_voice_free_max_length_40(self):
        b = _brief()
        # 41 chars → rejected.
        with pytest.raises(Exception):
            Identity(domain="D", register=["a"], voice="warm_precise",
                     voice_free="a" * 41)

    def test_neutrals_tint_free_accepted(self):
        p = Palette(brand="#000000", accent="#111111", neutrals_base="#F5F5F5",
                    neutrals_tint="cool", neutrals_tint_free="cool with green",
                    surface_bg="#FFFFFF", surface_elevated="#FFFFFF",
                    foreground_primary="#000000", foreground_muted="#666666")
        assert p.neutrals_tint_free == "cool with green"

    def test_neutrals_tint_free_max_length_20(self):
        with pytest.raises(Exception):
            Palette(brand="#000000", accent="#111111", neutrals_base="#F5F5F5",
                    neutrals_tint="cool", neutrals_tint_free="a" * 21,
                    surface_bg="#FFFFFF", surface_elevated="#FFFFFF",
                    foreground_primary="#000000", foreground_muted="#666666")

    def test_radius_px_accepted(self):
        b = _brief(radius_px=12)
        assert b.layout.radius_px == 12

    def test_radius_px_range_checked(self):
        with pytest.raises(Exception):
            Layout(density="compact", radius="soft_8", radius_px=33)  # > 32
        with pytest.raises(Exception):
            Layout(density="compact", radius="soft_8", radius_px=-1)  # < 0

    def test_density_pt_accepted(self):
        b = _brief(density_pt=8)
        assert b.layout.density_pt == 8

    def test_density_pt_range_checked(self):
        with pytest.raises(Exception):
            Layout(density="compact", radius="soft_8", density_pt=33)

    def test_all_new_fields_optional_defaults_none(self):
        b = _brief()
        assert b.identity.voice_free is None
        assert b.palette.neutrals_tint_free is None
        assert b.layout.radius_px is None
        assert b.layout.density_pt is None


# ────────────────────────────────────────────────────────────
# Snap helpers
# ────────────────────────────────────────────────────────────

class TestSnapRadius:
    def test_none_input_returns_none(self):
        assert snap_radius_px(None) is None

    def test_zero_to_three_snap_to_sharp_2(self):
        for v in (0, 1, 2, 3):
            assert snap_radius_px(v) == "sharp_2"

    def test_four_to_fifteen_snap_to_soft_8(self):
        for v in (4, 8, 12, 15):
            assert snap_radius_px(v) == "soft_8"

    def test_sixteen_and_above_snap_to_pill(self):
        for v in (16, 24, 32, 999):
            assert snap_radius_px(v) == "pill"

    def test_non_numeric_returns_none(self):
        assert snap_radius_px("abc") is None  # type: ignore[arg-type]


class TestRadiusScaleFromPx:
    def test_small_px_produces_proportional_scale(self):
        s = radius_scale_from_px(8)
        assert s["sm"] == 4 and s["md"] == 8 and s["lg"] == 12

    def test_large_px_snaps_md_lg_to_pill_999(self):
        s = radius_scale_from_px(24)
        assert s["md"] == 999 and s["lg"] == 999

    def test_zero_px_still_returns_min_1(self):
        s = radius_scale_from_px(0)
        # We clamp to minimum 1 so CSS never gets a bare "0px" that some
        # engines print as just "0" (invalid for radius).
        assert s["md"] >= 1


class TestSnapDensity:
    def test_none_returns_none(self):
        assert snap_density_pt(None) is None

    def test_compact_range(self):
        for v in (2, 4, 5):
            assert snap_density_pt(v) == "compact"

    def test_comfortable_range(self):
        for v in (6, 8, 10):
            assert snap_density_pt(v) == "comfortable"

    def test_spacious_range(self):
        for v in (11, 14, 16):
            assert snap_density_pt(v) == "spacious"

    def test_spacious_for_touch(self):
        for v in (17, 24, 32):
            assert snap_density_pt(v) == "spacious_for_touch"


# ────────────────────────────────────────────────────────────
# brief_to_design_spec — numeric wins when present
# ────────────────────────────────────────────────────────────

class TestBriefToDesignSpec:
    def test_enum_path_unchanged_when_no_px(self):
        # Regression: existing behavior for enum-only briefs.
        spec = brief_to_design_spec(_brief(radius="soft_8"))
        assert spec["borderRadius"]["md"] == "8px"

    def test_radius_px_overrides_enum(self):
        # brief.layout.radius still "soft_8" (would emit 8px) but
        # radius_px=24 wins → pill treatment (999).
        spec = brief_to_design_spec(_brief(radius="soft_8", radius_px=24))
        assert spec["borderRadius"]["md"] == "999px"

    def test_radius_px_flows_to_layout_scale(self):
        spec = brief_to_design_spec(_brief(radius="soft_8", radius_px=8))
        assert spec["layout"]["radius"]["md"] == 8

    def test_borderradius_and_layout_agree(self):
        # Both readers should see the same source of truth.
        spec = brief_to_design_spec(_brief(radius_px=6))
        assert spec["borderRadius"]["md"] == f"{spec['layout']['radius']['md']}px"

    def test_deterministic_with_numeric_authoring(self):
        b = _brief(radius_px=10)
        a = brief_to_design_spec(b)
        b2 = brief_to_design_spec(b)
        assert a == b2

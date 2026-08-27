"""Tests for services.logo_generator — Spec C9 monogram SVG."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.logo_generator import (
    generate_logo_set,
    render_monogram_svg,
)


class TestRender:
    def test_returns_svg_source(self):
        svg = render_monogram_svg("R", brand_hex="#2D5A8E")
        assert "<svg" in svg
        assert 'viewBox="0 0 64 64"' in svg
        assert ">R</text>" in svg

    def test_uses_brand_hex_verbatim(self):
        svg = render_monogram_svg("A", brand_hex="#FF6600")
        assert 'fill="#FF6600"' in svg

    def test_normalizes_lowercase_hex(self):
        svg = render_monogram_svg("A", brand_hex="#ab12cd")
        assert 'fill="#AB12CD"' in svg

    def test_normalizes_shorthand_hex(self):
        svg = render_monogram_svg("A", brand_hex="#F60")
        assert 'fill="#FF6600"' in svg

    def test_dark_brand_gets_white_text(self):
        # #111827 is very dark → text should be white.
        svg = render_monogram_svg("A", brand_hex="#111827")
        assert 'fill="#FFFFFF"' in svg

    def test_light_brand_gets_dark_text(self):
        svg = render_monogram_svg("A", brand_hex="#FFEB3B")  # bright yellow
        assert 'fill="#111827"' in svg

    def test_deterministic_same_inputs_same_output(self):
        a = render_monogram_svg("R", brand_hex="#2D5A8E")
        b = render_monogram_svg("R", brand_hex="#2D5A8E")
        assert a == b

    def test_custom_size_reflected_in_viewbox(self):
        svg = render_monogram_svg("R", brand_hex="#000", size=128)
        assert 'viewBox="0 0 128 128"' in svg
        assert 'width="128"' in svg

    def test_custom_radius_px(self):
        svg = render_monogram_svg("R", brand_hex="#000", size=64, radius_px=32)
        assert 'rx="32"' in svg and 'ry="32"' in svg

    def test_xml_declaration_toggle(self):
        with_decl = render_monogram_svg("R", brand_hex="#000", include_xml_decl=True)
        no_decl = render_monogram_svg("R", brand_hex="#000", include_xml_decl=False)
        assert with_decl.startswith('<?xml')
        assert not no_decl.startswith('<?xml')


class TestGenerateSet:
    def test_writes_all_four_files(self, tmp_path):
        res = generate_logo_set(str(tmp_path), app_name="Rentr", brand_hex="#2D5A8E")
        assert res["files"] == 4
        pub = tmp_path / "public"
        for name in ("logo.svg", "logo-large.svg", "favicon.svg",
                     "apple-touch-icon.svg"):
            assert (pub / name).exists(), f"missing {name}"

    def test_letter_first_alnum_upper(self, tmp_path):
        res = generate_logo_set(str(tmp_path), app_name="  ⚡rentr", brand_hex="#000")
        assert res["letter"] == "R"

    def test_letter_defaults_when_no_alnum(self, tmp_path):
        res = generate_logo_set(str(tmp_path), app_name="---", brand_hex="#000")
        assert res["letter"] == "?"

    def test_letter_appears_in_all_svgs(self, tmp_path):
        generate_logo_set(str(tmp_path), app_name="Hive", brand_hex="#000")
        pub = tmp_path / "public"
        for name in ("logo.svg", "logo-large.svg", "favicon.svg",
                     "apple-touch-icon.svg"):
            assert ">H</text>" in (pub / name).read_text()

    def test_radius_kind_pill_makes_full_round_favicon(self, tmp_path):
        generate_logo_set(str(tmp_path), app_name="A", brand_hex="#000",
                          radius_kind="pill")
        fav = (tmp_path / "public/favicon.svg").read_text()
        assert 'rx="8"' in fav  # 16/2 = 8 → pill circle for 16px mark

    def test_radius_kind_sharp_2_makes_tiny_corners(self, tmp_path):
        generate_logo_set(str(tmp_path), app_name="A", brand_hex="#000",
                          radius_kind="sharp_2")
        large = (tmp_path / "public/logo-large.svg").read_text()
        # 256 / 32 = 8 → small corners
        assert 'rx="8"' in large

    def test_radius_kind_soft_8_default(self, tmp_path):
        generate_logo_set(str(tmp_path), app_name="A", brand_hex="#000")
        logo = (tmp_path / "public/logo.svg").read_text()
        # 64 / 8 = 8 for soft_8
        assert 'rx="8"' in logo

    def test_brand_hex_recorded_in_return(self, tmp_path):
        res = generate_logo_set(str(tmp_path), app_name="X", brand_hex="#e8a020")
        assert res["brand"] == "#E8A020"

    def test_deterministic_across_runs(self, tmp_path):
        r1 = generate_logo_set(str(tmp_path), app_name="Rentr", brand_hex="#2D5A8E")
        first = (tmp_path / "public/logo.svg").read_text()
        r2 = generate_logo_set(str(tmp_path), app_name="Rentr", brand_hex="#2D5A8E")
        second = (tmp_path / "public/logo.svg").read_text()
        assert first == second
        assert r1 == r2

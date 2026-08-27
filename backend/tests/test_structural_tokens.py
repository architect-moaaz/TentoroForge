"""Promote structural design tokens from LLM-authored / static-gray to spec-derived:
the neutral scaffolding (border, input, ring, muted, foreground, card/popover) is
derived from the palette's brand hue so the whole app reads as ONE cohesive theme
instead of a colored primary sitting on generic grey chrome.
"""
import re

from services.design_compiler import derive_structural_tokens

_TRIPLET = re.compile(r"^(\d{1,3}) (\d{1,3})% (\d{1,3})%$")


def _hue(triplet: str) -> int:
    m = _TRIPLET.match(triplet)
    assert m, f"bad HSL triplet: {triplet!r}"
    return int(m.group(1))


def _sat(triplet: str) -> int:
    return int(_TRIPLET.match(triplet).group(2))


def _lum(triplet: str) -> int:
    return int(_TRIPLET.match(triplet).group(3))


TEAL = {"primary": "#0f766e", "background": "#ffffff", "accent": "#d97706"}


def test_neutrals_carry_the_brand_hue_not_pure_grey():
    toks = derive_structural_tokens(TEAL)
    # #0f766e is teal → hue ~173-175. Border/muted/foreground should share it.
    for var in ("--border", "--muted", "--foreground", "--muted-foreground"):
        h = _hue(toks[var])
        assert 165 <= h <= 185, f"{var} hue {h} not tinted toward the teal brand hue"
    # ...and be low-saturation neutrals, not vivid.
    assert _sat(toks["--border"]) <= 25
    assert _sat(toks["--muted"]) <= 25


def test_lightness_hierarchy_is_sane_for_light_theme():
    toks = derive_structural_tokens(TEAL)
    assert _lum(toks["--foreground"]) < 30          # dark text
    assert _lum(toks["--muted-foreground"]) < _lum(toks["--border"])  # text darker than border
    assert _lum(toks["--border"]) > 80              # subtle light border
    assert _lum(toks["--muted"]) > 90               # near-white muted surface


def test_ring_tracks_the_primary():
    toks = derive_structural_tokens(TEAL)
    assert 165 <= _hue(toks["--ring"]) <= 185       # focus ring = brand hue
    assert _sat(toks["--ring"]) >= 30               # ring is more saturated than neutrals


def test_all_values_are_valid_hsl_triplets():
    for var, val in derive_structural_tokens(TEAL).items():
        assert _TRIPLET.match(val), f"{var}={val!r} is not an 'H S% L%' triplet"


def test_empty_or_invalid_palette_falls_back_without_crashing():
    for palette in ({}, {"primary": "not-a-hex"}, {"primary": None}):
        toks = derive_structural_tokens(palette)
        assert "--border" in toks and _TRIPLET.match(toks["--border"])


def test_warm_brand_hue_tints_warm():
    # A warm brown/gold primary should tint neutrals warm (hue ~30-45), not teal.
    toks = derive_structural_tokens({"primary": "#b45309"})
    assert 20 <= _hue(toks["--border"]) <= 50


def test_rewrite_globals_writes_derived_structural_tokens(tmp_path):
    """Integration: _rewrite_globals_root must emit brand-tinted structural tokens
    into :root even when the palette only carries primary/background."""
    from agents.design_agent import _rewrite_globals_root

    css = tmp_path / "globals.css"
    # A :root the LLM authored with GENERIC grey border (hue 0 / slate), no tint.
    css.write_text(":root {\n  --primary: 173 79% 26%;\n  --border: 0 0% 90%;\n}\n")
    _rewrite_globals_root(css, {"primary": "#0f766e", "background": "#ffffff"})
    out = css.read_text()
    assert "--border:" in out and "--ring:" in out and "--foreground:" in out
    # the border hue must now be teal (~165-185), not 0 (grey)
    m = re.search(r"--border:\s*(\d+) ", out)
    assert m and 165 <= int(m.group(1)) <= 185, out

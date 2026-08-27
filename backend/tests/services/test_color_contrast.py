"""Tests for services.color_contrast — WCAG contrast + HSL saturation."""
from __future__ import annotations

import pytest

from services.color_contrast import (
    contrast_ratio,
    parse_hex,
    relative_luminance,
    saturation,
    saturation_cap_for_register,
)


# --------------------------------------------------------------------- #
# parse_hex
# --------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "value,expected",
    [
        ("#000000", (0, 0, 0)),
        ("#FFFFFF", (255, 255, 255)),
        ("#ffffff", (255, 255, 255)),
        ("FFFFFF",  (255, 255, 255)),
        ("#F5F6F8", (0xF5, 0xF6, 0xF8)),
        ("  #ABCDEF  ", (0xAB, 0xCD, 0xEF)),
    ],
)
def test_parse_hex_valid(value, expected):
    assert parse_hex(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", None, "#12345", "#GGGGGG", "not a color", 123, "#1234567", "#FFF"],
)
def test_parse_hex_invalid(value):
    assert parse_hex(value) is None


# --------------------------------------------------------------------- #
# relative_luminance
# --------------------------------------------------------------------- #

def test_relative_luminance_reference_values():
    # WCAG spec reference: black is 0.0, white is 1.0.
    assert relative_luminance((0, 0, 0)) == pytest.approx(0.0)
    assert relative_luminance((255, 255, 255)) == pytest.approx(1.0)
    # Mid-grey (#808080) sits around 0.216.
    assert relative_luminance((128, 128, 128)) == pytest.approx(0.216, abs=1e-2)


# --------------------------------------------------------------------- #
# contrast_ratio
# --------------------------------------------------------------------- #

def test_contrast_ratio_black_on_white():
    # WCAG max ratio is 21:1 (black vs white).
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.05)


def test_contrast_ratio_identical_is_one():
    assert contrast_ratio("#123456", "#123456") == pytest.approx(1.0)


def test_contrast_ratio_symmetric():
    a = contrast_ratio("#0B2545", "#F5F6F8")
    b = contrast_ratio("#F5F6F8", "#0B2545")
    assert a == pytest.approx(b)
    # Deep navy on off-white — comfortably AA territory (>= 7:1 is AAA).
    assert a > 12.0


def test_contrast_ratio_low_returns_below_threshold():
    # Light lavender on a near-white bg should tank contrast (<3:1).
    assert contrast_ratio("#ABCDEF", "#F5F6F8") < 3.0


def test_contrast_ratio_bad_input_falls_open_to_one():
    assert contrast_ratio("not-a-hex", "#FFFFFF") == 1.0
    assert contrast_ratio("#FFFFFF", None) == 1.0  # type: ignore[arg-type]


# --------------------------------------------------------------------- #
# saturation
# --------------------------------------------------------------------- #

def test_saturation_greys_are_zero():
    assert saturation((0, 0, 0)) == 0.0
    assert saturation((128, 128, 128)) == 0.0
    assert saturation((255, 255, 255)) == 0.0


def test_saturation_pure_primaries_are_one():
    assert saturation((255, 0, 0)) == pytest.approx(1.0)
    assert saturation((0, 255, 0)) == pytest.approx(1.0)
    assert saturation((0, 0, 255)) == pytest.approx(1.0)


def test_saturation_muted_forest_green_is_low():
    # WELLNESS_WARM's forest green — restrained palette.
    r, g, b = parse_hex("#5A6B4A")
    assert saturation((r, g, b)) < 0.30


def test_saturation_vivid_amber_is_high():
    # #F59E0B (amber-500) — vivid brand color.
    r, g, b = parse_hex("#F59E0B")
    assert saturation((r, g, b)) > 0.85


# --------------------------------------------------------------------- #
# saturation_cap_for_register
# --------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "register,expected",
    [
        (["calm"],           0.55),
        (["clinical"],       0.55),
        (["warm", "soft"],   0.55),
        (["bold"],           0.95),
        (["playful"],        0.95),
        (["energetic"],      0.95),
        # bold wins on a mixed tag — a playful + calm brief still reads playful
        (["playful", "calm"], 0.95),
        # unknown / free-form → default cap
        (["quirky"],         0.75),
        ([],                 0.75),
        (None,               0.75),
        # single-string form is tolerated
        ("clinical",         0.55),
    ],
)
def test_saturation_cap(register, expected):
    assert saturation_cap_for_register(register) == expected

"""Spec E Wave 2 — high_contrast_pass unit tests.

Guarantees:
* WCAG contrast maths hits the well-known black-on-white = 21:1 anchor.
* derive_high_contrast returns a variant where ink/canvas meets 7:1
  (WCAG AAA) even when the input is a low-contrast pair.
* build_high_contrast_css always emits a data-theme block ready to
  concat into globals.css, and is deterministic given the same input.
"""
from __future__ import annotations

import pytest

from services.high_contrast_pass import (
    build_high_contrast_css,
    contrast_ratio,
    derive_high_contrast,
    relative_luminance,
)


def test_black_on_white_is_21_to_1():
    assert round(contrast_ratio("#000000", "#ffffff"), 1) == 21.0


def test_white_luminance_is_one():
    assert pytest.approx(relative_luminance("#ffffff"), abs=0.001) == 1.0


def test_black_luminance_is_zero():
    assert relative_luminance("#000000") == 0.0


def test_derive_pushes_low_contrast_pair_to_aaa():
    # Light-grey on light-grey — nowhere near 7:1 out of the box.
    src = {"brand": "#888", "accent": "#999", "ink": "#666", "canvas": "#eee"}
    out = derive_high_contrast(src)
    # ink vs canvas is the primary text pair; must meet AAA (7:1).
    assert contrast_ratio(out["ink"], out["canvas"]) >= 7.0
    # Brand + accent likewise (they are used as text/foreground in badges,
    # buttons and links, so the same threshold applies).
    assert contrast_ratio(out["brand"], out["canvas"]) >= 7.0
    assert contrast_ratio(out["accent"], out["canvas"]) >= 7.0


def test_derive_handles_missing_input_gracefully():
    # No palette at all — should still return a valid variant.
    out = derive_high_contrast(None)
    assert "ink" in out and "canvas" in out
    assert contrast_ratio(out["ink"], out["canvas"]) >= 7.0


def test_derive_handles_bad_hex_gracefully():
    # A junk value should be ignored (fall back to default), not raise.
    src = {"brand": "not-a-colour", "canvas": "#fff", "ink": "#000"}
    out = derive_high_contrast(src)
    assert out["ink"].startswith("#")
    assert out["canvas"].startswith("#")


def test_derive_on_dark_canvas_lightens_text():
    src = {"brand": "#4a90e2", "accent": "#7c3aed", "ink": "#cccccc", "canvas": "#111111"}
    out = derive_high_contrast(src)
    assert contrast_ratio(out["ink"], out["canvas"]) >= 7.0


def test_build_css_emits_data_theme_block():
    css = build_high_contrast_css()
    assert '[data-theme="high-contrast"]' in css
    assert "--color-foreground" in css
    assert "--color-background" in css
    # Focus-ring override so the ring is always visible on the HC canvas.
    assert "--focus-ring-color" in css


def test_build_css_is_deterministic():
    a = build_high_contrast_css({"brand": "#f00", "ink": "#000", "canvas": "#fff"})
    b = build_high_contrast_css({"brand": "#f00", "ink": "#000", "canvas": "#fff"})
    assert a == b

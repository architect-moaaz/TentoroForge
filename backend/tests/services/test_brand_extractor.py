"""Tests for brand color extraction from logo bytes."""
import pytest
from pathlib import Path
from services.brand_extractor import extract_palette_from_logo, BrandPalette


@pytest.fixture
def red_square_png():
    """An 8×8 pure-red PNG, used as a deterministic test fixture."""
    from PIL import Image
    import io
    img = Image.new("RGB", (8, 8), (220, 38, 38))  # #DC2626 red
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def blue_with_white_png():
    """A 16×16 PNG: half pure-blue #0EA5E9, half white (near-neutral)."""
    from PIL import Image
    import io
    img = Image.new("RGB", (16, 16), (255, 255, 255))
    for x in range(8):
        for y in range(16):
            img.putpixel((x, y), (14, 165, 233))  # #0EA5E9
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_palette_returns_brand_palette(red_square_png):
    result = extract_palette_from_logo(red_square_png)
    assert isinstance(result, BrandPalette)


def test_extract_palette_picks_dominant_color(red_square_png):
    result = extract_palette_from_logo(red_square_png)
    # Primary should be close to #DC2626 (RGB 220, 38, 38)
    r, g, b = result.primary_rgb
    assert r > 180 and g < 80 and b < 80


def test_extract_palette_filters_near_white(blue_with_white_png):
    result = extract_palette_from_logo(blue_with_white_png)
    # Primary should be the blue #0EA5E9, not white
    r, g, b = result.primary_rgb
    assert b > 180 and r < 100  # blue-dominant


def test_extract_palette_returns_hex_strings(red_square_png):
    result = extract_palette_from_logo(red_square_png)
    assert result.primary_hex.startswith("#") and len(result.primary_hex) == 7

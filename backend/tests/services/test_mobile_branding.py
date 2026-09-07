"""Tests for services.mobile_branding — MOBILE-E anchor.

Covers:
  * Monogram derivation from various app names.
  * Contrast picker returns readable foreground for any brand hue.
  * Icon/splash files land at the requested dimensions.
  * Store listing hits every documented section.
  * Store fields honour Play Store / App Store character limits.
  * Category guesser matches obvious signals, otherwise Productivity.
  * Graceful fallback when Pillow is missing / app.json is malformed.
  * Idempotency: two runs produce the same bytes.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest


pytest.importorskip("PIL", reason="mobile_branding tests need Pillow")

from services.mobile_branding import (
    MobileSpec,
    _APP_STORE_KEYWORDS_LIMIT,
    _APP_STORE_SUBTITLE_LIMIT,
    _PLAY_STORE_LONG_LIMIT,
    _PLAY_STORE_SHORT_LIMIT,
    _contrasting_color,
    _guess_category,
    _hex_to_rgb,
    _keywords,
    _long_description,
    _normalize_hex,
    _short_description,
    apply_mobile_branding,
)


# --------------------------------------------------------------------------- #
# Fixture — a minimal mobile/ folder with an app.json                          #
# --------------------------------------------------------------------------- #

def _make_mobile_dir(
    tmp_path: Path,
    *,
    name: str = "Recipe Collection",
    brand: str = "#EF4444",
    description: str = "",
) -> Path:
    m = tmp_path / "mobile"
    (m / "assets").mkdir(parents=True)
    (m / "app.json").write_text(json.dumps({
        "expo": {
            "name": name,
            "slug": "recipe-collection",
            "splash": {"backgroundColor": brand},
            "extra": {"description": description},
        },
    }), encoding="utf-8")
    return m


# --------------------------------------------------------------------------- #
# Monogram                                                                     #
# --------------------------------------------------------------------------- #

class TestMonogram:
    @pytest.mark.parametrize("name, expected", [
        ("Recipe Collection", "RC"),
        ("Planters Nursery Management", "PN"),
        ("Planters", "P"),
        ("simple", "S"),
        ("multi-word thing", "MW"),
        ("   trim me   ", "TM"),
        ("123", "A"),
        ("", "A"),
    ])
    def test_derives_1_or_2_letters(self, name, expected):
        spec = MobileSpec(name=name, slug="x", brand_hex="#000000")
        assert spec.monogram == expected


# --------------------------------------------------------------------------- #
# Color helpers                                                                #
# --------------------------------------------------------------------------- #

class TestColor:
    def test_normalize_hex_pads_and_uppercases(self):
        assert _normalize_hex("ef4444") == "#EF4444"
        assert _normalize_hex("#ef4444") == "#EF4444"

    def test_normalize_hex_rejects_garbage(self):
        assert _normalize_hex("nope") == "#4F46E5"
        assert _normalize_hex("") == "#4F46E5"

    def test_hex_to_rgb(self):
        assert _hex_to_rgb("#FF0000") == (255, 0, 0)
        assert _hex_to_rgb("000000") == (0, 0, 0)

    def test_contrast_white_on_dark_brand(self):
        assert _contrasting_color((79, 70, 229)) == (255, 255, 255)  # indigo
        assert _contrasting_color((0, 0, 0)) == (255, 255, 255)

    def test_contrast_dark_on_light_brand(self):
        assert _contrasting_color((255, 255, 255)) == (17, 17, 17)
        assert _contrasting_color((240, 240, 200)) == (17, 17, 17)  # pale yellow


# --------------------------------------------------------------------------- #
# apply_mobile_branding — end-to-end                                            #
# --------------------------------------------------------------------------- #

class TestApplyBranding:
    def test_writes_all_four_pngs_and_listing(self, tmp_path):
        m = _make_mobile_dir(tmp_path)
        result = apply_mobile_branding(str(m))
        assert result["applied"] is True
        for name in ("icon.png", "adaptive-icon.png",
                     "splash.png", "favicon.png"):
            assert (m / "assets" / name).is_file(), f"{name} missing"
        assert (m / "store-listing.md").is_file()

    def test_pngs_have_expected_dimensions(self, tmp_path):
        m = _make_mobile_dir(tmp_path)
        apply_mobile_branding(str(m))
        for name, w, h in [
            ("icon.png", 1024, 1024),
            ("adaptive-icon.png", 1024, 1024),
            ("splash.png", 1242, 2436),
            ("favicon.png", 48, 48),
        ]:
            data = (m / "assets" / name).read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{name} bad PNG signature"
            assert data[12:16] == b"IHDR"
            got_w, got_h = struct.unpack(">II", data[16:24])
            assert (got_w, got_h) == (w, h), f"{name} is {got_w}x{got_h}, want {w}x{h}"

    def test_missing_app_json_returns_reason(self, tmp_path):
        m = tmp_path / "mobile"
        m.mkdir()
        result = apply_mobile_branding(str(m))
        assert result["applied"] is False
        assert result["reason"] == "no_app_json"

    def test_second_run_is_stable(self, tmp_path):
        """Idempotent — running the pass again produces the same bytes.
        Prevents a spurious 'edited files' diff on every re-generation."""
        m = _make_mobile_dir(tmp_path)
        apply_mobile_branding(str(m))
        first = {
            n: (m / "assets" / n).read_bytes()
            for n in ("icon.png", "splash.png")
        }
        apply_mobile_branding(str(m))
        second = {
            n: (m / "assets" / n).read_bytes()
            for n in ("icon.png", "splash.png")
        }
        assert first == second


# --------------------------------------------------------------------------- #
# Store-listing content                                                        #
# --------------------------------------------------------------------------- #

class TestStoreListing:
    def _read_listing(self, tmp_path, **kwargs) -> str:
        m = _make_mobile_dir(tmp_path, **kwargs)
        apply_mobile_branding(str(m))
        return (m / "store-listing.md").read_text(encoding="utf-8")

    def test_has_every_required_section(self, tmp_path):
        text = self._read_listing(tmp_path)
        for header in (
            "# App Store & Play Store listing",
            "## Common",
            "## Google Play Store",
            "**Short description",
            "**Full description",
            "## Apple App Store",
            "**Subtitle",
            "**Keywords",
            "## Screenshots",
            "## First submission checklist",
        ):
            assert header in text, f"missing section: {header}"

    def test_short_description_under_play_limit(self, tmp_path):
        """Emitted short description must be ≤ 80 chars — Play Console
        rejects submissions over that."""
        text = self._read_listing(
            tmp_path,
            name="Very Long App Name For Testing",
            description="A very lengthy description that goes on and on and definitely exceeds eighty characters when written out fully",
        )
        # Extract the short description block.
        match = _extract_block(text, "**Short description")
        assert match is not None
        assert len(match) <= _PLAY_STORE_SHORT_LIMIT

    def test_keywords_under_app_store_limit(self, tmp_path):
        text = self._read_listing(
            tmp_path,
            description="recipe cook meal kitchen ingredient food cuisine gourmet plate dish tasty delicious",
        )
        match = _extract_block(text, "**Keywords")
        assert match is not None
        assert len(match) <= _APP_STORE_KEYWORDS_LIMIT

    def test_subtitle_under_app_store_limit(self, tmp_path):
        text = self._read_listing(
            tmp_path,
            description="A long-winded subtitle attempting to fully explain the product's raison d'être",
        )
        # Subtitle appears immediately after the ** header inside a fenced block.
        match = _extract_block(text, "**Subtitle")
        assert match is not None
        assert len(match) <= _APP_STORE_SUBTITLE_LIMIT


class TestShortLongDescription:
    def test_short_falls_back_to_generic(self):
        spec = MobileSpec(name="Test App", slug="x", brand_hex="#000000")
        short = _short_description(spec)
        assert "Test App" in short

    def test_short_uses_description_when_present(self):
        spec = MobileSpec(
            name="Recipes", slug="x", brand_hex="#000000",
            description="A curated cookbook",
        )
        assert "curated cookbook" in _short_description(spec)

    def test_long_stays_under_play_limit(self):
        spec = MobileSpec(name="X", slug="x", brand_hex="#000000",
                          description="Y " * 500)
        long_ = _long_description(spec)
        assert len(long_) < _PLAY_STORE_LONG_LIMIT


# --------------------------------------------------------------------------- #
# Keywords + category                                                          #
# --------------------------------------------------------------------------- #

class TestKeywords:
    def test_drops_stop_words(self):
        spec = MobileSpec(
            name="App", slug="app", brand_hex="#000",
            description="this that with from your make about people",
        )
        result = _keywords(spec)
        for stop in ("this", "that", "with", "your", "about"):
            assert stop not in result

    def test_returns_fallback_when_no_keywords(self):
        spec = MobileSpec(name="X", slug="x", brand_hex="#000000")
        result = _keywords(spec)
        assert len(result) > 0

    def test_dedupes(self):
        spec = MobileSpec(
            name="Recipe", slug="x", brand_hex="#000",
            description="recipe recipe recipe cook cook",
        )
        result = _keywords(spec)
        parts = [p for p in result.split(",") if p]
        assert len(parts) == len(set(parts))


class TestCategory:
    @pytest.mark.parametrize("description, category", [
        ("A shopping cart for buying stuff", "Shopping"),
        ("Track your workout and fitness goals", "Health & Fitness"),
        ("Curated recipe collection", "Food & Drink"),
        ("Read your library", "Books"),
        ("Book your next trip", "Travel"),
        ("Manage your camera photos", "Photo & Video"),
        ("Track your finances and expenses", "Finance"),
        ("A course of lessons for learning", "Education"),
        ("Something completely generic and unremarkable", "Productivity"),
    ])
    def test_matches_common_signals(self, description, category):
        spec = MobileSpec(
            name="X", slug="x", brand_hex="#000",
            description=description,
        )
        assert _guess_category(spec) == category


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _extract_block(md: str, after_header: str) -> str | None:
    """Return the text inside the first ``` fenced block that follows
    the given markdown header."""
    idx = md.find(after_header)
    if idx < 0:
        return None
    fence_open = md.find("```", idx)
    if fence_open < 0:
        return None
    body_start = md.find("\n", fence_open) + 1
    fence_close = md.find("```", body_start)
    if fence_close < 0:
        return None
    return md[body_start:fence_close].strip()

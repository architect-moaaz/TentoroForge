"""A design montage should reach the pipeline, not just Smith's eyes.

Today `attachment_ids` is threaded only into `_handle_smith_turn` — Smith
can SEE an attached screenshot and talk about it, but the generation
pipeline never reads it. The design brief is authored from the text brief
plus discovery prose ("deep navy and teal with warm amber accents"),
never from the image the user actually pointed at.

Figma already has the seam: `extract_figma_context` pulls structured
tokens, then `brief_from_figma` deterministically maps them to roles.
A screenshot needs only the first half replaced — vision instead of the
Figma API — because the aggregation half is domain-agnostic: it takes
`{colors, fonts, spacings, border_radii}` and knows nothing about where
they came from.

So this module reuses brief_from_figma's helpers verbatim. Two things
that must hold and are easy to get wrong:

* `source="screenshot"` and locked fields — a montage is evidence the
  user chose, so Smith's edit_brief must refuse to silently overwrite
  the extracted palette, exactly as it does for Figma.
* The extractor must reject junk. Vision returns prose sometimes; a
  malformed hex or a hallucinated font name must not reach the brief,
  because a bad hex propagates all the way to globals.css.
"""
from __future__ import annotations

import json

import pytest

from services.brief_from_screenshot import (
    ScreenshotBriefError,
    brief_from_screenshot,
    extract_screenshot_tokens,
)

# Tokens shaped like the BizHub montage: navy chrome, white surfaces,
# a blue brand, amber/green/red status accents, Inter-ish type.
_MONTAGE = {
    "colors": [
        "#FFFFFF", "#FFFFFF", "#FFFFFF", "#F8FAFC", "#F1F5F9",
        "#1E293B", "#0F172A", "#64748B",
        "#2563EB", "#2563EB", "#2563EB", "#2563EB",
        "#F59E0B", "#F59E0B", "#10B981", "#EF4444",
    ],
    "fonts": ["Inter", "Inter", "Inter"],
    "spacings": [4, 8, 12, 16, 24],
    "border_radii": [8, 8, 12],
}


class TestAggregationReusesTheFigmaContract:
    def test_it_returns_a_valid_design_brief(self, tmp_path):
        brief = brief_from_screenshot(_MONTAGE, "event-management")
        assert brief.identity.domain == "event-management"

    def test_brand_is_the_most_frequent_non_neutral(self):
        """#2563EB appears 4x — more than any other chromatic colour."""
        brief = brief_from_screenshot(_MONTAGE, "general")
        assert brief.palette.brand.upper().startswith("#2563EB")

    def test_neutrals_come_from_the_neutral_subset(self):
        brief = brief_from_screenshot(_MONTAGE, "general")
        assert brief.palette.surface_bg.upper() in ("#FFFFFF", "#F8FAFC")

    def test_typography_uses_the_observed_family(self):
        brief = brief_from_screenshot(_MONTAGE, "general")
        assert "Inter" in (brief.typography.body_family or "")


class TestProvenanceAndLocking:
    def test_source_is_screenshot(self):
        """Distinguishable from figma and authored — the brief records
        where its evidence came from."""
        assert brief_from_screenshot(_MONTAGE, "general").identity.source == "screenshot"

    def test_palette_fields_are_locked(self):
        """A montage is a deliberate choice; edit_brief must not silently
        overwrite it (same guarantee Figma gets)."""
        locked = brief_from_screenshot(_MONTAGE, "general").palette.locked_fields
        assert "brand" in locked and "surface_bg" in locked

    def test_a_signature_move_records_the_provenance(self):
        moves = brief_from_screenshot(_MONTAGE, "general").signature_moves
        assert any("screenshot" in (m.kind + m.detail).lower() for m in moves)


class TestSparseInputIsRefusedLoudly:
    def test_no_colors_raises(self):
        with pytest.raises(ScreenshotBriefError):
            brief_from_screenshot({"colors": [], "fonts": ["Inter"]}, "general")

    def test_missing_tokens_raises(self):
        with pytest.raises(ScreenshotBriefError):
            brief_from_screenshot({}, "general")

    def test_only_neutrals_raises(self):
        """A greyscale screenshot carries no brand signal — better to fail
        than to invent one."""
        with pytest.raises(ScreenshotBriefError):
            brief_from_screenshot(
                {"colors": ["#FFFFFF", "#EEEEEE", "#111111"], "fonts": []}, "general")


class TestExtractorRejectsJunk:
    """Vision output is untrusted text until proven parseable."""

    def _llm(self, payload):
        return lambda **_kw: payload

    def test_it_parses_a_clean_json_response(self):
        out = extract_screenshot_tokens(
            [{"type": "image"}],
            llm=self._llm(json.dumps({"colors": ["#2563EB", "#FFFFFF"],
                                      "fonts": ["Inter"], "border_radii": [8],
                                      "spacings": [8]})),
        )
        assert out["colors"] == ["#2563EB", "#FFFFFF"]

    def test_it_tolerates_fenced_json(self):
        fenced = "```json\n" + json.dumps({"colors": ["#2563EB"], "fonts": []}) + "\n```"
        out = extract_screenshot_tokens([{"type": "image"}], llm=self._llm(fenced))
        assert out["colors"] == ["#2563EB"]

    def test_malformed_hex_is_dropped_not_passed_through(self):
        out = extract_screenshot_tokens(
            [{"type": "image"}],
            llm=self._llm(json.dumps({"colors": ["#2563EB", "blueish", "#GGG", "12345"],
                                      "fonts": []})),
        )
        assert out["colors"] == ["#2563EB"]

    def test_shorthand_hex_is_expanded(self):
        out = extract_screenshot_tokens(
            [{"type": "image"}],
            llm=self._llm(json.dumps({"colors": ["#fff"], "fonts": []})),
        )
        assert out["colors"] == ["#FFFFFF"]

    def test_prose_response_yields_empty_tokens_not_a_crash(self):
        out = extract_screenshot_tokens(
            [{"type": "image"}],
            llm=self._llm("I can see a dashboard with blue accents."))
        assert out["colors"] == []

    def test_non_numeric_radii_are_dropped(self):
        out = extract_screenshot_tokens(
            [{"type": "image"}],
            llm=self._llm(json.dumps({"colors": ["#2563EB"], "fonts": [],
                                      "border_radii": [8, "rounded", None]})),
        )
        assert out["border_radii"] == [8.0]

    def test_no_image_blocks_raises(self):
        with pytest.raises(ScreenshotBriefError):
            extract_screenshot_tokens([], llm=self._llm("{}"))

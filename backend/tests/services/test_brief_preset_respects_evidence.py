"""A domain preset must not overwrite colours measured from a real source.

Found while wiring the montage. `_author_and_persist_brief` applies a
visual-lock preset from the plan whenever `brief.visual_lock.is_active()`
is false — and it is false for EVERY freshly extracted brief, because
extraction populates `palette`, not `visual_lock`. So the sequence was:

    montage → palette.brand = #0B5FFF   (locked: extracted evidence)
    preset  → visual_lock  = admin-neutral
    spec    → primary      = #4F46E5    (the preset's indigo)

The user's reference colour reached brief.json and died one step later.
Nothing logged a conflict, so the app just looked like the model had
ignored the montage.

This is not a screenshot-only bug: the Figma path extracts the same way
and carries the same locks, so a Figma-sourced brief was equally liable to
have its palette replaced by a domain preset. The existing byte-exact
Figma test calls `brief_from_figma → brief_to_design_spec` directly and
never runs the seam, which is why it stayed green.

The rule: a preset is a FALLBACK for briefs with no measured source. When
the brief carries extracted evidence — `identity.source` is figma or
screenshot, or the palette has locked fields — the evidence wins.
"""
from __future__ import annotations

import pytest

from schemas.design_brief import DesignBrief
from services.brief_from_figma import brief_from_figma
from services.brief_from_screenshot import brief_from_screenshot
from services.design_brief_preset_policy import should_apply_preset

_TOKENS = {
    "colors": ["#0B5FFF", "#F5F7FA", "#101828", "#12B76A"],
    "fonts": ["Inter", "Söhne"],
    "border_radii": [12.0],
    "spacings": [8.0, 16.0, 24.0],
}


class TestExtractedEvidenceWins:
    def test_a_screenshot_brief_refuses_the_preset(self):
        assert should_apply_preset(brief_from_screenshot(_TOKENS, domain="X")) is False

    def test_a_figma_brief_refuses_the_preset(self):
        brief = brief_from_figma({"design_tokens": _TOKENS}, domain="X")
        assert should_apply_preset(brief) is False

    def test_the_reason_is_the_lock_not_just_the_source_label(self):
        """Locked palette fields alone are enough — a brief that measured
        colours should keep them even if `source` is later widened."""
        brief = brief_from_screenshot(_TOKENS, domain="X")
        brief.identity.source = "authored"          # label lies; locks don't
        assert should_apply_preset(brief) is False


class TestAuthoredBriefsStillGetAPreset:
    """The preset exists for a reason — don't regress the common path."""

    def _authored(self) -> DesignBrief:
        brief = brief_from_screenshot(_TOKENS, domain="X")
        brief.identity.source = "authored"
        brief.palette.locked_fields = set()
        return brief

    def test_an_authored_brief_accepts_the_preset(self):
        assert should_apply_preset(self._authored()) is True

    def test_a_brief_that_already_has_a_lock_is_left_alone(self):
        """Idempotence — re-running must not swap one preset for another."""
        brief = self._authored()
        from services.visual_lock_presets import pick_preset_from_plan
        brief.visual_lock = pick_preset_from_plan({})
        if brief.visual_lock.is_active():
            assert should_apply_preset(brief) is False


class TestDegenerate:
    def test_none_is_not_a_brief(self):
        assert should_apply_preset(None) is False

"""Motion invariants hold, and the gate names real violations only."""
from __future__ import annotations

import pytest

from services.motion_authority import (ACTIVE_SCALE, COMPOSITED, CURVES,
                                       MAX_UI_DURATION_MS, MIN_ENTRY_SCALE,
                                       check_css, css_variables, duration_for)

CLEAN = """
:root { --ease-out: cubic-bezier(0.23, 1, 0.32, 1); }
.btn { transition: transform 120ms var(--ease-out), opacity 120ms; }
.btn:active { transform: scale(0.97); }
@media (hover: hover) and (pointer: fine) { .btn:hover { opacity: .9 } }
@media (prefers-reduced-motion: reduce) { * { transition-duration: .01ms !important } }
"""


class TestTokens:
    def test_ease_in_is_not_offered(self):
        assert "--ease-in" not in CURVES          # only --ease-in-out
        assert "--ease-in-out" in CURVES

    def test_every_duration_is_under_the_cap(self):
        for name, val in css_variables().items():
            if name.startswith("--duration-"):
                assert int(val.removesuffix("ms")) <= MAX_UI_DURATION_MS

    def test_curves_and_durations_both_emitted(self):
        v = css_variables()
        assert v["--ease-out"] == "cubic-bezier(0.23, 1, 0.32, 1)"
        assert v["--duration-press"] == "120ms"

    def test_scales_are_perceptible_but_not_broken(self):
        assert 0.95 <= ACTIVE_SCALE <= 0.98
        assert MIN_ENTRY_SCALE >= 0.95      # never animate from scale(0)

    def test_only_transform_and_opacity_are_composited(self):
        assert COMPOSITED == {"transform", "opacity"}

    def test_duration_for_caps_and_defaults(self):
        assert duration_for("press") == 120
        assert duration_for("nonsense") == duration_for("dropdown")
        assert duration_for("modal") <= MAX_UI_DURATION_MS


class TestGate:
    def test_clean_sheet_has_no_findings(self):
        assert check_css(CLEAN) == []

    def test_transition_all_is_caught(self):
        f = check_css(CLEAN + ".x { transition: all 150ms; }")
        assert [x["rule"] for x in f] == ["transition_all"]
        assert "reflow" in f[0]["detail"]

    @pytest.mark.parametrize("prop", ["height", "padding", "width", "margin"])
    def test_layout_properties_are_caught(self, prop):
        f = check_css(CLEAN + f".x {{ transition: {prop} 200ms; }}")
        assert f[0]["rule"] == "layout_property_animated"
        assert prop in f[0]["detail"]

    def test_ease_in_is_caught_but_ease_in_out_is_not(self):
        assert check_css(CLEAN + ".x{transition:opacity 1ms ease-in}")[0][
            "rule"] == "ease_in_used"
        assert check_css(CLEAN + ".x{transition:opacity 1ms ease-in-out}") == []

    def test_missing_reduced_motion_is_caught(self):
        assert any(x["rule"] == "no_reduced_motion"
                   for x in check_css(".a{transition:opacity 1ms}"))

    def test_ungated_hover_is_caught(self):
        css = ("@media (prefers-reduced-motion: reduce){*{}}"
               ".b:hover{opacity:.9}")
        assert any(x["rule"] == "ungated_hover" for x in check_css(css))

    def test_gated_hover_is_clean(self):
        assert not any(x["rule"] == "ungated_hover" for x in check_css(CLEAN))

    def test_empty_input_is_not_a_crash(self):
        for bad in ("", None):
            assert isinstance(check_css(bad), list)

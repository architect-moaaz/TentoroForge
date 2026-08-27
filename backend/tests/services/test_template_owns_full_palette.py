"""The design option the user picks must own every palette hex, not two of them.

We research industry-relevant looks, show the user three, and they pick one.
That pick is the strongest colour signal in the system — stronger than the
brief, the domain preset, or anything derived. But only `primary` and
`accent` ever came from it.

`template_to_design_spec` filled the other roles from `_NEUTRALS[mode]`, a
fixed two-row table: every light template got #FFFFFF / #F8FAFC / #0F172A,
every dark one got #0F172A / #1E293B / #F1F5F9. So "Calm clinical" and
"Warm retail" — deliberately different directions — shipped byte-identical
backgrounds, surfaces and text colours. Only the two brand hues differed,
which is why picking a different option changed so much less than it looked
like it should.

Worse, four of those roles (`surfaceHover`, `textPrimary`, `textSecondary`,
`textTertiary`) could not be expressed by a template at all: `guard_template`
dropped them, so even a template that named them was ignored.

The rule: every role the selection names is used verbatim. `_NEUTRALS[mode]`
stays, demoted to a backfill for the roles a sparse template leaves out — an
older cached template, or a researcher response that only returned two hues,
must still render.
"""
from __future__ import annotations

from services.design_templates import (
    guard_template,
    seed_design_spec,
    template_to_design_spec,
    HOUSE_TEMPLATES,
)

# All seven roles named explicitly, none of them the _NEUTRALS defaults.
_FULL = {
    "id": "user-pick", "name": "User pick", "vibe": "chosen",
    "palette": {
        "primary": "#0B5FFF", "accent": "#12B76A", "mode": "light",
        "background": "#FFFBF5",      # warm cream, not #FFFFFF
        "surface": "#F6EFE4",         # not #F8FAFC
        "surfaceHover": "#EFE4D4",    # not #F1F5F9
        "textPrimary": "#2B1B0E",     # not #0F172A
        "textSecondary": "#6B5741",   # not #475569
        "textTertiary": "#A08straight",  # deliberately invalid — see clamp test
    },
    "typography": {"headingFont": "Fraunces", "bodyFont": "Inter", "scale": "airy"},
    "tokens": {"density": "spacious", "radiusScale": "rounded",
               "elevation": "soft", "motionLevel": "subtle"},
    "shell": {"frame": "topbar", "tone": "light"},
}


def _valid_full() -> dict:
    t = {**_FULL, "palette": {**_FULL["palette"], "textTertiary": "#A08B72"}}
    return t


class TestEveryNamedRoleSurvives:
    def test_all_seven_reach_the_design_spec_verbatim(self):
        pal = template_to_design_spec(_valid_full())["colorPalette"]
        assert pal["primary"] == "#0B5FFF"
        assert pal["accent"] == "#12B76A"
        assert pal["background"] == "#FFFBF5"
        assert pal["surface"] == "#F6EFE4"
        assert pal["surfaceHover"] == "#EFE4D4"
        assert pal["textPrimary"] == "#2B1B0E"
        assert pal["textSecondary"] == "#6B5741"

    def test_the_guard_no_longer_drops_the_five_neutral_roles(self):
        """Before: guard_template kept only background/surface/sidebar*, so a
        template naming textPrimary lost it before the mapping ever ran."""
        clean, _ = guard_template(_valid_full())
        for role in ("surfaceHover", "textPrimary", "textSecondary", "textTertiary"):
            assert clean["palette"].get(role), f"{role} dropped by the guard"

    def test_two_different_options_no_longer_share_a_background(self):
        """The symptom: picking a different look barely changed the app."""
        warm = _valid_full()
        cool = {**_valid_full(), "palette": {**_valid_full()["palette"],
                                             "background": "#F7FAFF",
                                             "textPrimary": "#0A1B2B"}}
        a = template_to_design_spec(warm)["colorPalette"]
        b = template_to_design_spec(cool)["colorPalette"]
        assert a["background"] != b["background"]
        assert a["textPrimary"] != b["textPrimary"]

    def test_selection_survives_the_merge_onto_an_existing_spec(self):
        """seed_design_spec is what the pipeline actually calls."""
        existing = {"colorPalette": {"primary": "#4F46E5", "background": "#FFFFFF",
                                     "textPrimary": "#111111"},
                    "somethingElse": "preserved"}
        out = seed_design_spec(existing, _valid_full())
        assert out["colorPalette"]["primary"] == "#0B5FFF"
        assert out["colorPalette"]["background"] == "#FFFBF5"
        assert out["colorPalette"]["textPrimary"] == "#2B1B0E"
        assert out["somethingElse"] == "preserved"


class TestSparseTemplatesStillRender:
    """A cached template or a thin researcher response names only two hues."""

    def _sparse(self, mode: str = "light") -> dict:
        return {"id": "sparse", "name": "Sparse",
                "palette": {"primary": "#0B5FFF", "accent": "#12B76A", "mode": mode},
                "typography": {"headingFont": "Inter", "bodyFont": "Inter", "scale": "balanced"},
                "tokens": {"density": "comfortable", "radiusScale": "soft",
                           "elevation": "soft", "motionLevel": "subtle"},
                "shell": {"frame": "topbar", "tone": "light"}}

    def test_missing_roles_backfill_from_the_mode_table(self):
        pal = template_to_design_spec(self._sparse("light"))["colorPalette"]
        assert pal["background"] == "#FFFFFF"
        assert pal["textPrimary"] == "#0F172A"

    def test_dark_mode_backfill_still_works(self):
        pal = template_to_design_spec(self._sparse("dark"))["colorPalette"]
        assert pal["background"] == "#0F172A"
        assert pal["textPrimary"] == "#F1F5F9"

    def test_named_roles_win_over_backfill_when_only_some_are_given(self):
        t = self._sparse()
        t["palette"]["background"] = "#FFFBF5"
        pal = template_to_design_spec(t)["colorPalette"]
        assert pal["background"] == "#FFFBF5"       # named
        assert pal["textPrimary"] == "#0F172A"      # backfilled


class TestGarbageIsStillClamped:
    def test_a_non_hex_role_falls_back_rather_than_reaching_css(self):
        pal = template_to_design_spec(_FULL)["colorPalette"]   # textTertiary invalid
        assert pal["textTertiary"] == "#94A3B8"                # light-mode default

    def test_guard_never_raises_on_junk(self):
        clean, _ = guard_template({"palette": {"primary": 42, "textPrimary": None}})
        assert clean["palette"]["primary"].startswith("#")


class TestHouseTemplatesAreHonest:
    """The deterministic fallbacks are what ships when research fails, so they
    must exercise the same contract rather than relying on the mode table."""

    def test_every_house_template_names_its_own_neutrals(self):
        thin = [t["id"] for t in HOUSE_TEMPLATES
                if not all(t.get("palette", {}).get(r)
                           for r in ("background", "surface", "textPrimary"))]
        assert not thin, f"house templates still leaning on _NEUTRALS: {thin}"

    def test_house_templates_do_not_all_share_one_background(self):
        backgrounds = {t["palette"]["background"] for t in HOUSE_TEMPLATES}
        assert len(backgrounds) > 1, "house looks are still visually interchangeable"

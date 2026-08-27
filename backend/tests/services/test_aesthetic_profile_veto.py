"""Tests for the brief-aware veto in ``services.aesthetic_profile_picker``.

The veto exists to prevent brutalist (IBM-Carbon-style) skins from
landing on calm/warm briefs — the yoga→carbon mismatch class. Each
test pins one behaviour of the veto so regressions read as a single
failure with a legible message rather than a mysterious profile flip.
"""
from __future__ import annotations

import pytest

from services import aesthetic_profile_picker
from services.aesthetic_profile_picker import (
    _BRUTALIST_PROFILE_NAMES,
    _is_vetoed_by_brief,
    pick,
    pick_profile,
)


# ── word / temperature reader ────────────────────────────────────────


class TestBriefStanceWords:
    def test_missing_brief_is_empty(self):
        words, temp = aesthetic_profile_picker._brief_stance_words(None)
        assert words == frozenset()
        assert temp is None

    def test_missing_identity_is_empty(self):
        words, temp = aesthetic_profile_picker._brief_stance_words({})
        assert words == frozenset()
        assert temp is None

    def test_reads_principles_and_register_and_temperature(self):
        brief = {
            "identity": {
                "register": ["warm", "editorial"],
                "visual_stance": {
                    "temperature": "warm",
                    "principles": ["calm restraint", "human"],
                },
            }
        }
        words, temp = aesthetic_profile_picker._brief_stance_words(brief)
        assert temp == "warm"
        # Multi-word principles split on whitespace so component words
        # register (a brief that says "calm restraint" matches both).
        assert {"warm", "editorial", "calm", "restraint", "human"} <= words

    def test_temperature_case_and_whitespace_normalized(self):
        brief = {"identity": {"visual_stance": {"temperature": "  WARM  "}}}
        _, temp = aesthetic_profile_picker._brief_stance_words(brief)
        assert temp == "warm"

    def test_snake_case_register_extracts_component_words(self):
        # Real briefs use tokens like ``grounded_calm`` /
        # ``purposeful_clear`` / ``warm_precise`` — the reader must
        # split on ``_`` / ``-`` / ``/`` so downstream veto rules see
        # the ``calm`` / ``warm`` signal words.
        brief = {
            "identity": {
                "register": ["grounded_calm", "purposeful_clear"],
                "voice": None,
                "visual_stance": {"principles": ["warm-precise"]},
            }
        }
        words, _ = aesthetic_profile_picker._brief_stance_words(brief)
        assert {"grounded", "calm", "purposeful", "clear",
                "warm", "precise"} <= words

    def test_snake_case_brief_vetoes_carbon(self):
        # The exact shape 4noe2jyh's yoga brief takes — ensures a real
        # generated brief with underscored register values still trips
        # the brutalist veto.
        brief = {
            "identity": {
                "register": ["grounded_calm", "purposeful_clear"],
                "visual_stance": {"principles": []},
            }
        }
        assert _is_vetoed_by_brief("carbon", brief) is True

    def test_non_string_items_ignored(self):
        brief = {
            "identity": {
                "register": [None, 42, "warm"],
                "visual_stance": {"principles": [None, "calm"]},
            }
        }
        words, _ = aesthetic_profile_picker._brief_stance_words(brief)
        assert "warm" in words
        assert "calm" in words


# ── veto function ────────────────────────────────────────────────────


class TestIsVetoedByBrief:
    def test_no_brief_no_veto(self):
        assert _is_vetoed_by_brief("carbon", None) is False

    def test_non_brutalist_profile_never_vetoed(self):
        # Even a very calm brief can't veto a non-brutalist profile —
        # the veto only exists to reject the sharp/monochrome family.
        brief = {"identity": {"visual_stance": {"temperature": "warm",
                                                "principles": ["calm"]}}}
        for name in ("polaris", "material-3", "fluent-2",
                     "clean-editorial", "glass-dark"):
            assert _is_vetoed_by_brief(name, brief) is False, name

    def test_warm_temperature_vetoes_carbon(self):
        # This is the yoga→carbon bug case in miniature: a brief that
        # says its aesthetic is warm should never land on carbon.
        brief = {"identity": {"visual_stance": {"temperature": "warm"}}}
        assert _is_vetoed_by_brief("carbon", brief) is True

    def test_cool_temperature_never_vetoes(self):
        # A cool-tempered brief is allowed to pick carbon — that's the
        # legitimate "cool minimalist" use case the profile was built
        # for. Even calm-word principles on a cool brief don't veto.
        brief = {"identity": {"visual_stance": {"temperature": "cool",
                                                "principles": ["calm"]}}}
        assert _is_vetoed_by_brief("carbon", brief) is False

    def test_calm_word_on_neutral_temperature_vetoes(self):
        # Temperature is neutral (or absent), but a principle/register
        # word signals calm/warm — carbon still vetoed. This is the
        # main real-world case, since many briefs leave temperature
        # unset but declare "friendly" / "welcoming" principles.
        brief = {"identity": {"register": ["friendly"]}}
        assert _is_vetoed_by_brief("carbon", brief) is True

    def test_no_calm_signals_no_veto(self):
        # An enterprise/dev-tools brief with no calm-word signals is
        # eligible for carbon — the veto stays out of the way.
        brief = {"identity": {"register": ["precise", "industrial"],
                              "visual_stance": {"principles": ["restraint"]}}}
        # "restraint" is a calm-signal word by design (editorial-style
        # briefs shouldn't get brutalist skins either), so we expect
        # this to veto. Kept as a positive test to pin the choice.
        assert _is_vetoed_by_brief("carbon", brief) is True

    def test_industrial_brief_not_vetoed(self):
        # Truly enterprise-style brief with no calm-word coverage —
        # carbon remains eligible.
        brief = {"identity": {"register": ["precise", "clinical"],
                              "visual_stance": {"principles": ["technical"]}}}
        assert _is_vetoed_by_brief("carbon", brief) is False


# ── pick() end-to-end integration ────────────────────────────────────


class TestPickWithBrief:
    def setup_method(self):
        # Clear the profile cache so on-disk profile edits don't leak
        # across tests, and so the module state is fresh per-case.
        aesthetic_profile_picker.clear_cache()

    def test_yoga_wellness_brief_never_picks_carbon(self):
        # The exact class of bug that motivated this fix: a wellness
        # domain brief with a warm/friendly register would previously
        # tie-break onto carbon and land IBM Plex + hairline hairboxes
        # on a yoga app. With the veto + tie-break demotion, it never
        # picks carbon regardless of app_shape signals.
        plan = {
            "industry": "wellness",
            "app_shape": {
                "layout": {"density": "comfortable"},
                "identity": {"usageMode": "multi-user-team"},
            },
        }
        brief = {
            "identity": {
                "register": ["warm", "welcoming"],
                "visual_stance": {
                    "temperature": "warm",
                    "principles": ["calm", "human"],
                },
            }
        }
        picked = pick(plan, brief=brief)
        assert picked != "carbon", (
            f"warm/wellness brief must not pick carbon, got {picked!r}"
        )

    def test_veto_applies_to_all_brutalist_profiles(self):
        # If a new profile joins the brutalist set later, this test
        # generalises to it too — every profile in the set must be
        # rejected for a calm brief.
        brief = {"identity": {"visual_stance": {"temperature": "warm"}}}
        for name in _BRUTALIST_PROFILE_NAMES:
            picked = pick({"aesthetic_profile": name}, brief=brief)
            # Explicit override still wins (documented behaviour): an
            # author asking for the brutalist profile by name gets it.
            assert picked == name
        # But when no override is set, none of them can win on score.
        picked = pick({"app_shape": {"layout": {"density": "dense",
                                                "primaryInteraction": "data-grid"}}},
                      brief=brief)
        assert picked not in _BRUTALIST_PROFILE_NAMES

    def test_no_brief_falls_back_to_old_behavior(self):
        # Callers without a brief (e.g. legacy sites, tests) get the
        # picker's original behaviour — no veto layer applied.
        plan = {
            "app_shape": {
                "layout": {"density": "dense", "primaryInteraction": "data-grid"},
                "identity": {"usageMode": "multi-user-team"},
            }
        }
        assert pick(plan) == "carbon"
        assert pick(plan, brief=None) == "carbon"

    def test_explicit_aesthetic_profile_override_bypasses_veto(self):
        # An author who explicitly names carbon in the plan gets carbon
        # even on a warm brief. The veto only intervenes when the
        # picker is scoring — not when the author has already made a
        # deliberate choice.
        brief = {"identity": {"visual_stance": {"temperature": "warm"}}}
        plan = {"aesthetic_profile": "carbon"}
        assert pick(plan, brief=brief) == "carbon"

    def test_cool_brief_can_still_pick_carbon(self):
        # A "cool minimalist" wellness app — the picker still lets
        # carbon win when the brief's temperature signals cool. This
        # is the legitimate case the veto is designed to leave alone.
        plan = {
            "app_shape": {
                "layout": {"density": "dense", "primaryInteraction": "data-grid"},
                "identity": {"usageMode": "multi-user-team"},
            }
        }
        brief = {"identity": {"visual_stance": {"temperature": "cool"}}}
        assert pick(plan, brief=brief) == "carbon"

    def test_pick_profile_threads_brief(self):
        # pick_profile is a thin wrapper — make sure it actually passes
        # brief through so callers who use it (surface_treatment_pass,
        # critic_personas) benefit from the veto too.
        brief = {"identity": {"visual_stance": {"temperature": "warm"}}}
        plan = {
            "app_shape": {
                "layout": {"density": "dense", "primaryInteraction": "data-grid"},
                "identity": {"usageMode": "multi-user-team"},
            }
        }
        profile = pick_profile(plan, brief=brief)
        assert profile.get("name") != "carbon"

    def test_pydantic_model_style_brief_also_works(self):
        # The picker is called with both dict-shaped briefs (loaded
        # from disk as JSON) and pydantic-model briefs (returned by
        # ``load_brief_from_disk``). The reader walks attributes and
        # keys uniformly so both shapes veto correctly.
        class _S:  # tiny stand-in for VisualStance
            temperature = "warm"
            principles = ["calm"]

        class _I:
            register = ["warm"]
            visual_stance = _S()

        class _B:
            identity = _I()

        brief = _B()
        plan = {
            "app_shape": {
                "layout": {"density": "dense", "primaryInteraction": "data-grid"},
                "identity": {"usageMode": "multi-user-team"},
            }
        }
        assert pick(plan, brief=brief) != "carbon"


# ── tie-break re-ordering ────────────────────────────────────────────


class TestTieBreakReordering:
    def setup_method(self):
        aesthetic_profile_picker.clear_cache()

    def test_carbon_no_longer_wins_tie_over_material_or_fluent(self):
        # A plan whose signals produce a score-tie between carbon and
        # material-3/fluent-2 used to hand the win to carbon (it was
        # 2nd in tie-break order). Now carbon is last — so tied scores
        # go to the softer profile. If no dimension differentiates
        # carbon from material-3/fluent-2, whichever is earlier in the
        # new tie-break order wins.
        # A brief-free plan that scores carbon = fluent-2 = material-3
        # = 1 (each matches only ``usageMode=multi-user-team``) should
        # now break to polaris/material-3/fluent-2 before carbon.
        plan = {
            "app_shape": {"identity": {"usageMode": "multi-user-team"}},
        }
        picked = pick(plan)
        assert picked != "carbon", (
            f"tie-break should no longer hand ties to carbon; got {picked!r}"
        )

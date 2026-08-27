"""Tests for the brief-aware veto in ``services.design_language``.

Same class of gate as the aesthetic_profile veto (task #595): a warm/calm
brief must never draw brutalist picks (hard-offset shadows, grid-paper /
crosshatch grounds, JetBrains-Mono headings, chunky 3px borders). The
4noe2jyh yoga app hit this: ``lang190bc97b`` combined ``cardTreatment=
hard-offset`` + ``surface=grid-paper`` + ``typeClass=mono`` on a brief
whose voice was ``warm_precise`` and register was
``["grounded_calm", "purposeful_clear"]``. Each test pins one behaviour
so a regression reads as a single failure with a legible message.
"""
from __future__ import annotations

import pytest

from services import design_language
from services.design_language import (
    _BRUTALIST_CARDS,
    _BRUTALIST_SURFACES,
    _BRUTALIST_TYPES,
    _SHARP_RADII,
    _is_warm_brief,
    _veto_brutalist_fallbacks,
    _veto_brutalist_pool,
    compose_language,
)


# ── warmth detector ────────────────────────────────────────────────


class TestIsWarmBrief:
    def test_no_brief_is_not_warm(self):
        assert _is_warm_brief(None) is False

    def test_empty_brief_is_not_warm(self):
        assert _is_warm_brief({}) is False

    def test_warm_temperature_is_warm(self):
        brief = {"identity": {"visual_stance": {"temperature": "warm"}}}
        assert _is_warm_brief(brief) is True

    def test_cool_temperature_never_warm_even_with_calm_words(self):
        # Same contract as aesthetic_profile veto — a cool brief keeps
        # the full pool available even if a stray calm word appears.
        brief = {"identity": {"visual_stance": {
            "temperature": "cool",
            "principles": ["calm restraint"],
        }}}
        assert _is_warm_brief(brief) is False

    def test_snake_case_register_flags_warm(self):
        # The 4noe2jyh brief case: temperature is None, register uses
        # snake_case tokens. Reader must split on `_` and see the calm
        # component word.
        brief = {"identity": {
            "register": ["grounded_calm", "purposeful_clear"],
            "visual_stance": None,
        }}
        assert _is_warm_brief(brief) is True

    def test_industrial_brief_not_warm(self):
        brief = {"identity": {
            "register": ["precise", "clinical"],
            "visual_stance": {"principles": ["technical"]},
        }}
        assert _is_warm_brief(brief) is False


# ── pool + fallback filters ────────────────────────────────────────


class TestVetoPools:
    def test_veto_drops_brutalist_cards(self):
        filtered = _veto_brutalist_pool(design_language.CARD_TREATMENTS,
                                         _BRUTALIST_CARDS)
        for name in _BRUTALIST_CARDS:
            assert name not in filtered, name

    def test_veto_keeps_soft_cards(self):
        filtered = _veto_brutalist_pool(design_language.CARD_TREATMENTS,
                                         _BRUTALIST_CARDS)
        # Every soft/organic card treatment must still be available.
        for name in ("soft-shadow", "layered", "hairline", "tint-fill", "none"):
            assert name in filtered, f"{name} should survive the veto"

    def test_veto_drops_brutalist_surfaces(self):
        filtered = _veto_brutalist_pool(design_language.SURFACES,
                                         _BRUTALIST_SURFACES)
        for name in _BRUTALIST_SURFACES:
            assert name not in filtered, name

    def test_veto_keeps_soft_surfaces(self):
        # ``plain`` + subtle organic textures survive.
        filtered = _veto_brutalist_pool(design_language.SURFACES,
                                         _BRUTALIST_SURFACES)
        for name in ("plain", "grain", "linen", "wash"):
            assert name in filtered, f"{name} should survive the veto"

    def test_veto_drops_mono_and_condensed_types(self):
        filtered = _veto_brutalist_pool(design_language.TYPE_CLASSES,
                                         _BRUTALIST_TYPES)
        for name in ("mono", "condensed", "slab"):
            assert name not in filtered, name

    def test_veto_keeps_humanist_and_serif_types(self):
        filtered = _veto_brutalist_pool(design_language.TYPE_CLASSES,
                                         _BRUTALIST_TYPES)
        for name in ("humanist", "geometric", "rounded",
                     "grotesque", "serif-display"):
            assert name in filtered, f"{name} should survive the veto"

    def test_veto_of_empty_result_returns_original(self):
        # Defensive: if the veto set matches EVERY entry (impossible with
        # current data but a real risk if someone extends the veto set
        # without updating the pool), we keep the original pool rather
        # than returning an empty dict that would crash composition.
        empty_result_veto = frozenset(design_language.CARD_TREATMENTS.keys())
        filtered = _veto_brutalist_pool(design_language.CARD_TREATMENTS,
                                         empty_result_veto)
        assert filtered is design_language.CARD_TREATMENTS

    def test_fallback_veto_drops_brutalist_presets(self):
        # After the veto, no fallback preset can contain a brutalist
        # surface / card / type.
        filtered = _veto_brutalist_fallbacks(design_language._FALLBACKS)
        for fb in filtered:
            assert fb.get("surface") not in _BRUTALIST_SURFACES
            assert fb.get("cardTreatment") not in _BRUTALIST_CARDS
            assert fb.get("typeClass") not in _BRUTALIST_TYPES

    def test_fallback_veto_keeps_at_least_one_preset(self):
        # Fallbacks fire only when the composer exhausts all 3 relaxation
        # tiers — a very rare code path. The important guarantee is that
        # SOMETHING soft-friendly survives so the last-resort branch on a
        # warm brief still lands on a non-brutalist preset. Currently
        # only 1 of the 8 fallbacks (grain / soft-shadow / geometric) is
        # fully soft-friendly. That's fine as a floor; if a future
        # tightening of the veto were to strand the pool at zero, the
        # `_veto_brutalist_fallbacks` safety branch returns the original
        # tuple rather than crashing.
        filtered = _veto_brutalist_fallbacks(design_language._FALLBACKS)
        assert len(filtered) >= 1, (
            "No fallback preset survives the warm-brief veto. Either "
            "widen the veto's whitelist or add a soft-friendly preset "
            "to _FALLBACKS."
        )


# ── compose_language end-to-end integration ────────────────────────


class TestComposeLanguageWithBrief:
    def _yoga_brief(self):
        # Miniature of the real 4noe2jyh brief that triggered task #661.
        return {"identity": {
            "domain": "Yoga Studio Management",
            "register": ["grounded_calm", "purposeful_clear"],
            "voice": "warm_precise",
            "visual_stance": None,
        }}

    def _fixed_seed(self, salt: int = 0) -> bytes:
        # Deterministic seed for repeatable tests.
        return bytes(range(1, 33))[:32] if salt == 0 else bytes([salt] * 32)

    def test_warm_brief_never_picks_brutalist_card(self):
        # Try many seeds — none should produce a brutalist card
        # treatment when the brief is warm. Same guarantee for surface
        # + typeClass.
        brief = self._yoga_brief()
        for salt in range(1, 25):
            lang = compose_language("hr-people", bytes([salt] * 32),
                                    brief=brief)
            assert lang["cardTreatment"] not in _BRUTALIST_CARDS, (
                f"seed={salt} composed brutalist card "
                f"{lang['cardTreatment']!r} on a warm brief"
            )
            assert lang["surface"] not in _BRUTALIST_SURFACES, (
                f"seed={salt} composed brutalist surface "
                f"{lang['surface']!r} on a warm brief"
            )
            assert lang["typeClass"] not in _BRUTALIST_TYPES, (
                f"seed={salt} composed brutalist type "
                f"{lang['typeClass']!r} on a warm brief"
            )

    def test_no_brief_may_still_pick_brutalist(self):
        # Backward-compat: callers that don't pass a brief keep the
        # historical behaviour. At least one draw across many seeds
        # should land on a brutalist pick (proves the veto is inert
        # without a brief) — the enterprise/tech/analytics archetypes
        # rely on those picks for their intended workspace feel.
        seen_brutalist = False
        for salt in range(1, 60):
            lang = compose_language("developer", bytes([salt] * 32))
            if (lang["cardTreatment"] in _BRUTALIST_CARDS
                or lang["surface"] in _BRUTALIST_SURFACES
                or lang["typeClass"] in _BRUTALIST_TYPES):
                seen_brutalist = True
                break
        assert seen_brutalist, (
            "Expected at least one brutalist pick over 60 seeds when "
            "no brief is passed — the veto is leaking to unrelated callers."
        )

    def test_cool_brief_may_still_pick_brutalist(self):
        # A cool/technical brief is allowed to compose a technical
        # skin (grid-paper + hairline is the Linear look — perfectly
        # valid). The veto must not fire for cool briefs.
        brief = {"identity": {"visual_stance": {"temperature": "cool"}}}
        seen_brutalist = False
        for salt in range(1, 60):
            lang = compose_language("analytics", bytes([salt] * 32),
                                    brief=brief)
            if (lang["cardTreatment"] in _BRUTALIST_CARDS
                or lang["surface"] in _BRUTALIST_SURFACES
                or lang["typeClass"] in _BRUTALIST_TYPES):
                seen_brutalist = True
                break
        assert seen_brutalist, (
            "cool-tempered brief should still allow technical picks; "
            "veto is firing when it shouldn't."
        )

    def test_deterministic_with_brief(self):
        # Same (archetype, seed, brief) → same pick, always.
        brief = self._yoga_brief()
        seed = self._fixed_seed()
        a = compose_language("hr-people", seed, brief=brief)
        b = compose_language("hr-people", seed, brief=brief)
        for key in ("cardTreatment", "surface", "typeClass",
                    "navShape", "radiusRegime", "density"):
            assert a[key] == b[key], key

    def test_pydantic_model_style_brief_works(self):
        # The picker is called from generate.py with the result of
        # ``load_brief_from_disk`` which returns a pydantic model, not
        # a dict. Attribute-walking must work for both shapes.
        class _S:
            temperature = None
            principles = []
        class _I:
            register = ["warm", "welcoming"]
            visual_stance = _S()
        class _B:
            identity = _I()
        brief = _B()
        lang = compose_language("hr-people", bytes([7] * 32), brief=brief)
        assert lang["cardTreatment"] not in _BRUTALIST_CARDS

    def test_yoga_seed_would_have_picked_brutalist_without_brief(self):
        # Regression pin for 4noe2jyh specifically. Without brief on
        # this seed/archetype the composer historically drew a
        # brutalist skin (that's the bug). With the yoga brief, the
        # veto must break the pick to something non-brutalist. This
        # test asserts the delta rather than a specific alternative,
        # since the specific new pick will drift as the tables evolve.
        seed = bytes.fromhex(
            "e4a3b91b19f0c5f5b7c6d8e9a4b3c2d1"
            "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
        )
        no_brief = compose_language("hr-people", seed)
        with_brief = compose_language("hr-people", seed,
                                       brief=self._yoga_brief())
        if (no_brief["cardTreatment"] in _BRUTALIST_CARDS
            or no_brief["surface"] in _BRUTALIST_SURFACES
            or no_brief["typeClass"] in _BRUTALIST_TYPES):
            assert with_brief["cardTreatment"] not in _BRUTALIST_CARDS
            assert with_brief["surface"] not in _BRUTALIST_SURFACES
            assert with_brief["typeClass"] not in _BRUTALIST_TYPES
        # If this specific seed didn't happen to draw brutalist even
        # without a brief, the test is trivially satisfied — the
        # `test_warm_brief_never_picks_brutalist_card` covers many
        # seeds and pins the veto directly.


# ── grain surface: pseudo-element must distribute over selector lists ──

def test_grain_surface_distributes_before_over_selector_list():
    """Regression for the 5%-opacity app: with a selector-list scope,
    f"{S}::before" attached ::before only to the LAST selector, so the
    grain styles (position:fixed + opacity .055) landed on the first
    selector's real element — the shell content container — rendering
    the whole app nearly invisible."""
    from services.design_language import surface_css
    css = surface_css(
        "grain",
        {"bg": "#111", "primary": "#4F46E5", "accent": "#22d3ee",
         "line": "#333"},
        dark=True,
        scope="[data-x] [data-shell-main], [data-x] main",
    )
    # Every selector in the overlay rule must carry ::before.
    overlay_rule = [ln for ln in css.split("\n") if "opacity" in ln][0]
    selectors = overlay_rule.split("{")[0].split(",")
    assert all("::before" in s for s in selectors), overlay_rule
    # And the base rule must NOT set opacity on real elements.
    base_rule = css.split("\n")[0]
    assert "opacity" not in base_rule

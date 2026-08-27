"""Spec D Wave 1 — additive scaffolding tests for design-brief schema.

Verifies the three new Identity fields (visual_stance, auth_taglines,
product_name_candidates) plus the standalone VisualStance model:

  * All new fields optional; old briefs load unchanged.
  * VisualStance accepts partial authoring.
  * Size caps hold (auth_taglines ≤ 2; product_name_candidates ≤ 6;
    principles ≤ 4; string caps).
  * Enum-shape fields reject invalid values.

Every test constructs the model directly; the pipeline consumers stay
untouched in Wave 1 (they still read the ARCHETYPES / AUTH_COPY dicts).
"""
from __future__ import annotations

import pytest

from schemas.design_brief import (
    DesignBrief,
    Identity,
    Layout,
    Palette,
    SignatureMove,
    Typography,
    VisualStance,
)


def _base_brief_kwargs() -> dict:
    return dict(
        identity=Identity(domain="Recruitment", register=["structured"],
                          voice="warm_precise"),
        palette=Palette(brand="#2D5A8E", accent="#E8A020",
                        neutrals_base="#F5F5F5", neutrals_tint="cool",
                        surface_bg="#FFFFFF", surface_elevated="#FFFFFF",
                        foreground_primary="#111111",
                        foreground_muted="#666666"),
        typography=Typography(display_family="Inter", body_family="Inter"),
        layout=Layout(density="compact", radius="soft_8"),
        signature_moves=[SignatureMove(kind="warm_serif_h1", detail="x")],
    )


# ── Identity field defaults ──────────────────────────────────────────

class TestIdentityDefaults:
    def test_visual_stance_defaults_to_none(self):
        i = Identity(domain="D", register=["a"], voice="warm_precise")
        assert i.visual_stance is None

    def test_auth_taglines_defaults_to_empty_list(self):
        i = Identity(domain="D", register=["a"], voice="warm_precise")
        assert i.auth_taglines == []

    def test_product_name_candidates_defaults_to_empty_list(self):
        i = Identity(domain="D", register=["a"], voice="warm_precise")
        assert i.product_name_candidates == []

    def test_full_brief_without_new_fields_still_valid(self):
        # Regression: an existing serialized brief lacking any Wave 1
        # field must still validate cleanly.
        b = DesignBrief(**_base_brief_kwargs())
        assert b.identity.visual_stance is None
        assert b.identity.auth_taglines == []
        assert b.identity.product_name_candidates == []


# ── Identity field acceptance ────────────────────────────────────────

class TestIdentityAcceptance:
    def test_visual_stance_accepts_full_shape(self):
        i = Identity(
            domain="D", register=["a"], voice="warm_precise",
            visual_stance=VisualStance(
                hue_range="cool blues", temperature="cool",
                shape_vocab="geometric",
                principles=["restraint", "precision"],
            ),
        )
        assert i.visual_stance is not None
        assert i.visual_stance.temperature == "cool"
        assert i.visual_stance.principles == ["restraint", "precision"]

    def test_auth_taglines_accepts_up_to_two(self):
        i = Identity(domain="D", register=["a"], voice="warm_precise",
                     auth_taglines=["Welcome back.", "Let's get to work."])
        assert len(i.auth_taglines) == 2

    def test_auth_taglines_rejects_three(self):
        with pytest.raises(Exception):
            Identity(domain="D", register=["a"], voice="warm_precise",
                     auth_taglines=["a", "b", "c"])

    def test_product_name_candidates_accepts_up_to_six(self):
        i = Identity(domain="D", register=["a"], voice="warm_precise",
                     product_name_candidates=list("abcdef"))
        assert len(i.product_name_candidates) == 6

    def test_product_name_candidates_rejects_seven(self):
        with pytest.raises(Exception):
            Identity(domain="D", register=["a"], voice="warm_precise",
                     product_name_candidates=list("abcdefg"))


# ── VisualStance standalone ──────────────────────────────────────────

class TestVisualStance:
    def test_empty_construction_ok(self):
        # Partial authoring is safe — every field optional.
        v = VisualStance()
        assert v.hue_range is None
        assert v.temperature is None
        assert v.shape_vocab is None
        assert v.principles == []

    def test_partial_authoring_ok(self):
        v = VisualStance(temperature="warm")
        assert v.temperature == "warm"
        assert v.hue_range is None

    def test_temperature_enum_rejects_unknown(self):
        with pytest.raises(Exception):
            VisualStance(temperature="lukewarm")

    def test_hue_range_max_40_chars(self):
        VisualStance(hue_range="x" * 40)  # OK
        with pytest.raises(Exception):
            VisualStance(hue_range="x" * 41)

    def test_shape_vocab_max_40_chars(self):
        VisualStance(shape_vocab="x" * 40)
        with pytest.raises(Exception):
            VisualStance(shape_vocab="x" * 41)

    def test_principles_max_four_items(self):
        VisualStance(principles=["a", "b", "c", "d"])
        with pytest.raises(Exception):
            VisualStance(principles=["a", "b", "c", "d", "e"])


# ── Whole brief with all Wave 1 fields ───────────────────────────────

class TestBriefWithWave1Fields:
    def test_brief_with_all_wave1_fields_ok(self):
        kw = _base_brief_kwargs()
        kw["identity"] = Identity(
            domain="Recruitment", register=["structured"],
            voice="warm_precise",
            visual_stance=VisualStance(temperature="cool",
                                       principles=["restraint"]),
            auth_taglines=["Welcome back."],
            product_name_candidates=["Forge", "Anvil"],
        )
        b = DesignBrief(**kw)
        assert b.identity.visual_stance.temperature == "cool"
        assert b.identity.auth_taglines == ["Welcome back."]
        assert b.identity.product_name_candidates == ["Forge", "Anvil"]

    def test_roundtrip_via_model_dump_and_validate(self):
        kw = _base_brief_kwargs()
        kw["identity"] = Identity(
            domain="Recruitment", register=["structured"],
            voice="warm_precise",
            visual_stance=VisualStance(temperature="cool"),
            auth_taglines=["Welcome."],
        )
        b = DesignBrief(**kw)
        dumped = b.model_dump()
        b2 = DesignBrief.model_validate(dumped)
        assert b2.identity.visual_stance.temperature == "cool"
        assert b2.identity.auth_taglines == ["Welcome."]

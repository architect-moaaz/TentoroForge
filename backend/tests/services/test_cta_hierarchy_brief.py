"""Tests for Spec D Wave 3 — brief-authored cta_hierarchy.

Additive: brief.cta_hierarchy is optional. When present, flows into
design_spec.cta_hierarchy so schema_prompt's existing
`design_spec.get("cta_hierarchy") or defaults_for_register(...)` pattern
picks the brief-authored version. When absent, downstream falls back to
cta_defaults.defaults_for_register unchanged.
"""
from __future__ import annotations

import pytest

from schemas.design_brief import (
    ContentBank, CtaHierarchy, CtaRule, DesignBrief, Identity, Layout,
    Palette, SignatureMove, Typography,
)
from services.brief_to_design_spec import brief_to_design_spec
from services.cta_defaults import defaults_for_register


def _base_brief(**overrides) -> DesignBrief:
    kwargs = dict(
        identity=Identity(domain="Test", register=["structured"], voice="warm_precise"),
        palette=Palette(brand="#2D5A8E", accent="#E8A020",
                        neutrals_base="#F5F5F5", neutrals_tint="cool",
                        surface_bg="#FFFFFF", surface_elevated="#FFFFFF",
                        foreground_primary="#111111", foreground_muted="#666666"),
        typography=Typography(display_family="X", body_family="X"),
        layout=Layout(density="compact", radius="soft_8", grid="12col"),
        signature_moves=[SignatureMove(kind="warm_serif_h1", detail="x")],
    )
    kwargs.update(overrides)
    return DesignBrief(**kwargs)


class TestSchema:
    def test_cta_hierarchy_default_is_none(self):
        b = _base_brief()
        assert b.cta_hierarchy is None

    def test_cta_hierarchy_accepted(self):
        h = CtaHierarchy(
            primary=CtaRule(variant="primary", max_per_page=1, min_per_page=1),
            secondary=CtaRule(variant="secondary", max_per_page=3, min_per_page=0),
            tertiary=CtaRule(variant="ghost", max_per_page=None, min_per_page=0),
        )
        b = _base_brief(cta_hierarchy=h)
        assert b.cta_hierarchy is not None
        assert b.cta_hierarchy.primary.variant == "primary"
        assert b.cta_hierarchy.secondary.max_per_page == 3
        assert b.cta_hierarchy.tertiary.max_per_page is None

    def test_cta_rule_min_ge_0(self):
        with pytest.raises(Exception):
            CtaRule(variant="ghost", max_per_page=None, min_per_page=-1)


class TestBriefToDesignSpec:
    def test_absent_field_omitted_from_spec(self):
        spec = brief_to_design_spec(_base_brief())
        # When brief has no cta_hierarchy, the key isn't emitted; readers
        # fall back to defaults_for_register.
        assert "cta_hierarchy" not in spec

    def test_present_field_flows_verbatim(self):
        h = CtaHierarchy(
            primary=CtaRule(variant="primary", max_per_page=1, min_per_page=1),
            secondary=CtaRule(variant="outline", max_per_page=2, min_per_page=0),
            tertiary=CtaRule(variant="link", max_per_page=None, min_per_page=0),
        )
        spec = brief_to_design_spec(_base_brief(cta_hierarchy=h))
        assert spec["cta_hierarchy"]["primary"]["variant"] == "primary"
        assert spec["cta_hierarchy"]["secondary"]["variant"] == "outline"
        assert spec["cta_hierarchy"]["secondary"]["max_per_page"] == 2
        assert spec["cta_hierarchy"]["tertiary"]["variant"] == "link"

    def test_precedence_matches_schema_prompt_pattern(self):
        """schema_prompt reads `design_spec.get("cta_hierarchy") or defaults_for_register(register)`.
        With brief-authored hierarchy, that expression returns the brief;
        without it, returns defaults."""
        # Without brief field → get() returns None → falls through.
        spec_a = brief_to_design_spec(_base_brief())
        result_a = spec_a.get("cta_hierarchy") or defaults_for_register("default")
        assert result_a == defaults_for_register("default")

        # With brief field → get() returns brief-authored → falls through NOT triggered.
        h = CtaHierarchy(
            primary=CtaRule(variant="hero", max_per_page=1, min_per_page=1),
            secondary=CtaRule(variant="ghost", max_per_page=5, min_per_page=0),
            tertiary=CtaRule(variant="ghost", max_per_page=None, min_per_page=0),
        )
        spec_b = brief_to_design_spec(_base_brief(cta_hierarchy=h))
        result_b = spec_b.get("cta_hierarchy") or defaults_for_register("default")
        assert result_b["primary"]["variant"] == "hero"  # brief wins
        assert result_b != defaults_for_register("default")


class TestBackwardCompatCtaDefaults:
    def test_defaults_for_register_still_works(self):
        """The pre-existing register lookup keeps functioning for callers
        that haven't opted into brief-authoring."""
        assert defaults_for_register("linear")["secondary"]["max_per_page"] == 2
        assert defaults_for_register("default") == defaults_for_register("stripe")
        # Unknown register → base fallback.
        assert "primary" in defaults_for_register("pottery-marketplace")

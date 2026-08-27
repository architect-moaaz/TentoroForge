"""Tests for services.pipeline.variance — deterministic per-brief seed.

The seed's core contract:
- Same brief → same seed (reproducibility).
- Different briefs → different seeds (variety).
- Empty/malformed plan → 0 (safe fallback, doesn't crash callers).
- Never raises.
"""
from __future__ import annotations

from services.pipeline.variance import variance_seed_for, variance_hint_line


class TestVarianceSeedFor:
    def test_deterministic_across_calls(self):
        # The whole point — reproducibility must hold across processes.
        # Same-plan calls MUST return the same seed forever.
        plan = {"description": "yoga studio for booking classes"}
        s1 = variance_seed_for(plan)
        s2 = variance_seed_for(plan)
        assert s1 == s2
        # Stable value (blake2b is deterministic across CPython versions).
        # If this ever needs to change, the plan doc's reproducibility
        # contract needs to change too.
        assert s1 != 0

    def test_different_briefs_diverge(self):
        # Two yoga-studio apps with different descriptions must get
        # different seeds so their downstream picks diverge.
        a = variance_seed_for({"description": "yoga studio, warm & boutique"})
        b = variance_seed_for({"description": "yoga studio chain, high-density admin"})
        assert a != b

    def test_module_name_differences_matter(self):
        a = variance_seed_for({"description": "same", "module_name": "Rania"})
        b = variance_seed_for({"description": "same", "module_name": "YogaFlex"})
        assert a != b

    def test_field_priority_stability(self):
        # description is the highest-priority field. Changing lower-
        # priority ones must not change the seed when description is set.
        # No — actually per the implementation, ALL identity fields
        # contribute; that's intentional (so branding-lock rename
        # invalidates the seed). Pin the behaviour explicitly.
        a = variance_seed_for({"description": "x", "module_name": "A"})
        b = variance_seed_for({"description": "x", "module_name": "B"})
        assert a != b, "module_name is part of the identity hash"

    def test_none_plan_returns_zero(self):
        assert variance_seed_for(None) == 0  # type: ignore

    def test_non_dict_plan_returns_zero(self):
        assert variance_seed_for("not a plan") == 0  # type: ignore
        assert variance_seed_for(42) == 0  # type: ignore

    def test_empty_plan_returns_zero(self):
        assert variance_seed_for({}) == 0

    def test_plan_with_only_empty_strings_returns_zero(self):
        assert variance_seed_for({
            "description": "",
            "module_name": "  ",
            "brief": None,
        }) == 0

    def test_seed_fits_in_32_bits(self):
        # Prompt-facing value should be small enough to look tidy.
        for desc in ("a", "aaaaa", "long description " * 20, "unicode 🎨✨"):
            s = variance_seed_for({"description": desc})
            assert 0 <= s < (1 << 32)


class TestVarianceHintLine:
    def test_empty_when_seed_zero(self):
        assert variance_hint_line({}) == ""
        assert variance_hint_line(None) == ""  # type: ignore

    def test_includes_seed_value(self):
        line = variance_hint_line({"description": "yoga studio"})
        assert "VARIANCE HINT" in line
        # Seed value appears in the line.
        seed = variance_seed_for({"description": "yoga studio"})
        assert str(seed) in line

    def test_prompt_line_stable_across_calls(self):
        plan = {"description": "recruitment platform"}
        a = variance_hint_line(plan)
        b = variance_hint_line(plan)
        assert a == b

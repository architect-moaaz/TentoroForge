"""The stance is chosen, singular, and cheap enough to inject."""
from __future__ import annotations

import pytest

from services.taste_standards import STANCES, render_for, stance_for


class TestStanceIsChosenNotOffered:
    def test_explicit_brief_stance_wins(self):
        assert stance_for({"visual_stance": {"stance": "brutalist"}}) == "brutalist"
        assert stance_for({"stance": "soft"}) == "soft"

    def test_warm_register_reads_soft(self):
        assert stance_for({"identity": {"register": "warm, welcoming"}}) == "soft"
        assert stance_for({"visual_stance": {"temperature": "calm"}}) == "soft"

    def test_raw_register_reads_brutalist(self):
        assert stance_for({"identity": {"register": "raw technical"}}) == "brutalist"

    def test_unknown_falls_back_to_one_stance(self):
        for brief in (None, {}, {"identity": {}}, {"stance": "nonsense"}):
            assert stance_for(brief) in STANCES

    def test_only_one_stance_appears_in_the_prompt(self):
        block = render_for("design", {"stance": "soft"})
        named = [s for s in STANCES if f"Stance: {s}" in block]
        assert named == ["soft"]
        # the other two must not leak in as alternatives
        assert "minimalist" not in block and "brutalist" not in block


class TestRenderShape:
    @pytest.mark.parametrize("phase", ["design", "page_schema", "compose"])
    def test_known_phases_render(self, phase):
        assert render_for(phase, {}).startswith("## Design stance")

    def test_unknown_phase_is_empty_not_a_crash(self):
        assert render_for("nope", {}) == ""          # type: ignore[arg-type]

    def test_inference_questions_only_on_the_design_phase(self):
        assert "Who uses this" in render_for("design", {})
        assert "Who uses this" not in render_for("page_schema", {})

    def test_invariants_reach_every_authoring_phase(self):
        for phase in ("design", "page_schema", "compose"):
            assert "Both themes are designed" in render_for(phase, {})


class TestBudget:
    """Every token here displaces component contracts and registry context."""

    @pytest.mark.parametrize("phase", ["design", "page_schema", "compose"])
    def test_block_stays_small(self, phase):
        # ~4 chars/token; the whole prompt budget is 25k tokens.
        approx_tokens = len(render_for(phase, {})) / 4
        assert approx_tokens < 350, f"{phase} block is {approx_tokens:.0f} tokens"

    def test_no_foreign_design_systems_are_named(self):
        # Naming systems this platform does not ship invites the model to
        # reference components that do not exist here.
        blob = " ".join(render_for(p, {}) for p in
                        ("design", "page_schema", "compose")).lower()
        for foreign in ("material", "carbon", "polaris", "fluent", "bootstrap",
                        "shadcn", "radix", "atlassian"):
            assert foreign not in blob

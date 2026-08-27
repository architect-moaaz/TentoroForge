"""Tests for Phase 2 pieces: brief_to_prompt flattener + critic."""
from __future__ import annotations

from schemas.design_brief import DesignBrief
from tests.services._brief_fixtures import healthcare_brief
from services.design_brief_to_prompt import brief_to_prompt
from services.design_brief_critic import critique


_HC = healthcare_brief()


class TestBriefToPrompt:
    def test_contains_all_hexes(self):
        block = brief_to_prompt(_HC)
        assert _HC.palette.brand in block
        assert _HC.palette.accent in block
        assert _HC.palette.foreground_primary in block

    def test_contains_signature_moves(self):
        block = brief_to_prompt(_HC)
        for m in _HC.signature_moves:
            assert m.kind in block

    def test_contains_antipatterns(self):
        block = brief_to_prompt(_HC)
        for ap in _HC.anti_patterns[:2]:
            assert ap in block

    def test_labels_contract(self):
        block = brief_to_prompt(_HC)
        assert "DESIGN BRIEF" in block
        assert "contract" in block.lower()

    def test_empty_antipatterns_renders_none(self):
        payload = _HC.model_dump()
        payload["anti_patterns"] = []
        b = DesignBrief.model_validate(payload)
        block = brief_to_prompt(b)
        assert "(none)" in block


class TestCritic:
    def test_pass_on_clean_output(self):
        rendered = "some tsx with #2F6D5A and warm_serif_h1 signature"
        r = critique(_HC, {"rendered_text": rendered})
        assert r.passed
        assert r.stats["signature_kinds_matched"] >= 1

    def test_antipattern_hit_blocks(self):
        # Healthcare antipattern includes 'medical_blue_default' — feed it.
        rendered = "here is some medical_blue_default styling"
        r = critique(_HC, {"rendered_text": rendered})
        assert not r.passed
        assert any(f.kind == "antipattern" for f in r.findings)

    def test_antipattern_hit_with_spaces(self):
        rendered = "we're using medical blue default here"
        r = critique(_HC, {"rendered_text": rendered})
        # substring-with-spaces match — should fire.
        assert not r.passed

    def test_no_signature_move_warns_not_blocks(self):
        rendered = "no signature moves and no antipatterns #2F6D5A"
        r = critique(_HC, {"rendered_text": rendered})
        assert r.passed  # warning only
        assert any(f.kind == "no_signature_move" for f in r.findings)

    def test_brand_leak_over_threshold_warns(self):
        # Six random non-brief hexes → warn.
        rendered = " ".join([
            "#123456", "#654321", "#ABCDEF", "#111111", "#222222",
            "#333333", "#444444",
            _HC.palette.brand,  # one brief hex to keep it real
            "warm_serif_h1",     # so signature move matches
        ])
        r = critique(_HC, {"rendered_text": rendered})
        assert r.passed  # warnings don't block
        assert any(f.kind == "brand_leak" for f in r.findings)

    def test_stats_populated(self):
        r = critique(_HC, {"rendered_text": _HC.palette.brand + " warm_serif_h1"})
        assert "antipattern_hits" in r.stats
        assert "signature_kinds_matched" in r.stats
        assert "total_hexes_in_output" in r.stats

    def test_empty_output_still_returns_report(self):
        r = critique(_HC, {"rendered_text": ""})
        assert isinstance(r.passed, bool)

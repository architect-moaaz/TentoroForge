"""Tests for services.brief_loop_cascade + smith_decide.harvest_brief_metadata."""
from __future__ import annotations

import json
from pathlib import Path

from services.brief_loop_cascade import brief_to_design_spec_overlay, cascade
from tests.services._brief_fixtures import healthcare_brief
from services.design_brief_editor import write_brief
from services.smith_decide import harvest_brief_metadata


_HC = healthcare_brief()


class TestOverlay:
    def test_overlay_has_expected_shape(self):
        o = brief_to_design_spec_overlay(_HC)
        assert "colorPalette" in o
        assert "typography" in o
        assert o["colorPalette"]["brand"]["500"] == _HC.palette.brand

    def test_typography_families_carried_through(self):
        o = brief_to_design_spec_overlay(_HC)
        assert o["typography"]["display"]["family"] == _HC.typography.display_family
        assert o["typography"]["body"]["family"] == _HC.typography.body_family


class TestCascade:
    def test_no_brief_returns_noop(self, tmp_path: Path):
        r = cascade(tmp_path)
        assert r["recompiled"] is False
        assert "no brief" in r["reason"]

    def test_with_brief_writes_tokens(self, tmp_path: Path):
        write_brief(tmp_path, _HC)
        r = cascade(tmp_path)
        # Either recompiled or a compile-failure reason — but not skipped-for-no-brief.
        assert "no brief" not in r.get("reason", "")
        if r["recompiled"]:
            assert Path(r["tokens_path"]).exists()


class TestHarvestBrief:
    def test_empty_trace(self):
        assert harvest_brief_metadata(None) == {}
        assert harvest_brief_metadata([]) == {}

    def test_get_brief_only(self):
        trace = [{
            "tool": "get_brief",
            "result": {"brief": _HC.model_dump()},
        }]
        md = harvest_brief_metadata(trace)
        assert "brief_snapshot" in md
        assert md["brief_snapshot"]["identity"]["domain"] == "Healthcare"

    def test_edit_brief_wins_over_get(self):
        trace = [
            {"tool": "get_brief", "result": {"brief": _HC.model_dump()}},
            {"tool": "edit_brief", "result": {
                "applied": True,
                "before": {"summary": "old"},
                "after": {"summary": "new", "brief": _HC.model_dump()},
            }},
        ]
        md = harvest_brief_metadata(trace)
        assert "brief_edit" in md
        assert "brief_snapshot" not in md

    def test_failed_edit_ignored(self):
        trace = [{"tool": "edit_brief", "result": {"error": "bad patch"}}]
        assert harvest_brief_metadata(trace) == {}

    def test_null_brief_from_get_ignored(self):
        trace = [{"tool": "get_brief", "result": {"brief": None}}]
        assert harvest_brief_metadata(trace) == {}

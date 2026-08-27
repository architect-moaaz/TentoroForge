"""Tests for services.design_brief_editor — Smith edit_brief helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.design_brief_antipatterns import BASE_ANTI_PATTERNS
from services.design_brief_editor import (
    BriefEditError,
    apply_patch,
    edit_brief_on_disk,
    read_brief,
    write_brief,
)
from tests.services._brief_fixtures import healthcare_brief


_HC = healthcare_brief()


class TestApplyPatch:
    def test_empty_patch_raises(self):
        with pytest.raises(BriefEditError):
            apply_patch(_HC, {})

    def test_top_level_scalar(self):
        after = apply_patch(_HC, {"layout": {"density": "compact"}})
        assert after.layout.density.value == "compact"
        # Untouched fields preserved.
        assert after.palette.brand == _HC.palette.brand

    def test_nested_palette_change(self):
        after = apply_patch(_HC, {"palette": {"brand": "#112233"}})
        assert after.palette.brand == "#112233"
        assert after.palette.accent == _HC.palette.accent

    def test_signature_moves_replaced_wholesale(self):
        after = apply_patch(_HC, {
            "signature_moves": [{"kind": "new_thing", "detail": "x"}],
        })
        assert len(after.signature_moves) == 1
        assert after.signature_moves[0].kind == "new_thing"

    def test_base_antipatterns_always_survive(self):
        # User tries to strip antipatterns → base list is restored.
        after = apply_patch(_HC, {"anti_patterns": []})
        for base in BASE_ANTI_PATTERNS:
            assert base in after.anti_patterns

    def test_invalid_hex_raises(self):
        with pytest.raises(BriefEditError):
            apply_patch(_HC, {"palette": {"brand": "not-a-hex"}})

    def test_invalid_enum_raises(self):
        with pytest.raises(BriefEditError):
            apply_patch(_HC, {"layout": {"density": "very-cozy"}})


class TestDiskRoundtrip:
    def test_write_then_read(self, tmp_path: Path):
        write_brief(tmp_path, _HC)
        loaded = read_brief(tmp_path)
        assert loaded is not None
        assert loaded.palette.brand == _HC.palette.brand

    def test_read_missing_returns_none(self, tmp_path: Path):
        assert read_brief(tmp_path) is None

    def test_write_atomic_no_tmp_leftover(self, tmp_path: Path):
        write_brief(tmp_path, _HC)
        assert (tmp_path / "contracts" / "brief.json").exists()
        assert not (tmp_path / "contracts" / "brief.json.tmp").exists()

    def test_edit_on_disk(self, tmp_path: Path):
        write_brief(tmp_path, _HC)
        before, after = edit_brief_on_disk(tmp_path, {
            "layout": {"density": "compact"},
        })
        assert before.layout.density.value != "compact"
        assert after.layout.density.value == "compact"
        # Round-trip: what's on disk matches after.
        assert read_brief(tmp_path).layout.density.value == "compact"

    def test_edit_missing_disk_raises(self, tmp_path: Path):
        with pytest.raises(BriefEditError):
            edit_brief_on_disk(tmp_path, {"layout": {"density": "compact"}})

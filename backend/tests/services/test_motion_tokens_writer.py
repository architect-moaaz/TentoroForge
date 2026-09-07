"""Tests for services.motion_tokens_writer — Spec C4 wiring."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.motion_tokens_writer import is_enabled, write_motion_tokens


def _seed(root: Path, spec: dict, css: str = ":root { --primary: #123; }\n") -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "app").mkdir(parents=True)
    (root / "src" / "contracts" / "design-spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (root / "src" / "app" / "globals.css").write_text(css, encoding="utf-8")


def _spec_with_motion(**overrides) -> dict:
    motion = {
        "durationFastMs": 120, "durationMediumMs": 240, "durationSlowMs": 480,
        "easeOut": "cubic-bezier(0.2, 0.0, 0.0, 1.0)",
        "easeInOut": "cubic-bezier(0.4, 0.0, 0.2, 1.0)",
        "reduceMotionRespect": True,
    }
    motion.update(overrides)
    return {"colorPalette": {"primary": "#123"}, "motion": motion,
            "responsive": {"primaryFormFactor": "desktop"}}


# ────────────────────────────────────────────────────────────
class TestFlag:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("FORGE_POLISH_MOTION", raising=False)
        assert is_enabled() is False

    def test_on_when_truthy(self, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_MOTION", "1")
        assert is_enabled() is True


# ────────────────────────────────────────────────────────────
class TestWrite:
    def test_appends_motion_block_on_first_run(self, tmp_path):
        _seed(tmp_path, _spec_with_motion())
        res = write_motion_tokens(str(tmp_path))
        assert res == {"written": True, "spec_had_motion": True}
        css = (tmp_path / "src/app/globals.css").read_text(encoding="utf-8")
        assert "--motion-fast-ms: 120ms" in css
        assert "--motion-medium-ms: 240ms" in css
        assert "--motion-slow-ms: 480ms" in css
        assert "--ease-out: cubic-bezier" in css
        assert "--primary-form-factor: \"desktop\"" in css
        assert "motion-tint" in css
        assert "motion-lift" in css

    def test_reduce_motion_media_query_present(self, tmp_path):
        _seed(tmp_path, _spec_with_motion(reduceMotionRespect=True))
        write_motion_tokens(str(tmp_path))
        css = (tmp_path / "src/app/globals.css").read_text(encoding="utf-8")
        assert "@media (prefers-reduced-motion: reduce)" in css
        assert "animation-duration: 0.01ms !important" in css

    def test_reduce_motion_media_query_absent_when_disabled(self, tmp_path):
        _seed(tmp_path, _spec_with_motion(reduceMotionRespect=False))
        write_motion_tokens(str(tmp_path))
        css = (tmp_path / "src/app/globals.css").read_text(encoding="utf-8")
        assert "@media (prefers-reduced-motion: reduce)" not in css

    def test_custom_motion_values_flow_through(self, tmp_path):
        _seed(tmp_path, _spec_with_motion(
            durationFastMs=180, durationMediumMs=320, durationSlowMs=600,
            easeOut="cubic-bezier(0.1, 0.9, 0.2, 1.0)",
        ))
        write_motion_tokens(str(tmp_path))
        css = (tmp_path / "src/app/globals.css").read_text(encoding="utf-8")
        assert "--motion-fast-ms: 180ms" in css
        assert "--motion-slow-ms: 600ms" in css
        assert "cubic-bezier(0.1, 0.9, 0.2, 1.0)" in css

    def test_idempotent_replaces_block_not_appends(self, tmp_path):
        _seed(tmp_path, _spec_with_motion())
        write_motion_tokens(str(tmp_path))
        first = (tmp_path / "src/app/globals.css").read_text(encoding="utf-8")
        # Second run with same spec → no diff.
        second_res = write_motion_tokens(str(tmp_path))
        second = (tmp_path / "src/app/globals.css").read_text(encoding="utf-8")
        assert second_res["written"] is False
        assert first == second
        # Second run with different spec → block replaced, not appended.
        _seed_only_spec = tmp_path / "src/contracts/design-spec.json"
        _seed_only_spec.write_text(json.dumps(
            _spec_with_motion(durationFastMs=500),
        ), encoding="utf-8")
        third_res = write_motion_tokens(str(tmp_path))
        third = (tmp_path / "src/app/globals.css").read_text(encoding="utf-8")
        assert third_res["written"] is True
        # Block appears once, with new value.
        assert third.count("Spec C4/C8 — motion + responsive tokens") == 1
        assert "--motion-fast-ms: 500ms" in third

    def test_no_op_when_no_motion_in_spec(self, tmp_path):
        _seed(tmp_path, {"colorPalette": {"primary": "#123"}})  # no motion
        res = write_motion_tokens(str(tmp_path))
        assert res == {"written": False, "spec_had_motion": False}

    def test_no_op_when_css_missing(self, tmp_path):
        (tmp_path / "src" / "contracts").mkdir(parents=True)
        (tmp_path / "src" / "contracts" / "design-spec.json").write_text(
            json.dumps(_spec_with_motion())
        )
        # globals.css intentionally absent.
        res = write_motion_tokens(str(tmp_path))
        assert res == {"written": False, "spec_had_motion": False}

    def test_preserves_existing_css(self, tmp_path):
        _seed(tmp_path, _spec_with_motion(),
              css="/* my rules */\n.foo { color: red; }\n")
        write_motion_tokens(str(tmp_path))
        css = (tmp_path / "src/app/globals.css").read_text(encoding="utf-8")
        assert ".foo { color: red; }" in css
        assert "/* my rules */" in css

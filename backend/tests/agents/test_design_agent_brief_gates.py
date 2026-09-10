"""Spec D Wave 1 (round 2) — design_agent CSS-injection sites now
consult the brief FIRST for tone_intensity + nav_language + a
foreground-hint override before falling back to the DNA-derived output.

These tests exercise the brief-first branches through the reader
helpers directly (the CSS-injection sites are inline in save_design_spec
and require the full pipeline to run — the readers are the authored
boundary that determines the branch)."""
from __future__ import annotations

from pathlib import Path

import pytest

from schemas.design_brief import DesignBrief
from services.brief_visual_stance import (
    get_foreground_hint,
    get_nav_language,
    get_tone_intensity,
    load_brief_from,
)
from tests.services._brief_fixtures import healthcare_brief


def _write(tmp_path: Path, payload_mutator) -> Path:
    payload = healthcare_brief().model_dump()
    payload_mutator(payload)
    brief = DesignBrief.model_validate(payload)
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "brief.json").write_text(brief.model_dump_json(), encoding="utf-8")
    return tmp_path


class TestPersonalityGate:
    """When brief.identity.tone_intensity == 0.0, design_agent suppresses
    the personality CSS block. The gate is a single check against
    get_tone_intensity() returning exactly 0.0 (None keeps default)."""

    def test_zero_tone_intensity_gates_personality(self, tmp_path: Path) -> None:
        _write(tmp_path, lambda p: p["identity"].update(tone_intensity=0.0))
        assert get_tone_intensity(load_brief_from(tmp_path)) == 0.0

    def test_nonzero_intensity_lets_personality_through(self, tmp_path: Path) -> None:
        _write(tmp_path, lambda p: p["identity"].update(tone_intensity=0.6))
        # design_agent only suppresses on exactly 0.0 — anything else
        # falls through to the archetype-driven emission.
        val = get_tone_intensity(load_brief_from(tmp_path))
        assert val == 0.6
        assert val != 0.0

    def test_absent_field_returns_none(self, tmp_path: Path) -> None:
        _write(tmp_path, lambda p: None)
        assert get_tone_intensity(load_brief_from(tmp_path)) is None


class TestNavGate:
    """When brief.layout.nav_language == 'invisible', design_agent skips
    the per-skin nav block. Other values fall through."""

    def test_invisible_gates_nav_block(self, tmp_path: Path) -> None:
        _write(tmp_path, lambda p: p["layout"].update(nav_language="invisible"))
        assert get_nav_language(load_brief_from(tmp_path)) == "invisible"

    def test_chrome_heavy_falls_through(self, tmp_path: Path) -> None:
        _write(tmp_path, lambda p: p["layout"].update(nav_language="chrome_heavy"))
        v = get_nav_language(load_brief_from(tmp_path))
        assert v == "chrome_heavy"
        assert v != "invisible"

    def test_absent_field_returns_none(self, tmp_path: Path) -> None:
        _write(tmp_path, lambda p: None)
        assert get_nav_language(load_brief_from(tmp_path)) is None


class TestForegroundHintGate:
    """When brief.palette.foreground_hint is set, the contrast guardrail
    uses it verbatim for --primary-foreground instead of computing."""

    def test_hex_hint_wins(self, tmp_path: Path) -> None:
        _write(tmp_path, lambda p: p["palette"].update(foreground_hint="#0F172A"))
        assert get_foreground_hint(load_brief_from(tmp_path)) == "#0F172A"

    def test_absent_hint_returns_none(self, tmp_path: Path) -> None:
        _write(tmp_path, lambda p: None)
        assert get_foreground_hint(load_brief_from(tmp_path)) is None

    def test_missing_brief_disk_returns_none(self, tmp_path: Path) -> None:
        # No brief.json on disk → legacy _fg_for path must run.
        assert load_brief_from(tmp_path) is None
        assert get_foreground_hint(None) is None

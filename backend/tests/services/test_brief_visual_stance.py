"""Tests for services.brief_visual_stance — the shared brief-reader that
design_agent / design_compiler / generate / ux_spec_generator /
phase_gates check BEFORE falling back to the legacy DNA / language /
domain-UX modules (Spec D W1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemas.design_brief import DesignBrief
from services.brief_visual_stance import (
    get_compliance_flags,
    get_foreground_hint,
    get_layout_numerics,
    get_nav_language,
    get_palette,
    get_product_names,
    get_taglines,
    get_tone_intensity,
    get_visual_stance,
    load_brief_from,
)
from tests.services._brief_fixtures import healthcare_brief


# ── load_brief_from ──────────────────────────────────────────────────────

class TestLoadBriefFrom:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert load_brief_from(tmp_path) is None

    def test_reads_a_written_brief(self, tmp_path: Path) -> None:
        brief = healthcare_brief()
        contracts = tmp_path / "contracts"
        contracts.mkdir()
        (contracts / "brief.json").write_text(brief.model_dump_json(), encoding="utf-8")
        loaded = load_brief_from(tmp_path)
        assert loaded is not None
        assert loaded.palette.brand == brief.palette.brand

    def test_malformed_json_returns_none(self, tmp_path: Path) -> None:
        contracts = tmp_path / "contracts"
        contracts.mkdir()
        (contracts / "brief.json").write_text("{ not valid json", encoding="utf-8")
        assert load_brief_from(tmp_path) is None

    def test_schema_mismatch_returns_none(self, tmp_path: Path) -> None:
        contracts = tmp_path / "contracts"
        contracts.mkdir()
        (contracts / "brief.json").write_text('{"foo": "bar"}', encoding="utf-8")
        assert load_brief_from(tmp_path) is None

    def test_accepts_string_output_dir(self, tmp_path: Path) -> None:
        # Public API accepts both str and Path.
        assert load_brief_from(str(tmp_path)) is None


# ── get_palette ──────────────────────────────────────────────────────────

class TestGetPalette:
    def test_returns_defaults_on_none_brief(self) -> None:
        p = get_palette(None)
        assert set(p.keys()) == {"brand", "accent", "ink", "canvas", "muted"}
        assert all(v.startswith("#") for v in p.values())

    def test_reads_all_five_fields_from_brief(self) -> None:
        brief = healthcare_brief()
        p = get_palette(brief)
        assert p["brand"] == "#2E5C7E"
        assert p["accent"] == "#0F8A6A"
        assert p["ink"] == "#1A2634"
        assert p["canvas"] == "#FAFCFD"
        assert p["muted"] == "#5A6B7A"

    def test_always_returns_all_keys(self) -> None:
        # Even when we hand-construct a partial-looking brief, we still
        # get all five keys — defaults fill in.
        brief = healthcare_brief()
        p = get_palette(brief)
        for key in ("brand", "accent", "ink", "canvas", "muted"):
            assert key in p


# ── get_visual_stance ────────────────────────────────────────────────────

class TestGetVisualStance:
    def test_returns_defaults_on_none_brief(self) -> None:
        s = get_visual_stance(None)
        assert s == {
            "hue_range": None,
            "temperature": None,
            "shape_vocab": None,
            "principles": [],
        }

    def test_returns_defaults_when_stance_absent(self) -> None:
        # healthcare_brief has no visual_stance.
        brief = healthcare_brief()
        s = get_visual_stance(brief)
        assert s["hue_range"] is None
        assert s["principles"] == []

    def test_reads_authored_stance(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["identity"]["visual_stance"] = {
            "hue_range": "cool blues",
            "temperature": "cool",
            "shape_vocab": "geometric",
            "principles": ["restraint", "precision"],
        }
        brief = DesignBrief.model_validate(payload)
        s = get_visual_stance(brief)
        assert s == {
            "hue_range": "cool blues",
            "temperature": "cool",
            "shape_vocab": "geometric",
            "principles": ["restraint", "precision"],
        }

    def test_principles_list_is_fresh_per_call(self) -> None:
        # Guard against callers mutating a shared default list.
        s1 = get_visual_stance(None)
        s1["principles"].append("mutated")
        s2 = get_visual_stance(None)
        assert s2["principles"] == []


# ── get_layout_numerics ──────────────────────────────────────────────────

class TestGetLayoutNumerics:
    def test_defaults_on_none_brief(self) -> None:
        n = get_layout_numerics(None)
        assert set(n.keys()) == {
            "radius_px", "gutter_px", "density_pt",
            "shadow_scale", "header_align", "card_border",
        }

    def test_enum_snaps_when_numeric_absent(self) -> None:
        brief = healthcare_brief()  # density=comfortable, radius=soft_8
        n = get_layout_numerics(brief)
        assert n["radius_px"] == 8       # soft_8 → 8
        assert n["density_pt"] == 12     # comfortable → 12
        assert n["gutter_px"] == 16      # comfortable → 16 gutter

    def test_numeric_wins_over_enum(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["layout"]["radius_px"] = 20
        payload["layout"]["density_pt"] = 18
        brief = DesignBrief.model_validate(payload)
        n = get_layout_numerics(brief)
        assert n["radius_px"] == 20
        assert n["density_pt"] == 18

    def test_pill_enum_snaps_to_envelope_max(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["layout"]["radius"] = "pill"
        payload["layout"]["radius_px"] = None
        brief = DesignBrief.model_validate(payload)
        n = get_layout_numerics(brief)
        assert n["radius_px"] == 32

    def test_defaults_present_for_fields_brief_does_not_carry(self) -> None:
        brief = healthcare_brief()
        n = get_layout_numerics(brief)
        # These have sensible defaults regardless of brief contents.
        assert n["shadow_scale"] in {0, 1, 2, 3, 4, 5}
        assert n["header_align"] in {"left", "center", "right", "split"}
        assert n["card_border"] in {"none", "hairline", "standard", "heavy"}


# ── get_taglines ─────────────────────────────────────────────────────────

class TestGetTaglines:
    def test_empty_on_none_brief(self) -> None:
        assert get_taglines(None) == []

    def test_empty_when_field_absent(self) -> None:
        brief = healthcare_brief()  # no auth_taglines
        assert get_taglines(brief) == []

    def test_reads_authored_taglines(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["identity"]["auth_taglines"] = ["Welcome back", "Sign in to continue"]
        brief = DesignBrief.model_validate(payload)
        assert get_taglines(brief) == ["Welcome back", "Sign in to continue"]

    def test_strips_and_drops_empty(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["identity"]["auth_taglines"] = ["  hello  ", ""]
        brief = DesignBrief.model_validate(payload)
        # empty strings are dropped; whitespace is stripped
        result = get_taglines(brief)
        assert result == ["hello"]


# ── get_product_names ────────────────────────────────────────────────────

class TestGetProductNames:
    def test_empty_on_none_brief(self) -> None:
        assert get_product_names(None) == []

    def test_empty_when_field_absent(self) -> None:
        brief = healthcare_brief()
        assert get_product_names(brief) == []

    def test_reads_authored_names(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["identity"]["product_name_candidates"] = ["CalmChart", "Pulseboard"]
        brief = DesignBrief.model_validate(payload)
        assert get_product_names(brief) == ["CalmChart", "Pulseboard"]


# ── get_tone_intensity ───────────────────────────────────────────────────

class TestGetToneIntensity:
    def test_none_on_none_brief(self) -> None:
        assert get_tone_intensity(None) is None

    def test_none_when_field_absent(self) -> None:
        brief = healthcare_brief()  # no tone_intensity
        assert get_tone_intensity(brief) is None

    def test_reads_authored_value(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["identity"]["tone_intensity"] = 0.75
        brief = DesignBrief.model_validate(payload)
        assert get_tone_intensity(brief) == 0.75

    def test_zero_is_a_real_authored_value(self) -> None:
        """0.0 means 'brief-authored quiet' — MUST NOT be conflated with
        None (silent). Callers gate personality suppression on 0.0."""
        payload = healthcare_brief().model_dump()
        payload["identity"]["tone_intensity"] = 0.0
        brief = DesignBrief.model_validate(payload)
        assert get_tone_intensity(brief) == 0.0

    def test_rejects_out_of_range(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["identity"]["tone_intensity"] = 1.5
        with pytest.raises(ValueError):
            DesignBrief.model_validate(payload)


# ── get_compliance_flags ─────────────────────────────────────────────────

class TestGetComplianceFlags:
    def test_empty_on_none_brief(self) -> None:
        assert get_compliance_flags(None) == []

    def test_empty_when_field_absent(self) -> None:
        brief = healthcare_brief()
        assert get_compliance_flags(brief) == []

    def test_reads_and_normalizes(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["identity"]["compliance_flags"] = ["HIPAA", " sox ", "hipaa", ""]
        brief = DesignBrief.model_validate(payload)
        # lowercased, whitespace-stripped, empties dropped, dedup'd
        assert get_compliance_flags(brief) == ["hipaa", "sox"]


# ── get_foreground_hint ──────────────────────────────────────────────────

class TestGetForegroundHint:
    def test_none_on_none_brief(self) -> None:
        assert get_foreground_hint(None) is None

    def test_none_when_field_absent(self) -> None:
        assert get_foreground_hint(healthcare_brief()) is None

    def test_reads_hex_verbatim_uppercase(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["palette"]["foreground_hint"] = "#ffffff"
        brief = DesignBrief.model_validate(payload)
        assert get_foreground_hint(brief) == "#FFFFFF"

    def test_rejects_non_hex(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["palette"]["foreground_hint"] = "white"
        with pytest.raises(ValueError):
            DesignBrief.model_validate(payload)


# ── get_nav_language ─────────────────────────────────────────────────────

class TestGetNavLanguage:
    def test_none_on_none_brief(self) -> None:
        assert get_nav_language(None) is None

    def test_none_when_field_absent(self) -> None:
        assert get_nav_language(healthcare_brief()) is None

    def test_reads_authored_enum(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["layout"]["nav_language"] = "invisible"
        brief = DesignBrief.model_validate(payload)
        assert get_nav_language(brief) == "invisible"

    def test_rejects_unknown_enum_value(self) -> None:
        payload = healthcare_brief().model_dump()
        payload["layout"]["nav_language"] = "bespoke_gold"
        with pytest.raises(ValueError):
            DesignBrief.model_validate(payload)


# ── Integration: brief-first-then-DNA-fallback pattern ───────────────────

class TestBriefFirstPattern:
    """The pattern every migrated caller uses: try brief; on None, fall
    back to the legacy DNA/language/ux_specs derivation. One test here
    exercises the full pattern with a real brief on disk."""

    def test_migrated_caller_prefers_brief_when_present(self, tmp_path: Path) -> None:
        # Simulate the disk shape: contracts/brief.json exists.
        brief = healthcare_brief()
        contracts = tmp_path / "contracts"
        contracts.mkdir()
        (contracts / "brief.json").write_text(brief.model_dump_json(), encoding="utf-8")

        # Caller runs the standard pattern.
        loaded = load_brief_from(tmp_path)
        assert loaded is not None
        palette = get_palette(loaded)
        assert palette["brand"] == brief.palette.brand

    def test_migrated_caller_falls_back_when_brief_missing(self, tmp_path: Path) -> None:
        # No brief.json on disk → caller MUST run its legacy derivation.
        loaded = load_brief_from(tmp_path)
        assert loaded is None
        # Helpers on None return safe defaults so the caller's fallback
        # branch is the only path that runs (no accidental partial data).
        assert get_palette(loaded)["brand"].startswith("#")
        assert get_taglines(loaded) == []
        assert get_product_names(loaded) == []

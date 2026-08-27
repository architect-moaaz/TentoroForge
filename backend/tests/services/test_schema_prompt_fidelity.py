"""Tests for the token-framed design brief injection into build_schema_prompt (SP1.5-F3).

Covers:
- format_design_brief_for_schema unit test: palette hex appears, no globals.css, no bg-[ class
- build_schema_prompt integration: hex appears in prompt, no globals.css, no bg-[ class

Both are gated by FIDELITY_MODE_ENABLED (same gate as the existing rationale injection),
so tests monkeypatch it to True.
"""
from __future__ import annotations
import pytest
from unittest.mock import patch

_PALETTE_HEX = "#AB12CD"

_FAKE_DESIGN_SPEC = {
    "designRationale": "Brand rationale text.",
    "colorPalette": {
        "primary": _PALETTE_HEX,
        "secondary": "#334455",
        "background": "#FAFAFA",
    },
    "typography": {
        "fontFamily": "Inter",
        "headingWeight": "700",
    },
    "layout": {
        "navigation": "sidebar",
        "density": "comfortable",
    },
}

_PLAN_BASE = {
    "description": "A test app.",
    "entity": {"name": "Widget", "fields": [{"name": "name", "type": "text"}]},
    "page_type": "list",
    "archetype": "card-grid",
}


# ---------------------------------------------------------------------------
# Unit test: format_design_brief_for_schema
# ---------------------------------------------------------------------------

class TestFormatDesignBriefForSchema:
    def test_contains_primary_hex(self):
        from services.schema_prompt import format_design_brief_for_schema
        result = format_design_brief_for_schema(_FAKE_DESIGN_SPEC)
        assert _PALETTE_HEX in result, (
            "The design brief must include the concrete primary hex so the LLM "
            "can compose with knowledge of the brand palette"
        )

    def test_no_globals_css(self):
        from services.schema_prompt import format_design_brief_for_schema
        result = format_design_brief_for_schema(_FAKE_DESIGN_SPEC)
        assert "globals.css" not in result, (
            "Schema-path brief must NOT emit a globals.css block — "
            "that is only for the Tailwind/code path"
        )

    def test_no_tailwind_class_instruction(self):
        from services.schema_prompt import format_design_brief_for_schema
        result = format_design_brief_for_schema(_FAKE_DESIGN_SPEC)
        assert "bg-[" not in result, (
            "Schema-path brief must NOT instruct Tailwind bg-[#hex] classes — "
            "schema mode uses design tokens, never inline hex"
        )

    def test_returns_string(self):
        from services.schema_prompt import format_design_brief_for_schema
        result = format_design_brief_for_schema(_FAKE_DESIGN_SPEC)
        assert isinstance(result, str)

    def test_empty_spec_returns_empty_or_stub(self):
        """An empty spec must not raise — returns empty string or safe stub."""
        from services.schema_prompt import format_design_brief_for_schema
        result = format_design_brief_for_schema({})
        assert isinstance(result, str)
        assert "globals.css" not in result
        assert "bg-[" not in result

    def test_missing_keys_are_skipped_gracefully(self):
        """Partial spec (only colorPalette) must not raise."""
        from services.schema_prompt import format_design_brief_for_schema
        result = format_design_brief_for_schema({"colorPalette": {"primary": _PALETTE_HEX}})
        assert _PALETTE_HEX in result


# ---------------------------------------------------------------------------
# Integration test: build_schema_prompt wires the brief in
# ---------------------------------------------------------------------------

class TestBuildSchemaPromptIncludesBrief:
    def test_prompt_contains_palette_hex_when_fidelity_on(self, monkeypatch):
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", True)
        # Inject design_spec directly to avoid filesystem
        monkeypatch.setattr(sp, "_load_design_spec", lambda _: _FAKE_DESIGN_SPEC)
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: None)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE, design_spec=_FAKE_DESIGN_SPEC)

        assert _PALETTE_HEX in prompt, (
            "With fidelity on and a design_spec carrying a colorPalette, "
            "the primary hex must appear in the schema prompt"
        )

    def test_prompt_has_no_globals_css_when_fidelity_on(self, monkeypatch):
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", True)
        monkeypatch.setattr(sp, "_load_design_spec", lambda _: _FAKE_DESIGN_SPEC)
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: None)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE, design_spec=_FAKE_DESIGN_SPEC)

        assert "globals.css" not in prompt, (
            "Schema prompt must NEVER include a globals.css block — "
            "that would contradict the token-only color rules"
        )

    def test_prompt_has_no_tailwind_class_instruction(self, monkeypatch):
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", True)
        monkeypatch.setattr(sp, "_load_design_spec", lambda _: _FAKE_DESIGN_SPEC)
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: None)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE, design_spec=_FAKE_DESIGN_SPEC)

        assert "bg-[" not in prompt, (
            "Schema prompt must not instruct Tailwind bg-[#hex] syntax — "
            "schema mode composes with design tokens, not inline hex classes"
        )

    def test_hex_absent_when_fidelity_off(self, monkeypatch):
        """When fidelity mode is off, the brief should not be injected."""
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", False)
        monkeypatch.setattr(sp, "_load_design_spec", lambda _: _FAKE_DESIGN_SPEC)
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: None)

        from services.schema_prompt import build_schema_prompt
        # Even passing design_spec directly, the brief should be suppressed
        # when fidelity is off (consistent with existing rationale behaviour)
        prompt = build_schema_prompt(_PLAN_BASE, design_spec=_FAKE_DESIGN_SPEC)

        assert _PALETTE_HEX not in prompt, (
            "With fidelity off, the palette hex must NOT appear in the prompt — "
            "brief injection is gated by FIDELITY_MODE_ENABLED"
        )

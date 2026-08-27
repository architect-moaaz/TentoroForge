"""Tests for the FIDELITY_MODE_ENABLED flag in build_schema_prompt (Task 36).

These tests exercise the feature-flag gate in services/schema_prompt.py.
The generate.py gate (design_compiler call sites) is exercised at runtime by
the visible "[Tokens] FIDELITY_MODE_ENABLED=false" log message; integration-
testing that async generator here is not feasible without a full harness, so
we cover it by inspection only.
"""
import json
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_PLAN_BASE = {
    "description": "A fintech expense-tracking app with a deep blue theme.",
    "entity": {"name": "Expense", "fields": [{"name": "amount", "type": "float"}]},
    "page_type": "list",
    "archetype": "card-grid",
}

_FAKE_DESIGN_SPEC = {
    "designRationale": "UNIQUE_DESIGN_RATIONALE_FINGERPRINT: trust-first fintech with cobalt palette.",
    "colorPalette": {"primary": "#1e3a8a"},
}

_FAKE_GOLD_EXAMPLE = {
    "schemaVersion": "2",
    "__GOLD_EXAMPLE_FINGERPRINT__": True,
    "id": "expense-list",
    "root": {"type": "Hero", "props": {}},
}


# ---------------------------------------------------------------------------
# Test 1: flag ON — design-spec section AND gold-example section present
# ---------------------------------------------------------------------------

class TestFidelityFlagOn:
    """With FIDELITY_MODE_ENABLED=True the prompt must include both enrichments."""

    def test_enriched_prompt_contains_design_spec_marker(self, monkeypatch):
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", True)
        # Patch internal helpers instead of touching the filesystem
        monkeypatch.setattr(sp, "_load_design_spec", lambda _output_dir: _FAKE_DESIGN_SPEC)
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: _FAKE_GOLD_EXAMPLE)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE)

        assert "UNIQUE_DESIGN_RATIONALE_FINGERPRINT" in prompt, (
            "With fidelity on, design-spec rationale must appear in prompt"
        )

    def test_enriched_prompt_contains_gold_example_marker(self, monkeypatch):
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", True)
        monkeypatch.setattr(sp, "_load_design_spec", lambda _output_dir: _FAKE_DESIGN_SPEC)
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: _FAKE_GOLD_EXAMPLE)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE)

        assert "__GOLD_EXAMPLE_FINGERPRINT__" in prompt, (
            "With fidelity on, gold-example JSON must appear in prompt"
        )


# ---------------------------------------------------------------------------
# Test 2: flag OFF — design-spec and gold-example must be absent
# ---------------------------------------------------------------------------

class TestFidelityFlagOff:
    """With FIDELITY_MODE_ENABLED=False the prompt must omit both enrichments."""

    def test_stripped_prompt_excludes_design_spec_marker(self, monkeypatch):
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", False)
        # Even if the helpers would return data, they should not be called
        monkeypatch.setattr(sp, "_load_design_spec", lambda _output_dir: _FAKE_DESIGN_SPEC)
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: _FAKE_GOLD_EXAMPLE)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE)

        assert "UNIQUE_DESIGN_RATIONALE_FINGERPRINT" not in prompt, (
            "With fidelity off, design-spec rationale must NOT appear in prompt"
        )

    def test_stripped_prompt_excludes_gold_example_marker(self, monkeypatch):
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", False)
        monkeypatch.setattr(sp, "_load_design_spec", lambda _output_dir: _FAKE_DESIGN_SPEC)
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: _FAKE_GOLD_EXAMPLE)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE)

        assert "__GOLD_EXAMPLE_FINGERPRINT__" not in prompt, (
            "With fidelity off, gold-example JSON must NOT appear in prompt"
        )

    # -----------------------------------------------------------------------
    # Test 3: flag OFF — token paths are still rendered
    # -----------------------------------------------------------------------

    def test_stripped_prompt_still_contains_token_paths(self, monkeypatch):
        """Token paths (defaultTokens) are part of the token contract and must
        always appear in the prompt regardless of fidelity mode."""
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", False)
        monkeypatch.setattr(sp, "_load_design_spec", lambda _output_dir: {})
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: None)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE)

        assert "tokens.color.primary.500" in prompt, (
            "Token paths must be present even when fidelity mode is off"
        )

    # -----------------------------------------------------------------------
    # Test 4: flag OFF — no exception when design-spec would be missing
    # -----------------------------------------------------------------------

    def test_no_exception_when_design_spec_absent_and_fidelity_off(self, monkeypatch):
        """When fidelity is off, _load_design_spec is never called, so a
        missing file cannot cause an error.  Verify no exception is raised and
        the prompt is still a usable non-empty string."""
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", False)
        # Simulate what happens without any patching — _output_dir is None,
        # so _load_design_spec would return {} (no-op). But with fidelity off,
        # it isn't called at all. We verify by NOT patching it and confirming
        # no exception surfaces.

        from services.schema_prompt import build_schema_prompt
        plan_no_output_dir = {
            "description": "expense tracker",
            "entity": {"name": "Expense", "fields": []},
            "page_type": "list",
            # deliberately no _output_dir
        }
        prompt = build_schema_prompt(plan_no_output_dir)

        assert isinstance(prompt, str)
        assert len(prompt) > 100, "Prompt must be a substantive string even with fidelity off"
        assert "tokens." in prompt, "Token contract must still appear"

    def test_gold_example_section_header_absent_when_fidelity_off(self, monkeypatch):
        """When fidelity is off, the 'Gold-standard example' section header must
        not appear in the prompt — the LLM must not see an instruction to follow
        a non-existent example."""
        import services.schema_prompt as sp

        monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", False)
        monkeypatch.setattr(sp, "_load_design_spec", lambda _output_dir: {})
        monkeypatch.setattr(sp, "load_gold_example", lambda _pt, _arch: None)

        from services.schema_prompt import build_schema_prompt
        prompt = build_schema_prompt(_PLAN_BASE)

        assert "Gold-standard example" not in prompt, (
            "With fidelity off, the gold-example section header must be absent "
            "from the prompt — emitting it with no example actively misleads the LLM"
        )

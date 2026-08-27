"""Tests for services.product_standards."""
from __future__ import annotations

import pytest

from services import product_standards as ps


def test_standards_has_expected_top_level_sections():
    got = ps.all_sections()
    assert set(got.keys()) == {"architecture", "frontend", "completeness", "content"}
    # And each section has bullets.
    for section, bullets in got.items():
        assert bullets, f"section {section!r} has no bullets"
        for b in bullets:
            assert isinstance(b, str) and b.strip(), f"empty bullet in {section!r}"


def test_render_for_design_includes_frontend_only():
    """Design agent decides visual style — it should see the frontend
    bullets and NOTHING else. Overloading its prompt with completeness
    or architecture rules would dilute the visual guidance."""
    out = ps.render_for("design")
    assert "## Product standards" in out
    assert "### Frontend" in out
    # Design agent should not see other phases' concerns.
    assert "### Completeness" not in out
    assert "### Architecture" not in out
    assert "### Content" not in out
    # Sanity: at least one frontend bullet lands.
    assert "Lucide icons" in out


def test_render_for_page_schema_includes_frontend_completeness_content():
    """Page-schema agent authors the LLM-driven content of each page —
    it needs frontend + completeness + content standards, since those
    are exactly what it decides on its own."""
    out = ps.render_for("page_schema")
    assert "### Frontend" in out
    assert "### Completeness" in out
    assert "### Content" in out
    # And still NOT architecture (that's enforced by the runtime + guards).
    assert "### Architecture" not in out
    # Sanity: at least one completeness bullet lands.
    assert "isLoading skeleton" in out


def test_render_for_unknown_phase_returns_empty_string():
    """Defensive: an unregistered phase gets nothing rather than a crash.
    Callers .strip()-check the return before appending."""
    # Use a type-cheat cast — we're testing the runtime fallback.
    assert ps.render_for("nonexistent") == ""  # type: ignore[arg-type]


def test_render_for_output_is_appendable_to_prompt():
    """The renderer's output must be safe to str-concat to a system or
    user prompt: no leading/trailing whitespace surprises that would
    fuse with adjacent context blocks."""
    out = ps.render_for("page_schema")
    # No trailing whitespace (the caller adds its own separator).
    assert out == out.rstrip(), "trailing whitespace would fuse with next block"
    # Starts with a heading — callers rely on this for section discovery.
    assert out.startswith("## Product standards")


def test_all_sections_returns_a_deep_copy():
    """Callers must not be able to mutate the canonical rubric by
    editing the returned dict/list."""
    snap = ps.all_sections()
    snap["frontend"].append("mutation")
    assert "mutation" not in ps.all_sections()["frontend"]

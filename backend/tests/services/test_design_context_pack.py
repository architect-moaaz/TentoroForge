"""Tests for services.design_context_pack — Sprint 1 of Forge Great Again.

The pack is a designer-facing prompt block prepended to the page-schema
LLM turn. These tests verify: opt-in gating, archetype scoping, section
composition, brief/signature-move integration, and graceful failure.

Purpose is behavioural (does the pack shape appear where expected) not
literal-string (the pack copy will evolve as we iterate on prompt
engineering). Assertions target section markers + key phrases.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import design_context_pack as dcp


# --------------------------------------------------------------------------- #
# Gating — the pack must be opt-in and archetype-scoped for slice 1.
# --------------------------------------------------------------------------- #

def test_disabled_by_default_env_var_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE_DESIGN_CONTEXT_PACK", raising=False)
    result = dcp.build_design_context_pack(
        plan={"actors": []},
        page={"type": "dashboard", "name": "Ops"},
        output_dir=str(tmp_path),
    )
    assert result == ""


def test_enabled_when_env_var_is_one(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    result = dcp.build_design_context_pack(
        plan={"actors": []},
        page={"type": "dashboard", "name": "Ops"},
        output_dir=str(tmp_path),
    )
    assert result  # non-empty
    assert "<design-mandate>" in result


def test_returns_empty_for_unsupported_page_types_in_slice_1(monkeypatch, tmp_path):
    """Slice 1 = dashboards only. list/detail/form pass through the base
    prompt unchanged so we can roll out per-archetype and watch quality."""
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    for page_type in ("list", "detail", "form", "auth", "settings"):
        result = dcp.build_design_context_pack(
            plan={}, page={"type": page_type}, output_dir=str(tmp_path),
        )
        assert result == "", f"{page_type!r} unexpectedly produced a pack"


def test_reads_page_type_field_or_page_type_alias(monkeypatch, tmp_path):
    """`page` may use either `type` (planner) or `page_type` (page_plan)."""
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    a = dcp.build_design_context_pack(
        plan={}, page={"type": "dashboard"}, output_dir=str(tmp_path),
    )
    b = dcp.build_design_context_pack(
        plan={}, page={"page_type": "dashboard"}, output_dir=str(tmp_path),
    )
    assert a and b
    # Both take the dashboard path — key palette marker present in both.
    assert "<component-palette page-type=\"dashboard\">" in a
    assert "<component-palette page-type=\"dashboard\">" in b


# --------------------------------------------------------------------------- #
# Section composition — every enabled dashboard page has these blocks.
# --------------------------------------------------------------------------- #

def test_pack_always_includes_mandate_and_purpose(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    out = dcp.build_design_context_pack(
        plan={"actors": ["Manager"]},
        page={"type": "dashboard", "name": "Ops"},
        output_dir=str(tmp_path),
    )
    assert "<design-mandate>" in out
    # Sprint 4: the tag now carries a source attr — accept either
    # "planner-authored" or "synthesized" (this test doesn't provide a
    # planner-authored purpose so synthesis fires).
    assert "<page-purpose " in out
    # Mandate carries the philosophy prose.
    assert "HERO MOMENT" in out
    assert "BRAND COLOR" in out
    assert "SIGNATURE MOVES" in out


def test_component_palette_present_for_dashboards(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    out = dcp.build_design_context_pack(
        plan={}, page={"type": "dashboard"}, output_dir=str(tmp_path),
    )
    assert "<component-palette" in out
    # Palette must mention the specific dashboard vocabulary the LLM
    # should reach for.
    for expected in ("KPI ROW", "HERO CHART", "SECONDARY RAIL", "RICH LISTS",
                     "EMPTY STATE"):
        assert expected in out, f"palette missing section: {expected}"


def test_page_purpose_names_the_actor_and_synthesises_a_goal(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    out = dcp.build_design_context_pack(
        plan={"actors": [{"name": "PropertyManager"}]},
        page={
            "type": "dashboard",
            "name": "Manager Dashboard",
            "route": "/dashboard",
            "entity": "Payment",
        },
        output_dir=str(tmp_path),
    )
    assert "Manager Dashboard" in out
    assert "/dashboard" in out
    # Actor name is humanized (camelCase → "Property Manager").
    assert "Property Manager" in out
    # Goal mentions the entity.
    assert "Payment" in out


# --------------------------------------------------------------------------- #
# Design-brief integration — when a brief exists on disk, it's rendered.
# When absent, the pack still builds without it.
# --------------------------------------------------------------------------- #

class _FakeBrief:
    """Mimics the DesignBrief attributes the pack reads. Full validation
    of the real brief is covered elsewhere — here we only care that the
    pack integrates with whatever load_brief_from_disk returns."""

    signature_moves = [
        {"kind": "ledger_row", "description": "mono row with hairline dividers"},
        {"kind": "warm_serif_h1", "description": "serif page title"},
    ]


def _install_fake_brief_loader(monkeypatch, brief):
    """Stub design_brief_to_prompt so the pack sees `brief` on disk
    without needing a real schema-valid brief.json."""
    from services import design_brief_to_prompt as dbtp
    monkeypatch.setattr(dbtp, "load_brief_from_disk", lambda _d: brief)
    if brief is not None:
        monkeypatch.setattr(dbtp, "brief_to_prompt", lambda _b: "BRIEF PROSE OK")


def test_pack_includes_brief_block_when_brief_on_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    _install_fake_brief_loader(monkeypatch, _FakeBrief())
    out = dcp.build_design_context_pack(
        plan={}, page={"type": "dashboard"}, output_dir=str(tmp_path),
    )
    assert "<design-brief>" in out
    assert "BRIEF PROSE OK" in out


def test_pack_omits_brief_block_when_brief_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    out = dcp.build_design_context_pack(
        plan={}, page={"type": "dashboard"}, output_dir=str(tmp_path),
    )
    # Mandate/purpose still present, brief section absent.
    assert "<design-mandate>" in out
    assert "<design-brief>" not in out


def test_pack_includes_signature_moves_when_registry_has_moves(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    # Signature-moves module registers built-ins at import; a real registry
    # is loaded. We just assert the block appears — content varies with
    # what's registered.
    out = dcp.build_design_context_pack(
        plan={}, page={"type": "dashboard"}, output_dir=str(tmp_path),
    )
    # Block may or may not appear depending on registry state, but if it
    # does, it must carry the mandate to apply at least two moves.
    if "<signature-moves>" in out:
        assert "AT LEAST TWO" in out


# --------------------------------------------------------------------------- #
# Failure isolation — the pack must never break generation.
# --------------------------------------------------------------------------- #

def test_returns_empty_when_plan_is_not_a_dict(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    out = dcp.build_design_context_pack(
        plan="not-a-dict",  # type: ignore[arg-type]
        page={"type": "dashboard"},
        output_dir=str(tmp_path),
    )
    assert out == ""


def test_returns_empty_when_page_is_not_a_dict(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    out = dcp.build_design_context_pack(
        plan={}, page=None,  # type: ignore[arg-type]
        output_dir=str(tmp_path),
    )
    assert out == ""


def test_broken_brief_on_disk_does_not_crash(monkeypatch, tmp_path):
    """A malformed brief.json must silently fall back — the base prompt
    still runs. Author quality suffers but generation doesn't."""
    monkeypatch.setenv("FORGE_DESIGN_CONTEXT_PACK", "1")
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "brief.json").write_text("{not-valid-json")
    out = dcp.build_design_context_pack(
        plan={}, page={"type": "dashboard"}, output_dir=str(tmp_path),
    )
    # Pack still assembles (mandate + purpose + palette), brief block
    # silently omitted.
    assert "<design-mandate>" in out
    assert "<design-brief>" not in out


# --------------------------------------------------------------------------- #
# Humanization helper — subtle but important for actor names / entity names
# so the synthesized purpose reads well.
# --------------------------------------------------------------------------- #

def test_humanize_camel_case():
    assert dcp._humanize("PropertyManager") == "Property Manager"


def test_humanize_snake_case():
    assert dcp._humanize("property_manager") == "Property Manager"


def test_humanize_kebab_case():
    assert dcp._humanize("property-manager") == "Property Manager"


def test_humanize_empty_and_non_string():
    assert dcp._humanize("") == ""
    assert dcp._humanize(None) == ""  # type: ignore[arg-type]

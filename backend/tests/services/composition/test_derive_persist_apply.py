"""Tests for the pipeline convenience helper — read brief.json, derive
recipes from plan, write back."""
from __future__ import annotations

import json
from pathlib import Path

from services.composition.apply_recipes import derive_persist_apply


def _write_brief_min(tmp_path: Path) -> Path:
    """Write a minimal valid DesignBrief to contracts/brief.json."""
    p = tmp_path / "contracts"
    p.mkdir(parents=True, exist_ok=True)
    brief = {
        "identity": {
            "domain": "Test", "register": ["structured"],
            "voice": "warm_precise",
        },
        "palette": {
            "brand": "#2D5A8E", "accent": "#E8A020",
            "neutrals_base": "#F5F5F5", "neutrals_tint": "cool",
            "surface_bg": "#FFFFFF", "surface_elevated": "#FFFFFF",
            "foreground_primary": "#111111", "foreground_muted": "#666666",
        },
        "typography": {"display_family": "Serif", "body_family": "Sans"},
        "layout": {"density": "compact", "radius": "soft_8", "grid": "12col"},
        "signature_moves": [{"kind": "warm_serif_h1", "detail": "x"}],
    }
    (p / "brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")
    return p / "brief.json"


def test_missing_brief_returns_empty(tmp_path):
    assert derive_persist_apply(tmp_path, {"pages": [{"route": "/home"}]}) == {}


def test_writes_derived_recipes_back(tmp_path):
    brief_path = _write_brief_min(tmp_path)
    plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}

    result = derive_persist_apply(tmp_path, plan)
    assert result == {"/home": "member_home"}

    # On-disk brief reflects the change.
    reread = json.loads(brief_path.read_text(encoding="utf-8"))
    assert reread["page_recipes"] == {"/home": "member_home"}


def test_no_op_when_nothing_derived_does_not_rewrite(tmp_path):
    brief_path = _write_brief_min(tmp_path)
    mtime_before = brief_path.stat().st_mtime_ns
    plan = {"pages": []}
    result = derive_persist_apply(tmp_path, plan)
    assert result == {}
    # File unchanged.
    assert brief_path.stat().st_mtime_ns == mtime_before


def test_second_run_is_idempotent(tmp_path):
    brief_path = _write_brief_min(tmp_path)
    plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}
    r1 = derive_persist_apply(tmp_path, plan)
    r2 = derive_persist_apply(tmp_path, plan)
    assert r1 == r2 == {"/home": "member_home"}


def test_existing_page_recipes_win_by_default(tmp_path):
    brief_path = _write_brief_min(tmp_path)
    # Seed a manual override.
    initial = json.loads(brief_path.read_text(encoding="utf-8"))
    initial["page_recipes"] = {"/home": "creator_workspace"}
    brief_path.write_text(json.dumps(initial), encoding="utf-8")

    plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}
    result = derive_persist_apply(tmp_path, plan)
    # Override kept — derived is a fallback, not an authority.
    assert result == {"/home": "creator_workspace"}


def test_overwrite_flag_replaces_wholesale(tmp_path):
    brief_path = _write_brief_min(tmp_path)
    initial = json.loads(brief_path.read_text(encoding="utf-8"))
    initial["page_recipes"] = {"/home": "creator_workspace"}
    brief_path.write_text(json.dumps(initial), encoding="utf-8")

    plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}
    result = derive_persist_apply(tmp_path, plan, overwrite=True)
    assert result == {"/home": "member_home"}


def test_broken_brief_returns_empty_without_raising(tmp_path):
    (tmp_path / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "contracts" / "brief.json").write_text("{not-json", encoding="utf-8")
    plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}
    assert derive_persist_apply(tmp_path, plan) == {}

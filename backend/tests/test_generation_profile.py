"""Generation profile — Fast vs Complete mode bundle.

The profile bundles several levers (narrative expansion, decomposition,
post-generate depth) behind one named choice the user picks on the
DiscoveryCard. Profile choice is persisted per-project so downstream
phases (planning / generation / post-gen) all read the same decision.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.generation_profile import (
    PROFILE_IDS,
    Profile,
    get_profile,
    load_profile,
    persist_profile,
)


# --------------------------------------------------------------------------- #
# Registry + lookup
# --------------------------------------------------------------------------- #

def test_profile_registry_exposes_fast_and_complete():
    assert "fast" in PROFILE_IDS
    assert "complete" in PROFILE_IDS


def test_get_profile_fast_disables_narrative_expansion():
    p = get_profile("fast")
    assert p.narrative_expansion is False
    assert p.id == "fast"
    assert p.eta_minutes <= 20  # marketing claim: ~15 min


def test_get_profile_complete_enables_narrative_expansion():
    p = get_profile("complete")
    assert p.narrative_expansion is True
    assert p.id == "complete"
    assert p.eta_minutes >= 30  # marketing claim: ~40 min


def test_get_profile_unknown_id_falls_back_to_default():
    """Any unknown/None id → the default (Fast). Never raises so a
    malformed frontend payload can't blow up generation."""
    for bad in (None, "", "nonsense", "FAST", 123):
        p = get_profile(bad)  # type: ignore[arg-type]
        assert p.id == "fast", f"expected fast fallback for {bad!r}"


def test_profile_carries_user_facing_metadata():
    """Frontend renders these fields on the chips — label + description
    must be non-empty so the UI shows something meaningful."""
    for pid in PROFILE_IDS:
        p = get_profile(pid)
        assert p.label, f"{pid}: empty label"
        assert p.description, f"{pid}: empty description"
        assert p.eta_minutes > 0, f"{pid}: no ETA"


# --------------------------------------------------------------------------- #
# Persistence — profile choice survives across phases
# --------------------------------------------------------------------------- #

def test_persist_and_load_round_trips(tmp_path):
    """persist_profile writes a JSON file the downstream phases can
    load_profile back from — no reliance on env vars or session state."""
    persist_profile(str(tmp_path), get_profile("fast"))
    loaded = load_profile(str(tmp_path))
    assert loaded is not None
    assert loaded.id == "fast"
    assert loaded.narrative_expansion is False


def test_load_profile_returns_none_when_missing(tmp_path):
    """No file yet → None. Callers use env / default when this happens."""
    assert load_profile(str(tmp_path)) is None


def test_persist_writes_to_contracts_dir(tmp_path):
    """Contract shape: file lives at ``<out>/contracts/generation-profile.json``
    so it sits alongside the other planner-era contracts."""
    persist_profile(str(tmp_path), get_profile("complete"))
    p = Path(tmp_path) / "contracts" / "generation-profile.json"
    assert p.exists()
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["id"] == "complete"


def test_persist_overwrites_existing_choice(tmp_path):
    """User picks Fast, then re-runs with Complete → new choice wins."""
    persist_profile(str(tmp_path), get_profile("fast"))
    persist_profile(str(tmp_path), get_profile("complete"))
    assert load_profile(str(tmp_path)).id == "complete"


def test_load_profile_silently_ignores_malformed_file(tmp_path):
    """A truncated / corrupt profile file → None, never raises. Callers
    fall through to the default."""
    p = Path(tmp_path) / "contracts" / "generation-profile.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not valid json", encoding="utf-8")
    assert load_profile(str(tmp_path)) is None

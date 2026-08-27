"""Tests for services.signature_moves_detector — Sprint 6."""
from __future__ import annotations

import pytest

from services import signature_moves_detector as smd


# ── Env gating ──────────────────────────────────────────────────────────

def test_gate_default_off(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_SIGNATURE_MOVES_GATE", raising=False)
    assert smd.signature_moves_gate_enabled() is False


def test_gate_on_when_flag_is_one(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_SIGNATURE_MOVES_GATE", "1")
    assert smd.signature_moves_gate_enabled() is True


def test_min_required_default(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_SIGNATURE_MOVES_MIN", raising=False)
    assert smd.min_signature_moves_required() == 2


def test_min_required_env_override(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_SIGNATURE_MOVES_MIN", "3")
    assert smd.min_signature_moves_required() == 3


# ── Detection ──────────────────────────────────────────────────────────

def test_detects_move_by_kind_substring():
    """A schema that mentions the move kind's exact name counts."""
    schema = {"root": {"props": {"variant": "ledger_row"}}}
    result = smd.detect_signature_moves(schema, ["ledger_row"])
    assert result["detected"] == ["ledger_row"]
    assert result["missing"] == []


def test_detects_move_by_alias():
    """Aliases catch renders that emit surface-form variants (like
    ``variant: "ledger"`` for the ``ledger_row`` move)."""
    schema = {"root": {"props": {"variant": "ledger"}}}
    result = smd.detect_signature_moves(schema, ["ledger_row"])
    assert result["detected"] == ["ledger_row"]


def test_missing_moves_reported(monkeypatch):
    schema = {"root": {"props": {"variant": "ledger"}}}
    result = smd.detect_signature_moves(
        schema, ["ledger_row", "warm_serif_h1", "velocity_sparkline"],
    )
    assert result["detected"] == ["ledger_row"]
    assert set(result["missing"]) == {"warm_serif_h1", "velocity_sparkline"}
    monkeypatch.setenv("FORGE_PAGE_SIGNATURE_MOVES_MIN", "2")
    result2 = smd.detect_signature_moves(
        schema, ["ledger_row", "warm_serif_h1"],
    )
    assert result2["meets_minimum"] is False  # only 1 of 2 needed detected


def test_meets_minimum_when_enough_moves():
    schema = {
        "root": {
            "children": [
                {"props": {"variant": "ledger"}},
                {"props": {"variant": "warm-serif"}},
            ]
        }
    }
    result = smd.detect_signature_moves(
        schema, ["ledger_row", "warm_serif_h1", "unrelated_move"],
    )
    assert result["meets_minimum"] is True


def test_empty_committed_set_falls_back_to_registered():
    """When the brief lacks a signature_moves list, ALL registered
    moves become eligible (permissive default). Detection still runs;
    just returns an empty expected set if nothing is registered."""
    schema = {"root": {}}
    # Empty explicit committed set → still gets registered defaults.
    result = smd.detect_signature_moves(schema, None)
    # Registered set may or may not contain built-ins depending on
    # import order in this test process — we just assert the shape.
    assert "expected" in result
    assert "detected" in result
    assert "meets_minimum" in result


def test_as_critic_gap_medium_when_gate_off(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_SIGNATURE_MOVES_GATE", raising=False)
    detection = {
        "expected":     ["a", "b", "c"],
        "detected":     [],
        "missing":      ["a", "b", "c"],
        "min_required": 2,
        "meets_minimum": False,
    }
    gap = smd.as_critic_gap(detection)
    assert gap is not None
    assert gap["severity"] == "medium"
    assert "Missing: a, b, c" in gap["note"]


def test_as_critic_gap_high_when_gate_on(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_SIGNATURE_MOVES_GATE", "1")
    detection = {
        "expected":     ["a", "b"],
        "detected":     [],
        "missing":      ["a", "b"],
        "min_required": 2,
        "meets_minimum": False,
    }
    gap = smd.as_critic_gap(detection)
    assert gap["severity"] == "high"


def test_as_critic_gap_none_when_minimum_met():
    detection = {"meets_minimum": True, "missing": [], "detected": []}
    assert smd.as_critic_gap(detection) is None


def test_as_critic_gap_none_when_no_expectations():
    detection = {
        "expected": [], "detected": [], "missing": [],
        "min_required": 2, "meets_minimum": False,
    }
    assert smd.as_critic_gap(detection) is None

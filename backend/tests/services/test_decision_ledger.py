"""Tests for services.decision_ledger.

Covers bands, decision_id stability, ledger idempotency, bindings
lookup, resolved-flag flipping. No LLM/IO mocking needed — the
ledger is pure disk I/O against tmp paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.decision_ledger import (
    BAND_HIGH, BAND_LOW, BAND_MEDIUM,
    KIND_ARCHETYPE, KIND_BUTTON_TARGET, KIND_FORM_SUBMIT,
    Alternative, Decision,
    band_for_score,
    load_bindings, load_ledger, make_alternative, make_decision,
    make_decision_id, pending_decisions,
    record, record_pick,
    resolve_binding, save_binding,
)


# ── bands ────────────────────────────────────────────────────────────

def test_band_high_boundary():
    """0.9 is HIGH (inclusive lower bound)."""
    assert band_for_score(1.0) == BAND_HIGH
    assert band_for_score(0.95) == BAND_HIGH
    assert band_for_score(0.9) == BAND_HIGH


def test_band_medium_range():
    assert band_for_score(0.89) == BAND_MEDIUM
    assert band_for_score(0.75) == BAND_MEDIUM
    assert band_for_score(0.6) == BAND_MEDIUM


def test_band_low_range():
    assert band_for_score(0.59) == BAND_LOW
    assert band_for_score(0.3) == BAND_LOW
    assert band_for_score(0.0) == BAND_LOW


# ── decision_id — stable & content-derived ───────────────────────────

def test_decision_id_deterministic_across_calls():
    a = make_decision_id(KIND_BUTTON_TARGET, "page:/docs", "Upload")
    b = make_decision_id(KIND_BUTTON_TARGET, "page:/docs", "Upload")
    assert a == b


def test_decision_id_encodes_kind_scope_identity():
    d_id = make_decision_id(KIND_FORM_SUBMIT, "page:/upload", "MyForm")
    assert "form_target" not in d_id  # sanity: no accidental substitution
    assert "form_submit" in d_id
    assert "upload" in d_id
    assert "myform" in d_id


def test_decision_id_slugs_pathy_scopes():
    """Route scopes keep slashes for readability."""
    d_id = make_decision_id(KIND_BUTTON_TARGET, "page:/documents/upload", "Save")
    assert "documents/upload" in d_id


def test_decision_id_empty_fields_get_defaults():
    d_id = make_decision_id(KIND_ARCHETYPE, "", "")
    assert "unknown" in d_id


# ── make_decision validates kind & band ──────────────────────────────

def test_make_decision_rejects_unknown_kind():
    with pytest.raises(ValueError):
        make_decision(kind="bogus_kind", scope="s", identity="i",
                      target_picked="x", confidence=BAND_HIGH,
                      source_emitter="test")


def test_make_decision_rejects_unknown_band():
    with pytest.raises(ValueError):
        make_decision(kind=KIND_BUTTON_TARGET, scope="s", identity="i",
                      target_picked="x", confidence="uncertain",
                      source_emitter="test")


def test_make_decision_accepts_all_valid_kinds_and_bands():
    from services.decision_ledger import _ALLOWED_KINDS
    for kind in _ALLOWED_KINDS:
        for band in (BAND_HIGH, BAND_MEDIUM, BAND_LOW):
            d = make_decision(kind=kind, scope="s", identity="i",
                              target_picked="x", confidence=band,
                              source_emitter="test")
            assert d.kind == kind
            assert d.confidence == band


# ── ledger persistence ───────────────────────────────────────────────

def test_record_writes_open_decisions_json(tmp_path: Path):
    d = make_decision(kind=KIND_BUTTON_TARGET, scope="page:/docs",
                      identity="Save", target_picked="SaveWorkflow",
                      confidence=BAND_HIGH, source_emitter="test")
    written = record(tmp_path, d)
    assert written is not None
    assert written.exists()

    on_disk = json.loads(written.read_text(encoding="utf-8"))
    assert "generated_at" in on_disk
    assert on_disk["decisions"][0]["target_picked"] == "SaveWorkflow"
    assert on_disk["decisions"][0]["confidence"] == BAND_HIGH


def test_record_is_idempotent_by_decision_id(tmp_path: Path):
    """Same (kind, scope, identity) = same id = overwritten, not duplicated."""
    d1 = make_decision(kind=KIND_BUTTON_TARGET, scope="page:/docs",
                       identity="Save", target_picked="SaveV1",
                       confidence=BAND_MEDIUM, source_emitter="test")
    d2 = make_decision(kind=KIND_BUTTON_TARGET, scope="page:/docs",
                       identity="Save", target_picked="SaveV2",
                       confidence=BAND_HIGH, source_emitter="test")
    record(tmp_path, d1)
    record(tmp_path, d2)
    ledger = load_ledger(tmp_path)
    assert len(ledger) == 1
    assert ledger[0]["target_picked"] == "SaveV2"
    assert ledger[0]["confidence"] == BAND_HIGH


def test_record_appends_distinct_decisions(tmp_path: Path):
    d1 = make_decision(kind=KIND_BUTTON_TARGET, scope="page:/a",
                       identity="X", target_picked="wf1",
                       confidence=BAND_HIGH, source_emitter="t")
    d2 = make_decision(kind=KIND_BUTTON_TARGET, scope="page:/b",
                       identity="Y", target_picked="wf2",
                       confidence=BAND_HIGH, source_emitter="t")
    record(tmp_path, d1)
    record(tmp_path, d2)
    assert len(load_ledger(tmp_path)) == 2


def test_record_serializes_alternatives(tmp_path: Path):
    alts = [
        make_alternative("Alt1", score=0.7, reason="close fuzzy"),
        make_alternative("Alt2", score=0.5),
    ]
    d = make_decision(kind=KIND_FORM_SUBMIT, scope="page:/f",
                      identity="MyForm", target_picked="Picked",
                      confidence=BAND_LOW, source_emitter="test",
                      alternatives=alts)
    record(tmp_path, d)
    ledger = load_ledger(tmp_path)
    assert len(ledger[0]["alternatives"]) == 2
    assert ledger[0]["alternatives"][0]["target"] == "Alt1"
    assert ledger[0]["alternatives"][0]["score"] == 0.7


def test_load_ledger_missing_file_returns_empty(tmp_path: Path):
    assert load_ledger(tmp_path) == []


def test_load_ledger_corrupt_file_returns_empty(tmp_path: Path):
    """Broken JSON must not fail generation — return empty."""
    from services.decision_ledger import OPEN_DECISIONS_REL
    p = tmp_path.joinpath(*OPEN_DECISIONS_REL)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{{not json", encoding="utf-8")
    assert load_ledger(tmp_path) == []


# ── pending_decisions filters band ───────────────────────────────────

def test_pending_hides_high_confidence(tmp_path: Path):
    """High-confidence picks ship silently — no chip."""
    record(tmp_path, make_decision(
        kind=KIND_BUTTON_TARGET, scope="s1", identity="i1",
        target_picked="x", confidence=BAND_HIGH, source_emitter="t"))
    record(tmp_path, make_decision(
        kind=KIND_BUTTON_TARGET, scope="s2", identity="i2",
        target_picked="x", confidence=BAND_MEDIUM, source_emitter="t"))
    record(tmp_path, make_decision(
        kind=KIND_BUTTON_TARGET, scope="s3", identity="i3",
        target_picked="x", confidence=BAND_LOW, source_emitter="t"))
    pending = pending_decisions(tmp_path)
    assert len(pending) == 2
    picked_scopes = {p["scope"] for p in pending}
    assert picked_scopes == {"s2", "s3"}


# ── bindings lookup + persistence ────────────────────────────────────

def test_resolve_binding_missing_returns_none(tmp_path: Path):
    assert resolve_binding(tmp_path, kind=KIND_BUTTON_TARGET,
                           scope="s", identity="i") is None


def test_save_and_resolve_roundtrip(tmp_path: Path):
    save_binding(tmp_path, kind=KIND_BUTTON_TARGET, scope="page:/docs",
                 identity="Save", target="MyWorkflow")
    got = resolve_binding(tmp_path, kind=KIND_BUTTON_TARGET,
                          scope="page:/docs", identity="Save")
    assert got == "MyWorkflow"


def test_save_binding_overwrites_prior(tmp_path: Path):
    save_binding(tmp_path, kind=KIND_BUTTON_TARGET, scope="s", identity="i",
                 target="First")
    save_binding(tmp_path, kind=KIND_BUTTON_TARGET, scope="s", identity="i",
                 target="Second")
    assert resolve_binding(tmp_path, kind=KIND_BUTTON_TARGET,
                           scope="s", identity="i") == "Second"


def test_save_binding_flips_resolved_flag_in_ledger(tmp_path: Path):
    """Chip UI hides resolved rows — the flag is how it knows."""
    d = make_decision(kind=KIND_BUTTON_TARGET, scope="page:/docs",
                      identity="Save", target_picked="Old",
                      confidence=BAND_LOW, source_emitter="test")
    record(tmp_path, d)
    save_binding(tmp_path, kind=KIND_BUTTON_TARGET, scope="page:/docs",
                 identity="Save", target="Confirmed")
    ledger = load_ledger(tmp_path)
    assert ledger[0].get("resolved") is True
    assert ledger[0].get("resolved_target") == "Confirmed"


def test_load_bindings_missing_returns_empty(tmp_path: Path):
    assert load_bindings(tmp_path) == {}


def test_load_bindings_corrupt_returns_empty(tmp_path: Path):
    from services.decision_ledger import BINDINGS_REL
    p = tmp_path.joinpath(*BINDINGS_REL)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("bogus", encoding="utf-8")
    assert load_bindings(tmp_path) == {}


# ── record_pick convenience — the emitter's typical entry point ─────

def test_record_pick_accepts_float_score(tmp_path: Path):
    """Emitters that score by float shouldn't need to import band_for_score."""
    d = record_pick(tmp_path,
                    kind=KIND_BUTTON_TARGET, scope="page:/docs",
                    identity="Save", target_picked="SaveWorkflow",
                    confidence=0.95, source_emitter="test")
    assert d.confidence == BAND_HIGH


def test_record_pick_accepts_band_string(tmp_path: Path):
    d = record_pick(tmp_path,
                    kind=KIND_BUTTON_TARGET, scope="page:/docs",
                    identity="Save", target_picked="SaveWorkflow",
                    confidence=BAND_MEDIUM, source_emitter="test")
    assert d.confidence == BAND_MEDIUM


def test_record_pick_writes_ledger(tmp_path: Path):
    record_pick(tmp_path, kind=KIND_ARCHETYPE, scope="app",
                identity="app", target_picked="doc-intel",
                confidence=0.85, source_emitter="test")
    ledger = load_ledger(tmp_path)
    assert len(ledger) == 1
    assert ledger[0]["target_picked"] == "doc-intel"
    assert ledger[0]["confidence"] == BAND_MEDIUM


def test_record_pick_survives_write_failure(tmp_path: Path, monkeypatch):
    """Ledger write failure must not raise — emitter still ships pick."""
    from services import decision_ledger as dl

    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(dl, "_write_json", boom)

    d = record_pick(tmp_path, kind=KIND_BUTTON_TARGET, scope="s",
                    identity="i", target_picked="target",
                    confidence=BAND_LOW, source_emitter="t")
    assert d.target_picked == "target"
    # Ledger empty because write failed — that's correct.
    assert load_ledger(tmp_path) == []

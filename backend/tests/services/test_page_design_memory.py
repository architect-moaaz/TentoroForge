"""Tests for services.page_design_memory — Sprint 9."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import page_design_memory as pdm


# ── Env gating ──────────────────────────────────────────────────────────

def test_memory_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_DESIGN_MEMORY", raising=False)
    assert pdm.design_memory_enabled() is False


def test_memory_enabled_when_flag_is_one(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_DESIGN_MEMORY", "1")
    assert pdm.design_memory_enabled() is True


# ── record_page ────────────────────────────────────────────────────────

def test_record_page_no_op_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_DESIGN_MEMORY", raising=False)
    pdm.record_page(
        str(tmp_path), slug="dashboard", page_type="dashboard",
        critique={"score": 8, "passes": True, "_detectors": {}},
    )
    # Ledger file must NOT exist — no writes when flag off.
    assert not (tmp_path / "reports" / "page-critic" / "_memory.json").exists()


def test_record_page_writes_ledger_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_DESIGN_MEMORY", "1")
    pdm.record_page(
        str(tmp_path), slug="dashboard", page_type="dashboard",
        critique={
            "score": 8, "passes": True,
            "_detectors": {
                "brand_echo":      {"total_echoes": 5, "meets_minimum": True},
                "signature_moves": {"detected": ["ledger_row"]},
            },
        },
    )
    ledger = tmp_path / "reports" / "page-critic" / "_memory.json"
    assert ledger.exists()
    data = json.loads(ledger.read_text())
    assert len(data["pages"]) == 1
    entry = data["pages"][0]
    assert entry["slug"] == "dashboard"
    assert entry["moves_applied"] == ["ledger_row"]
    assert entry["brand_echoes"] == 5
    assert entry["passes"] is True


def test_record_page_replaces_prior_entry_by_slug(tmp_path, monkeypatch):
    """Re-authoring a page → prior entry REPLACED (not duplicated)."""
    monkeypatch.setenv("FORGE_PAGE_DESIGN_MEMORY", "1")
    pdm.record_page(
        str(tmp_path), slug="dashboard", page_type="dashboard",
        critique={"score": 5, "passes": False, "_detectors": {}},
    )
    pdm.record_page(
        str(tmp_path), slug="dashboard", page_type="dashboard",
        critique={"score": 9, "passes": True, "_detectors": {}},
    )
    data = pdm.load_memory(str(tmp_path))
    assert len(data["pages"]) == 1
    assert data["pages"][0]["score"] == 9


def test_record_page_appends_new_slugs(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_DESIGN_MEMORY", "1")
    for slug in ("dashboard", "leases", "tenants"):
        pdm.record_page(
            str(tmp_path), slug=slug, page_type="list",
            critique={"score": 7, "passes": True, "_detectors": {}},
        )
    data = pdm.load_memory(str(tmp_path))
    assert [p["slug"] for p in data["pages"]] == ["dashboard", "leases", "tenants"]


# ── load_memory ────────────────────────────────────────────────────────

def test_load_memory_returns_empty_when_missing(tmp_path):
    data = pdm.load_memory(str(tmp_path))
    assert data == {"pages": []}


def test_load_memory_returns_empty_on_malformed_file(tmp_path):
    p = tmp_path / "reports" / "page-critic" / "_memory.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ not: valid json")
    assert pdm.load_memory(str(tmp_path)) == {"pages": []}


# ── memory_block_for_prompt ────────────────────────────────────────────

def test_memory_block_empty_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_DESIGN_MEMORY", raising=False)
    # Even if a ledger exists, disabled flag → empty output.
    (tmp_path / "reports" / "page-critic").mkdir(parents=True)
    (tmp_path / "reports" / "page-critic" / "_memory.json").write_text(
        json.dumps({"pages": [{"slug": "x", "moves_applied": []}]})
    )
    assert pdm.memory_block_for_prompt(str(tmp_path)) == ""


def test_memory_block_empty_when_no_prior_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_DESIGN_MEMORY", "1")
    assert pdm.memory_block_for_prompt(str(tmp_path)) == ""


def test_memory_block_lists_prior_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_DESIGN_MEMORY", "1")
    pdm.record_page(
        str(tmp_path), slug="dashboard", page_type="dashboard",
        critique={
            "score": 8, "passes": True,
            "_detectors": {
                "brand_echo":      {"total_echoes": 5},
                "signature_moves": {"detected": ["ledger_row", "warm_serif_h1"]},
            },
        },
    )
    pdm.record_page(
        str(tmp_path), slug="leases", page_type="list",
        critique={
            "score": 7, "passes": True,
            "_detectors": {
                "brand_echo":      {"total_echoes": 3},
                "signature_moves": {"detected": ["ledger_row"]},
            },
        },
    )
    block = pdm.memory_block_for_prompt(str(tmp_path))
    assert "<prior-pages-in-this-app>" in block
    assert "dashboard" in block
    assert "leases" in block
    assert "ledger_row, warm_serif_h1" in block
    assert "brand echoes on the page: 5" in block
    assert "brand echoes on the page: 3" in block


def test_memory_block_caps_prior_pages_to_six(tmp_path, monkeypatch):
    """The prompt cap keeps the DCP bounded; only the last N pages appear."""
    monkeypatch.setenv("FORGE_PAGE_DESIGN_MEMORY", "1")
    for i in range(10):
        pdm.record_page(
            str(tmp_path), slug=f"page{i}", page_type="list",
            critique={"score": 7, "passes": True, "_detectors": {}},
        )
    block = pdm.memory_block_for_prompt(str(tmp_path))
    # First four pages must be pruned; last six must appear.
    assert "page0" not in block
    assert "page3" not in block
    assert "page4" in block
    assert "page9" in block

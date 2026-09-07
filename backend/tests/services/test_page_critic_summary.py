"""Tests for services.page_critic_summary — Sprint 10."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import page_critic_summary as pcs


def _write_report(tmp_path: Path, slug: str, payload: dict) -> None:
    d = tmp_path / "reports" / "page-critic"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.json").write_text(json.dumps(payload), encoding="utf-8")


# ── No-input behavior ──────────────────────────────────────────────────

def test_build_summary_returns_none_when_no_reports(tmp_path):
    assert pcs.build_summary(str(tmp_path)) is None


def test_persist_summary_writes_nothing_when_no_reports(tmp_path):
    result = pcs.persist_summary(str(tmp_path))
    assert result is None
    assert not (tmp_path / "reports" / "page-critic" / "summary.json").exists()


# ── Aggregation ────────────────────────────────────────────────────────

def test_summary_counts_passes_and_fails(tmp_path):
    _write_report(tmp_path, "dashboard", {
        "score": 8, "passes": True, "gaps": [],
        "_detectors": {"brand_echo": {"primary_hex": "#f", "total_echoes": 5, "meets_minimum": True}},
    })
    _write_report(tmp_path, "leases", {
        "score": 4, "passes": False, "gaps": [{"severity": "high"}],
        "_detectors": {"brand_echo": {"primary_hex": "#f", "total_echoes": 0, "meets_minimum": False}},
    })
    s = pcs.build_summary(str(tmp_path))
    assert s["total_pages"] == 2
    assert s["pages_passed"] == 1
    assert s["pages_failed"] == 1
    assert s["pass_rate"] == 0.5
    assert s["avg_score"] == 6.0


def test_summary_aggregates_signature_moves(tmp_path):
    _write_report(tmp_path, "a", {
        "score": 7, "passes": True, "gaps": [],
        "_detectors": {"signature_moves": {
            "detected": ["ledger_row"],
            "missing":  ["warm_serif_h1", "keyline_breadcrumb"],
        }},
    })
    _write_report(tmp_path, "b", {
        "score": 6, "passes": True, "gaps": [],
        "_detectors": {"signature_moves": {
            "detected": ["ledger_row"],
            "missing":  ["warm_serif_h1"],
        }},
    })
    s = pcs.build_summary(str(tmp_path))
    assert dict(s["signature_moves"]["top_missing"])["warm_serif_h1"] == 2
    assert dict(s["signature_moves"]["top_missing"])["keyline_breadcrumb"] == 1
    assert dict(s["signature_moves"]["top_applied"])["ledger_row"] == 2


def test_summary_aggregates_brand_echo(tmp_path):
    _write_report(tmp_path, "a", {
        "passes": True, "score": 8, "gaps": [],
        "_detectors": {"brand_echo": {"primary_hex": "#f", "total_echoes": 6, "meets_minimum": True}},
    })
    _write_report(tmp_path, "b", {
        "passes": True, "score": 8, "gaps": [],
        "_detectors": {"brand_echo": {"primary_hex": "#f", "total_echoes": 2, "meets_minimum": False}},
    })
    _write_report(tmp_path, "c", {
        "passes": True, "score": 8, "gaps": [],
        # No primary_hex → not counted in brand aggregation.
        "_detectors": {"brand_echo": {"primary_hex": None}},
    })
    s = pcs.build_summary(str(tmp_path))
    be = s["brand_echo"]
    assert be["pages_evaluated"] == 2
    assert be["pages_meets_min"] == 1
    assert be["avg_echoes"] == 4.0


def test_summary_aggregates_gap_severities(tmp_path):
    _write_report(tmp_path, "a", {
        "passes": False, "score": 5,
        "gaps": [{"severity": "high"}, {"severity": "medium"}, {"severity": "low"}],
    })
    _write_report(tmp_path, "b", {
        "passes": True, "score": 8,
        "gaps": [{"severity": "medium"}],
    })
    s = pcs.build_summary(str(tmp_path))
    assert s["gap_counts_by_severity"] == {"high": 1, "medium": 2, "low": 1}


def test_summary_skips_memory_ledger_and_summary_itself(tmp_path):
    _write_report(tmp_path, "a", {"passes": True, "score": 8, "gaps": []})
    # The memory ledger from Sprint 9 must not be treated as a page report.
    (tmp_path / "reports" / "page-critic" / "_memory.json").write_text(
        json.dumps({"pages": [{"slug": "ghost"}]})
    )
    # A stale summary.json must not recursively aggregate itself.
    (tmp_path / "reports" / "page-critic" / "summary.json").write_text(
        json.dumps({"total_pages": 999})
    )
    s = pcs.build_summary(str(tmp_path))
    assert s["total_pages"] == 1
    assert s["pages"][0]["slug"] == "a"


def test_summary_survives_malformed_report(tmp_path):
    _write_report(tmp_path, "good", {"passes": True, "score": 8, "gaps": []})
    (tmp_path / "reports" / "page-critic" / "bad.json").write_text("{ not json", encoding="utf-8")
    s = pcs.build_summary(str(tmp_path))
    assert s["total_pages"] == 1


def test_persist_summary_writes_expected_path(tmp_path):
    _write_report(tmp_path, "a", {"passes": True, "score": 8, "gaps": []})
    result = pcs.persist_summary(str(tmp_path))
    expected = tmp_path / "reports" / "page-critic" / "summary.json"
    assert result == expected
    assert expected.exists()
    written = json.loads(expected.read_text(encoding="utf-8"))
    assert written["total_pages"] == 1

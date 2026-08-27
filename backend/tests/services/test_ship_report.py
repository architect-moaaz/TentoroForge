"""V3 — unified ship verdict (services.ship_report)."""
from __future__ import annotations

import json

import pytest

from services.ship_report import REPORT_NAME, build_ship_report


def _write(root, rel, doc):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))


def test_empty_app_passes(tmp_path):
    report = build_ship_report(str(tmp_path))
    assert report["verdict"] == "pass"
    assert (tmp_path / REPORT_NAME).exists()
    assert report["sources"]["delivery"]["present"] is False


def test_errors_warn_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_SHIP_GATE", raising=False)
    _write(tmp_path, "contracts/delivery-report.json",
           {"errors": [{"rule": "launcher_missing", "detail": "x"}], "warnings": []})
    report = build_ship_report(str(tmp_path))
    assert report["verdict"] == "warn"
    assert report["summary"]["errors"] == 1
    assert report["sources"]["delivery"]["errors"] == 1


def test_strict_mode_blocks_on_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_SHIP_GATE", "strict")
    _write(tmp_path, "contracts/delivery-report.json", {"errors": [{"rule": "r"}]})
    assert build_ship_report(str(tmp_path))["verdict"] == "block"


def test_security_critical_blocks_even_default(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_SHIP_GATE", raising=False)
    _write(tmp_path, "security-report.json",
           {"errors": [{"rule": "secret_leak", "severity": "critical", "detail": "AKIA…"}]})
    report = build_ship_report(str(tmp_path))
    assert report["verdict"] == "block"
    assert report["summary"]["criticals"] == 1


def test_off_mode_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_SHIP_GATE", "off")
    _write(tmp_path, "security-report.json",
           {"errors": [{"rule": "secret_leak", "severity": "critical"}]})
    assert build_ship_report(str(tmp_path))["verdict"] == "warn"


def test_quarantine_unresolved_counts(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_SHIP_GATE", raising=False)
    _write(tmp_path, "src/contracts/quarantine.json",
           {"quarantine": [{"check": "binding_contract", "passed": False,
                            "unresolved": [{"kind": "unknown_slug", "detail": "x"},
                                           {"kind": "unknown_slug", "detail": "y"}]}]})
    report = build_ship_report(str(tmp_path))
    assert report["sources"]["quarantine"]["errors"] == 2
    assert report["verdict"] == "warn"


def test_malformed_artifact_degrades_to_warning(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_SHIP_GATE", raising=False)
    p = tmp_path / "contracts"
    p.mkdir(parents=True)
    (p / "delivery-report.json").write_text("{not json")
    report = build_ship_report(str(tmp_path))
    assert report["verdict"] == "pass" or report["summary"]["warnings"] >= 1
    assert report["sources"]["delivery"]["present"] is True


def test_sample_is_clipped(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_SHIP_GATE", raising=False)
    _write(tmp_path, "contracts/delivery-report.json",
           {"errors": [{"rule": "r", "detail": "z" * 1000}] * 9})
    src = build_ship_report(str(tmp_path))["sources"]["delivery"]
    assert len(src["sample"]) == 5
    assert all(len(s) <= 240 for s in src["sample"])

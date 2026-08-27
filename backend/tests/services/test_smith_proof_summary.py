"""Tests for smith_memory.build_proof_summary + block wiring.

Smith reads contracts/proof_report.json on every turn so it can proactively
surface pipeline validator findings ("your /scans/[id]/prices page has an
orphan binding — want me to fix it?") instead of the user having to know
the report file exists.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_memory import build_memory_block, build_proof_summary


def _write_report(dir_: Path, data: dict) -> None:
    (dir_ / "contracts").mkdir(parents=True, exist_ok=True)
    (dir_ / "contracts" / "proof_report.json").write_text(json.dumps(data))


def test_empty_when_no_report(tmp_path: Path):
    assert build_proof_summary(str(tmp_path)) == ""


def test_empty_when_passed_and_clean(tmp_path: Path):
    """passed=True with no findings → nothing to say to Smith."""
    _write_report(tmp_path, {
        "passed": True, "error_count": 0, "warning_count": 0, "findings": []
    })
    assert build_proof_summary(str(tmp_path)) == ""


def test_reports_errors_and_warnings(tmp_path: Path):
    _write_report(tmp_path, {
        "passed": False,
        "error_count": 2,
        "warning_count": 1,
        "findings": [
            {"severity": "error", "code": "orphan-navigate",
             "message": "Button navigate=/x targets missing page",
             "file": "src/schemas/scan.json"},
            {"severity": "error", "code": "undefined-ref",
             "message": "{{status}} references undefined var",
             "file": "workflows/ScanProduct.json"},
            {"severity": "warning", "code": "empty-page",
             "message": "Page has no data-bearing components",
             "file": "src/schemas/dashboard.json"},
        ],
    })
    summary = build_proof_summary(str(tmp_path))
    assert "FAILED (2 errors, 1 warning)" in summary
    assert "orphan-navigate" in summary
    assert "undefined-ref" in summary
    assert "empty-page" in summary
    # Instruction to Smith to surface selectively, not dump.
    assert "surface only what's relevant" in summary


def test_error_cap_respected(tmp_path: Path):
    _write_report(tmp_path, {
        "passed": False,
        "error_count": 20,
        "warning_count": 0,
        "findings": [
            {"severity": "error", "code": f"code-{i}",
             "message": f"msg {i}", "file": "f.json"}
            for i in range(20)
        ],
    })
    summary = build_proof_summary(str(tmp_path), max_errors=3)
    assert "Errors (top 3):" in summary
    assert "code-0" in summary
    assert "code-19" not in summary


def test_warning_cap_respected(tmp_path: Path):
    _write_report(tmp_path, {
        "passed": False,
        "error_count": 1,
        "warning_count": 20,
        "findings": (
            [{"severity": "error", "code": "e", "message": "e", "file": "f"}]
            + [{"severity": "warning", "code": f"w-{i}",
                "message": f"w {i}", "file": "f"}
               for i in range(20)]
        ),
    })
    summary = build_proof_summary(str(tmp_path), max_warnings=2)
    assert "Warnings (top 2):" in summary
    assert "w-0" in summary
    assert "w-19" not in summary


def test_malformed_report_returns_empty(tmp_path: Path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "proof_report.json").write_text("not json")
    assert build_proof_summary(str(tmp_path)) == ""


def test_memory_block_renders_proof_summary_section():
    """When passed to build_memory_block, the summary lands under its own
    header inside the <smith-memory> tag."""
    block = build_memory_block(
        [],
        [],
        proof_summary="Status: FAILED (1 error, 0 warnings)\n- foo",
    )
    assert "## App proof report" in block
    assert "Status: FAILED" in block
    assert "<smith-memory>" in block


def test_memory_block_omits_section_when_empty():
    block = build_memory_block([], [], proof_summary="")
    assert "## App proof report" not in block


def test_workflow_file_locator_key(tmp_path: Path):
    """workflow_validator findings use `workflow_file`, not `file` — the
    formatter should still emit a locator."""
    _write_report(tmp_path, {
        "passed": False,
        "error_count": 1,
        "warning_count": 0,
        "findings": [
            {"severity": "error", "code": "undefined-ref",
             "message": "x", "workflow_file": "ScanProduct.json"},
        ],
    })
    summary = build_proof_summary(str(tmp_path))
    assert "ScanProduct.json" in summary

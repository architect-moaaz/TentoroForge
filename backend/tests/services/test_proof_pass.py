"""Tests for services.proof_pass — Phase 5.1 assertion pass."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.proof_pass import persist_report, run_proof_pass


def _write_page(schemas_dir: Path, name: str, data: dict) -> None:
    schemas_dir.mkdir(parents=True, exist_ok=True)
    (schemas_dir / name).write_text(json.dumps(data), encoding="utf-8")


def _write_wf(wf_dir: Path, name: str, data: dict) -> None:
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / name).write_text(json.dumps(data), encoding="utf-8")


# ---------- empty-page ----------------------------------------------------

def test_empty_page_flagged(tmp_path: Path):
    _write_page(tmp_path / "src" / "schemas", "stub.json", {
        "route": "/stub",
        "root": {"type": "Stack", "children": [
            {"type": "Heading", "props": {"content": "Stub"}},
        ]},
    })
    report = run_proof_pass(tmp_path)
    codes = {f.code for f in report.findings}
    assert "empty-page" in codes


def test_page_with_content_ok(tmp_path: Path):
    _write_page(tmp_path / "src" / "schemas", "real.json", {
        "route": "/real",
        "dataSources": [{"name": "rows", "entity": "X", "op": "list"}],
        "root": {"type": "Stack", "children": [
            {"type": "Heading", "props": {"content": "Real"}},
            {"type": "Repeat", "bind": "rows", "children": [
                {"type": "Text", "props": {"content": "{{item.name}}"}},
            ]},
        ]},
    })
    report = run_proof_pass(tmp_path)
    assert not any(f.code == "empty-page" for f in report.findings)


# ---------- list-without-repeat -------------------------------------------

def test_list_datasource_without_repeat_flagged(tmp_path: Path):
    _write_page(tmp_path / "src" / "schemas", "no-repeat.json", {
        "route": "/no-repeat",
        "dataSources": [{"name": "items", "entity": "X", "op": "list"}],
        "root": {"type": "Text", "props": {"content": "hi"}},
    })
    report = run_proof_pass(tmp_path)
    assert any(f.code == "list-without-repeat" for f in report.findings)


# ---------- repeat-without-source -----------------------------------------

def test_repeat_binding_to_undeclared_source_flagged(tmp_path: Path):
    _write_page(tmp_path / "src" / "schemas", "bad-bind.json", {
        "route": "/bad",
        "dataSources": [],
        "root": {"type": "Repeat", "bind": "ghosts", "children": []},
    })
    report = run_proof_pass(tmp_path)
    codes = {f.code for f in report.findings}
    assert "repeat-without-source" in codes


# ---------- duplicate-route -----------------------------------------------

def test_two_pages_same_route_flagged(tmp_path: Path):
    schemas = tmp_path / "src" / "schemas"
    _write_page(schemas, "a.json", {"route": "/scans", "root": {"type": "Text"}})
    _write_page(schemas, "b.json", {"route": "/scans", "root": {"type": "Text"}})
    report = run_proof_pass(tmp_path)
    assert any(f.code == "duplicate-route" for f in report.findings)


# ---------- aggregation + report shape ------------------------------------

def test_report_passed_false_when_errors_present(tmp_path: Path):
    _write_page(tmp_path / "src" / "schemas", "bad.json", {
        "route": "/bad",
        "dataSources": [],
        "root": {"type": "Repeat", "bind": "ghosts", "children": []},
    })
    report = run_proof_pass(tmp_path)
    assert report.passed is False
    assert report.error_count >= 1


def test_report_passed_true_when_only_warnings(tmp_path: Path):
    _write_page(tmp_path / "src" / "schemas", "stub.json", {
        "route": "/stub",
        "root": {"type": "Heading", "props": {"content": "hi"}},
    })
    report = run_proof_pass(tmp_path)
    # empty-page is a warning, no errors → passed=True.
    assert report.warning_count >= 1
    assert report.passed is True


def test_persist_writes_json(tmp_path: Path):
    _write_page(tmp_path / "src" / "schemas", "p.json", {
        "route": "/p", "root": {"type": "Heading", "props": {"content": "x"}},
    })
    report = run_proof_pass(tmp_path)
    path = persist_report(report, tmp_path)
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert "passed" in loaded
    assert "findings" in loaded


def test_run_proof_pass_no_schemas_dir_returns_empty_report(tmp_path: Path):
    """No src/schemas/ → report is empty and passed=True (nothing to check)."""
    report = run_proof_pass(tmp_path)
    assert report.passed is True
    assert report.findings == []

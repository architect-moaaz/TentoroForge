"""Tests for services.interaction_authority — Spec E Wave 1."""
from __future__ import annotations

import json
from pathlib import Path

from services import interaction_authority as ia


def _write_reg(root: Path, reg: dict) -> None:
    (root / "registry.json").write_text(json.dumps(reg), encoding="utf-8")


def _write_page(root: Path, name: str, page: dict) -> Path:
    schemas = root / "src" / "schemas"
    schemas.mkdir(parents=True, exist_ok=True)
    p = schemas / f"{name}.json"
    p.write_text(json.dumps(page), encoding="utf-8")
    return p


REG = {
    "entities": {
        "Order": {"fields": {"id": {}, "status": {}}, "indexes": []},
    },
    "relations": [],
    "api_routes": {},
    "components": {},
    "pages": {},
    "workflow_bindings": {"ArchiveOrders": {"page": "", "variables": {}}},
}


def test_disabled_without_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_E_INTERACTIONS", raising=False)
    report = ia.validate_output_dir(tmp_path)
    assert report.enabled is False
    assert report.files_written == 0


def test_strips_unknown_workflow_bulk_action(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_INTERACTIONS", "1")
    _write_reg(tmp_path, REG)
    page_fp = _write_page(tmp_path, "orders", {
        "entity": "Order",
        "dataSources": [{"op": "list", "entity": "Order"}],
        "content": [{
            "type": "Table",
            "props": {
                "bulkActions": [
                    {"label": "Archive", "workflow": "ArchiveOrders"},
                    {"label": "Bogus", "workflow": "NotAWorkflow"},
                ],
                "columns": [],
            },
        }],
    })
    report = ia.validate_output_dir(tmp_path)
    assert report.enabled is True
    assert report.tables_seen == 1
    written = json.loads(page_fp.read_text(encoding="utf-8"))
    bulk = written["content"][0]["props"]["bulkActions"]
    assert len(bulk) == 1
    assert bulk[0]["workflow"] == "ArchiveOrders"
    kinds = {f.kind for f in report.findings}
    assert "unknown_workflow" in kinds


def test_kanban_movable_between_lanes_unknown_column_stripped(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_INTERACTIONS", "1")
    _write_reg(tmp_path, REG)
    page_fp = _write_page(tmp_path, "orders", {
        "entity": "Order",
        "dataSources": [{"op": "list", "entity": "Order"}],
        "content": [{
            "type": "Kanban",
            "props": {"moveBetweenLanes": {"sourceField": "not_a_column"}},
        }],
    })
    ia.validate_output_dir(tmp_path)
    written = json.loads(page_fp.read_text(encoding="utf-8"))
    assert "moveBetweenLanes" not in written["content"][0]["props"]


def test_kanban_movable_between_lanes_valid_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_INTERACTIONS", "1")
    _write_reg(tmp_path, REG)
    page_fp = _write_page(tmp_path, "orders", {
        "entity": "Order",
        "dataSources": [{"op": "list", "entity": "Order"}],
        "content": [{
            "type": "Kanban",
            "props": {"moveBetweenLanes": {"sourceField": "status"}},
        }],
    })
    ia.validate_output_dir(tmp_path)
    written = json.loads(page_fp.read_text(encoding="utf-8"))
    assert written["content"][0]["props"]["moveBetweenLanes"]["sourceField"] == "status"


def test_persist_report_writes_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_INTERACTIONS", "1")
    _write_reg(tmp_path, REG)
    _write_page(tmp_path, "orders", {"entity": "Order", "content": []})
    report = ia.validate_output_dir(tmp_path)
    ia.persist_report(report, tmp_path)
    out = tmp_path / "contracts" / "interaction_authority.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["enabled"] is True

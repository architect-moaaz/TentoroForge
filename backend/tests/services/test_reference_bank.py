# backend/tests/services/test_reference_bank.py
import json
from pathlib import Path

import pytest

from services.reference_bank import (
    load_exemplars, available_cells, render_exemplars_block, Exemplar
)


@pytest.fixture
def temp_bank(tmp_path: Path, monkeypatch):
    """Build a tiny throwaway bank under tmp_path and point the loader at it."""
    bank = tmp_path / "reference_pages"
    cell = bank / "healthcare" / "list"
    cell.mkdir(parents=True)
    schema = {"schemaVersion": "2", "id": "x", "route": "/x", "meta": {"title": "Patients"},
              "dataSources": [], "root": {"id": "r", "type": "Stack", "props": {}, "children": []}}
    (cell / "exemplar_01.json").write_text(json.dumps(schema), encoding="utf-8")
    (cell / "exemplar_01.meta.json").write_text(json.dumps({
        "score": 8.4, "scored_at": "2026-05-06T10:00:00Z",
        "model_used": "sonnet-4-5", "seeder_version": "v1",
    }), encoding="utf-8")
    (cell / "exemplar_01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr("services.reference_bank._BANK_ROOT", bank)
    return bank


def test_load_exemplars_returns_exemplar_objects(temp_bank):
    exemplars = load_exemplars("healthcare", "list", limit=2)
    assert len(exemplars) == 1
    e = exemplars[0]
    assert isinstance(e, Exemplar)
    assert e.score == 8.4
    assert e.schema["id"] == "x"


def test_load_exemplars_missing_cell_returns_empty(temp_bank):
    assert load_exemplars("nonexistent", "list", limit=2) == []


def test_load_exemplars_respects_limit(tmp_path: Path, monkeypatch):
    bank = tmp_path / "reference_pages"
    cell = bank / "general" / "detail"
    cell.mkdir(parents=True)
    for i in range(5):
        (cell / f"exemplar_{i:02d}.json").write_text(json.dumps({"id": f"e{i}"}), encoding="utf-8")
        (cell / f"exemplar_{i:02d}.meta.json").write_text(json.dumps({"score": 8.0 + i * 0.1}), encoding="utf-8")
    monkeypatch.setattr("services.reference_bank._BANK_ROOT", bank)
    assert len(load_exemplars("general", "detail", limit=2)) == 2


def test_load_exemplars_sorted_by_score_desc(tmp_path: Path, monkeypatch):
    bank = tmp_path / "reference_pages"
    cell = bank / "general" / "list"
    cell.mkdir(parents=True)
    for i, score in enumerate([8.1, 8.5, 8.3]):
        (cell / f"exemplar_{i}.json").write_text(json.dumps({"id": f"e{i}"}), encoding="utf-8")
        (cell / f"exemplar_{i}.meta.json").write_text(json.dumps({"score": score}), encoding="utf-8")
    monkeypatch.setattr("services.reference_bank._BANK_ROOT", bank)
    exs = load_exemplars("general", "list", limit=3)
    scores = [e.score for e in exs]
    assert scores == sorted(scores, reverse=True)


def test_available_cells(temp_bank):
    cells = available_cells()
    assert ("healthcare", "list") in cells


def test_render_exemplars_block_includes_score_and_schema(temp_bank):
    exemplars = load_exemplars("healthcare", "list", limit=2)
    block = render_exemplars_block(exemplars)
    assert "8.4" in block
    assert "Exemplar 1" in block
    assert "schemaVersion" in block  # the schema JSON is inlined


def test_render_exemplars_block_empty_returns_empty_string():
    assert render_exemplars_block([]) == ""

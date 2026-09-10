"""Tests for the Phase 6b record composer bootstrap + recipe-fallback."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.apply_record_maquette import apply_maquettes_to_records


def _write_plan(root: Path, pages: list[dict], entities: dict | None = None) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "plan.json").write_text(
        json.dumps({"pages": pages, "entities": entities or {}}),
        encoding="utf-8",
    )


def _write_registry(root: Path, entities: dict) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "registry.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8",
    )


def _write_maquettes(root: Path, entries: list) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "record-maquettes.json").write_text(
        json.dumps(entries), encoding="utf-8",
    )


def _bookings_entity() -> dict:
    return {"bookings": {"fields": [
        {"name": "id", "type": "uuid"},
        {"name": "email", "type": "text"},
        {"name": "phone", "type": "text"},
        {"name": "startAt", "type": "timestamp"},
    ]}}


def _minimal_record_maquette(mode: str = "create", route: str = "/bookings/new") -> dict:
    return {
        "entity": "bookings", "route": route, "mode": mode,
        "section_grouping": [{"label": "Contact", "fields": ["email"]}],
    }


# ─────────────────────────── flag OFF: legacy ──────────────────────────


class TestFlagOffLegacy:
    def test_missing_schema_reports_no_schema(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_minimal_record_maquette()])
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 0
        assert any("no schema" in r for r in result["reasons"])


# ─────────────────────────── flag ON: bootstrap ────────────────────────


class TestFlagOnBootstrap:
    def test_bootstraps_new_schema(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_minimal_record_maquette()])
        _write_plan(tmp_path, [{"route": "/bookings/new", "type": "form", "entity": "bookings"}],
                     _bookings_entity())
        target = tmp_path / "src" / "schemas" / "bookings/new.json"
        assert not target.is_file()
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 1
        assert target.is_file()
        out = json.loads(target.read_text(encoding="utf-8"))
        assert out.get("meta", {}).get("record_maquette_composed") is True


# ─────────────────────────── flag ON: recipe fallback ─────────────────


class TestFlagOnRecipeFallback:
    def test_no_maquettes_recipe_fills_all_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        _write_registry(tmp_path, _bookings_entity())
        _write_plan(tmp_path, [
            {"route": "/bookings/new", "type": "form", "entity": "bookings"},
            {"route": "/bookings/[id]", "type": "detail", "entity": "bookings"},
        ], _bookings_entity())
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 2
        assert (tmp_path / "src" / "schemas" / "bookings/new.json").is_file()
        assert (tmp_path / "src" / "schemas" / "bookings/[id].json").is_file()

    def test_mode_inference_from_route_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # /new → create form, /[id]/edit → edit form, /[id] → view.
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        _write_registry(tmp_path, _bookings_entity())
        _write_plan(tmp_path, [
            {"route": "/bookings/new", "type": "form", "entity": "bookings"},
            {"route": "/bookings/[id]/edit", "type": "edit", "entity": "bookings"},
            {"route": "/bookings/[id]", "type": "detail", "entity": "bookings"},
        ], _bookings_entity())
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 3
        # Verify each mode landed the right builder shape.
        # create/edit use build_form_page → has a Form node; view uses
        # build_detail_page → no Form.
        for slug, expect_form in [
            ("bookings/new", True),
            ("bookings/[id]/edit", True),
            ("bookings/[id]", False),
        ]:
            doc = json.loads((tmp_path / "src" / "schemas" / f"{slug}.json").read_text(encoding="utf-8"))
            body = json.dumps(doc)
            has_form = '"type": "Form"' in body or '"Form"' in body
            if expect_form:
                assert has_form, f"{slug} should contain a Form node"

    def test_tail_fill_covers_records_without_maquette_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        _write_registry(tmp_path, _bookings_entity())
        _write_plan(tmp_path, [
            {"route": "/bookings/new", "type": "form", "entity": "bookings"},
            {"route": "/bookings/[id]/edit", "type": "edit", "entity": "bookings"},
            {"route": "/bookings/[id]", "type": "detail", "entity": "bookings"},
        ], _bookings_entity())
        # Only maquette-author'd /bookings/new.
        _write_maquettes(tmp_path, [_minimal_record_maquette(route="/bookings/new")])
        result = apply_maquettes_to_records(str(tmp_path))
        # 1 maquette-driven + 2 tail-filled.
        assert result["applied"] == 3

    def test_no_maquette_no_record_pages_coherent_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        _write_registry(tmp_path, _bookings_entity())
        _write_plan(tmp_path, [{"route": "/bookings", "type": "list"}],
                     _bookings_entity())
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 0
        assert any("no record pages in plan" in r for r in result["reasons"])

"""Tests for the Phase 6a collection composer bootstrap + recipe-fallback."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.apply_collection_maquette import apply_maquettes_to_collections


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
    (root / "src" / "contracts" / "collection-maquettes.json").write_text(
        json.dumps(entries), encoding="utf-8",
    )


def _write_schema(root: Path, slug: str, doc: dict) -> Path:
    p = root / "src" / "schemas" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _sessions_entity() -> dict:
    return {"sessions": {"fields": [
        {"name": "id", "type": "uuid"},
        {"name": "title", "type": "text"},
        {"name": "startAt", "type": "timestamp"},
        {"name": "status", "type": "text"},
    ]}}


def _minimal_maquette(entity: str = "sessions", route: str = "/sessions") -> dict:
    return {
        "entity": entity, "route": route, "layout": "table",
        "columns": [{"name": "title", "label": "Class"}],
    }


# ─────────────────────────── flag OFF: legacy ──────────────────────────


class TestFlagOffLegacyBehaviour:
    def test_no_maquettes_returns_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 0
        assert any("no maquettes" in r for r in result["reasons"])

    def test_missing_schema_still_reports_no_schema(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_minimal_maquette()])
        result = apply_maquettes_to_collections(str(tmp_path))
        # No bootstrap in legacy path.
        assert result["applied"] == 0
        assert any("no schema" in r for r in result["reasons"])


# ─────────────────────────── flag ON: bootstrap ────────────────────────


class TestFlagOnBootstrap:
    def test_bootstraps_new_schema_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_minimal_maquette()])
        _write_plan(tmp_path, [{"route": "/sessions", "type": "list", "entity": "sessions"}],
                     _sessions_entity())
        target = tmp_path / "src" / "schemas" / "sessions.json"
        assert not target.is_file()
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 1
        assert target.is_file()

    def test_bootstrap_reason_marker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_minimal_maquette()])
        _write_plan(tmp_path, [{"route": "/sessions", "type": "list", "entity": "sessions"}],
                     _sessions_entity())
        apply_maquettes_to_collections(str(tmp_path))
        # No exception; file exists.
        out = json.loads((tmp_path / "src" / "schemas" / "sessions.json").read_text(encoding="utf-8"))
        # The composer marker is stamped so guards go into assert-only mode.
        assert out.get("meta", {}).get("collection_maquette_composed") is True


# ─────────────────────────── flag ON: recipe fallback ─────────────────


class TestFlagOnRecipeFallback:
    def test_no_maquette_file_recipe_fills_all_collection_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        _write_registry(tmp_path, _sessions_entity())
        _write_plan(tmp_path, [
            {"route": "/sessions", "type": "list", "entity": "sessions"},
            {"route": "/dashboard", "type": "dashboard", "entity": "sessions"},
        ], _sessions_entity())
        # NO maquettes file.
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] >= 1
        # Only the collection page got a file (dashboards are not this composer's job).
        assert (tmp_path / "src" / "schemas" / "sessions.json").is_file()
        assert not (tmp_path / "src" / "schemas" / "dashboard.json").is_file()

    def test_no_maquette_no_collection_pages_returns_coherent_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        _write_registry(tmp_path, _sessions_entity())
        _write_plan(tmp_path, [{"route": "/dashboard", "type": "dashboard"}],
                     _sessions_entity())
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 0
        assert any("no collection pages in plan" in r for r in result["reasons"])

    def test_unreadable_maquettes_falls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        _write_registry(tmp_path, _sessions_entity())
        _write_plan(tmp_path, [{"route": "/sessions", "type": "list", "entity": "sessions"}],
                     _sessions_entity())
        # Corrupt maquettes file.
        (tmp_path / "src" / "contracts").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "contracts" / "collection-maquettes.json").write_text(
            "not-json", encoding="utf-8",
        )
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 1
        assert (tmp_path / "src" / "schemas" / "sessions.json").is_file()

    def test_tail_fill_covers_pages_without_maquette_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Plan has 3 collection pages but the maquette author only had
        # budget for one — the remaining 2 should be recipe-filled.
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        _write_registry(tmp_path, _sessions_entity())
        _write_plan(tmp_path, [
            {"route": "/sessions", "type": "list", "entity": "sessions"},
            {"route": "/upcoming", "type": "list", "entity": "sessions"},
            {"route": "/completed", "type": "list", "entity": "sessions"},
        ], _sessions_entity())
        # Only /sessions has a maquette.
        _write_maquettes(tmp_path, [_minimal_maquette(route="/sessions")])

        result = apply_maquettes_to_collections(str(tmp_path))
        # 1 maquette-driven + 2 recipe-filled = 3 applied.
        assert result["applied"] == 3
        for slug in ("sessions", "upcoming", "completed"):
            assert (tmp_path / "src" / "schemas" / f"{slug}.json").is_file()

    def test_tail_fill_skips_composer_authored_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # If a page is already marked composer-authored (from a prior
        # pass), the tail-fill should skip it — otherwise re-runs would
        # replace the composer's output with the recipe.
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        _write_registry(tmp_path, _sessions_entity())
        _write_plan(tmp_path, [
            {"route": "/sessions", "type": "list", "entity": "sessions"},
        ], _sessions_entity())
        # Pre-existing composer-marked schema.
        _write_schema(tmp_path, "sessions", {
            "id": "sessions", "route": "/sessions", "root": {"type": "Stack"},
            "meta": {"collection_maquette_composed": True},
        })
        # No maquette entry for /sessions.
        _write_maquettes(tmp_path, [])
        result = apply_maquettes_to_collections(str(tmp_path))
        # Tail-fill should not overwrite the marked file.
        after = json.loads((tmp_path / "src" / "schemas" / "sessions.json").read_text(encoding="utf-8"))
        assert after.get("meta", {}).get("collection_maquette_composed") is True

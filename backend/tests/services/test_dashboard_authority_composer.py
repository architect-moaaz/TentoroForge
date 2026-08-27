"""Tests for the Phase 3 composer bootstrap + recipe-fallback behaviour.

Under FORGE_DASHBOARD_AUTHORITY the composer becomes the sole writer for
dashboards. Two extensions activate:

1. **Bootstrap** — create the dashboard schema from scratch when the
   LLM skipped writing it (the flag makes the LLM skip too).
2. **Fallback via completeness** — when the maquette JSON is missing
   (LLM author failed), write a bootstrap skeleton then invoke
   dashboard_completeness to fill it with the recipe library defaults.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.apply_dashboard_maquette import apply_maquette_to_dashboard


def _write_plan(root: Path, pages: list[dict]) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "plan.json").write_text(
        json.dumps({"pages": pages,
                     "entities": {"tasks": {"fields": [{"name": "title", "type": "text"}]}}}),
        encoding="utf-8",
    )


def _write_maquette(root: Path, doc: dict) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "dashboard-maquette.json").write_text(
        json.dumps(doc), encoding="utf-8",
    )


def _basic_maquette() -> dict:
    return {
        "kpis": [{"label": "Tasks", "entity": "tasks", "op": "count"}],
        "primary_chart": {
            "title": "Tasks over time",
            "entity": "tasks",
            "kind": "bar",
            "group_by": "createdAt",
        },
        "activity": {"entity": "tasks", "title": "Recent"},
    }


# ─────────────────────────── flag OFF: legacy behaviour ───────────────


class TestFlagOffLegacyBehaviour:
    def test_missing_maquette_returns_no_maquette(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")  # explicit opt-out — the flag now defaults ON
        _write_plan(tmp_path, [{"route": "/dashboard", "type": "dashboard"}])
        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is False
        assert "no maquette" in result["reason"]

    def test_missing_schema_returns_no_schema(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")  # explicit opt-out — the flag now defaults ON
        _write_plan(tmp_path, [{"route": "/dashboard", "type": "dashboard"}])
        _write_maquette(tmp_path, _basic_maquette())
        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is False
        assert "no dashboard schema found" in result["reason"]


# ─────────────────────────── flag ON: bootstrap ────────────────────────


class TestFlagOnBootstrap:
    def test_bootstraps_new_schema_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Simulate the P3 authority state: LLM agent skipped the dashboard,
        # so no /src/schemas/dashboard.json exists on disk. The composer
        # should now create it from the maquette.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        _write_plan(tmp_path, [{"route": "/dashboard", "type": "dashboard"}])
        _write_maquette(tmp_path, _basic_maquette())

        # Precondition — nothing on disk.
        target = tmp_path / "src" / "schemas" / "dashboard.json"
        assert not target.is_file()

        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is True
        assert result["reason"] == "ok (bootstrap)"
        # File exists AFTER the bootstrap.
        assert target.is_file()

    def test_bootstrap_uses_plan_derived_route(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # An app that names its dashboard /admin should get admin.json
        # under the bootstrap path (same tier-1 as the finder).
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        _write_plan(tmp_path, [{"route": "/admin", "type": "dashboard"}])
        _write_maquette(tmp_path, _basic_maquette())

        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is True
        assert (tmp_path / "src" / "schemas" / "admin.json").is_file()

    def test_bootstrap_with_no_dashboard_page_in_plan_gives_clear_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        # Plan has NO dashboard-typed page.
        _write_plan(tmp_path, [{"route": "/notes", "type": "list"}])
        _write_maquette(tmp_path, _basic_maquette())

        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is False
        assert "no dashboard route in plan.pages" in result["reason"]


# ─────────────────────────── flag ON: fallback via completeness ────────


class TestFlagOnFallbackViaCompleteness:
    def test_missing_maquette_triggers_recipe_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # LLM maquette-author failed → no dashboard-maquette.json on disk.
        # Under authority, composer writes a skeleton + invokes
        # dashboard_completeness to top it up.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        _write_plan(tmp_path, [{"route": "/dashboard", "type": "dashboard"}])
        # NO maquette file.

        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is True
        assert "fallback-via-completeness" in result["reason"]
        # Skeleton file exists.
        assert (tmp_path / "src" / "schemas" / "dashboard.json").is_file()

    def test_missing_maquette_no_plan_route_returns_clear_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Fallback can't find a target either → coherent skip diagnostic.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        _write_plan(tmp_path, [{"route": "/notes", "type": "list"}])
        # NO maquette file.

        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is False
        assert "no dashboard route in plan.pages" in result["reason"]
        assert "no maquette on disk" in result["reason"]

    def test_unreadable_maquette_falls_back_when_flag_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        _write_plan(tmp_path, [{"route": "/dashboard", "type": "dashboard"}])
        # Corrupt maquette file.
        (tmp_path / "src" / "contracts").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "contracts" / "dashboard-maquette.json").write_text(
            "not-json", encoding="utf-8",
        )
        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is True
        assert "fallback-via-completeness" in result["reason"]
        assert "maquette unreadable" in result["reason"]

    def test_unreadable_maquette_returns_no_maquette_when_flag_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Regression guard: with flag OFF the legacy fail-closed
        # behaviour is preserved.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")  # explicit opt-out — the flag now defaults ON
        _write_plan(tmp_path, [{"route": "/dashboard", "type": "dashboard"}])
        (tmp_path / "src" / "contracts").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "contracts" / "dashboard-maquette.json").write_text(
            "not-json", encoding="utf-8",
        )
        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"] is False
        assert "maquette unreadable" in result["reason"]

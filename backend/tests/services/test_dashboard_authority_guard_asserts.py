"""Tests for the Phase 3 guard-demotion behaviour.

Under FORGE_DASHBOARD_AUTHORITY, four guards run in ASSERT-only mode
on composer-authored dashboard schemas: they log drift instead of
rewriting. This test suite verifies:

- surface_wrap_guard.wrap_bare_data_displays
- widget_data_source_guard.bind_static_widgets
- chart_data_source_guard.guard_chart_data_sources
- dashboard_completeness.apply_dashboard_completeness

For each guard: (a) with the flag OFF or the composer marker ABSENT,
legacy rewrite behaviour is preserved; (b) with the flag ON AND the
marker present, the schema is left untouched and an assert is logged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.chart_data_source_guard import guard_chart_data_sources
from services.dashboard_completeness import apply_dashboard_completeness
from services.surface_wrap_guard import wrap_bare_data_displays
from services.widget_data_source_guard import bind_static_widgets


# ─────────────────────────── shared helpers ────────────────────────────


def _write_schema(root: Path, slug: str, doc: dict) -> Path:
    p = root / "src" / "schemas" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _composed(schema: dict) -> dict:
    """Stamp the composer marker on a schema so the guards read it as
    composer-authored and switch to assert-only mode."""
    schema.setdefault("meta", {})["maquette_composed"] = True
    return schema


def _bare_data_display_schema(marker: bool = False) -> dict:
    schema = {
        "schemaVersion": "2",
        "id": "dashboard",
        "route": "/dashboard",
        "root": {
            "type": "Stack",
            "children": [
                # Bare Table right under Stack (no Card surface).
                {"type": "Table", "props": {"columns": [], "rows": []}},
            ],
        },
    }
    return _composed(schema) if marker else schema


def _chart_with_literal_data_schema(marker: bool = False) -> dict:
    schema = {
        "schemaVersion": "2",
        "id": "dashboard",
        "route": "/dashboard",
        "root": {
            "type": "Stack",
            "children": [
                # Bare data-shaped Chart the guard would normally convert.
                {"type": "Chart", "props": {
                    "kind": "bar",
                    "data": [{"label": "Jan", "value": 12}],
                }},
            ],
        },
    }
    return _composed(schema) if marker else schema


def _widget_needing_binding_schema(marker: bool = False) -> dict:
    schema = {
        "schemaVersion": "2",
        "id": "dashboard",
        "route": "/dashboard",
        "root": {
            "type": "Stack",
            "children": [
                {"type": "MetricTile", "props": {"label": "Users", "value": "0"}},
            ],
        },
    }
    return _composed(schema) if marker else schema


def _sparse_dashboard_schema(marker: bool = False) -> dict:
    schema = {
        "schemaVersion": "2",
        "id": "dashboard",
        "route": "/dashboard",
        "root": {
            "type": "Stack",
            # single MetricTile → below _MIN_SECTIONS content nodes.
            "children": [
                {"type": "MetricTile", "props": {"label": "Users", "value": "0"}},
            ],
        },
    }
    return _composed(schema) if marker else schema


def _write_plan_with_dashboard(root: Path) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "plan.json").write_text(
        json.dumps({
            "pages": [{"route": "/dashboard", "type": "dashboard"}],
            "entities": {"users": {"fields": [{"name": "email", "type": "text"}]}},
        }),
        encoding="utf-8",
    )


# ─────────────────────────── surface_wrap_guard ────────────────────────


class TestSurfaceWrapGuardAssertMode:
    def test_flag_off_still_rewrites(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")  # explicit opt-out — the flag now defaults ON
        p = _write_schema(tmp_path, "dashboard", _bare_data_display_schema(marker=True))
        result = wrap_bare_data_displays(str(tmp_path))
        # Legacy behaviour: even with the marker, flag OFF means rewrite.
        assert result["wrapped"] > 0
        after = json.loads(p.read_text())
        # Table is now nested under a Card.
        first_child = after["root"]["children"][0]
        assert first_child["type"] == "Card"

    def test_flag_on_no_marker_still_rewrites(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        p = _write_schema(tmp_path, "list", _bare_data_display_schema(marker=False))
        result = wrap_bare_data_displays(str(tmp_path))
        # Non-composer-authored schema still gets rewritten under flag ON.
        assert result["wrapped"] > 0
        after = json.loads(p.read_text())
        assert after["root"]["children"][0]["type"] == "Card"

    def test_flag_on_with_marker_asserts_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        p = _write_schema(tmp_path, "dashboard", _bare_data_display_schema(marker=True))
        before = p.read_text()
        result = wrap_bare_data_displays(str(tmp_path))
        # No mutation; assert logged.
        assert result["wrapped"] == 0
        assert result["asserts_logged"] == 1
        assert p.read_text() == before


# ─────────────────────────── chart_data_source_guard ───────────────────


class TestChartDataSourceGuardAssertMode:
    def test_flag_off_still_converts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")  # explicit opt-out — the flag now defaults ON
        _write_schema(tmp_path, "dashboard", _chart_with_literal_data_schema(marker=True))
        _write_plan_with_dashboard(tmp_path)
        result = guard_chart_data_sources(str(tmp_path))
        # Legacy: with flag off, the marker doesn't stop the conversion.
        # (converted OR skipped will be >0 depending on entity fit — either way
        # NO assert should have been logged.)
        assert result.get("asserts_logged", 0) == 0

    def test_flag_on_with_marker_asserts_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        p = _write_schema(tmp_path, "dashboard", _chart_with_literal_data_schema(marker=True))
        _write_plan_with_dashboard(tmp_path)
        before = p.read_text()
        result = guard_chart_data_sources(str(tmp_path))
        assert result["converted"] == 0
        assert result["asserts_logged"] == 1
        assert p.read_text() == before

    def test_flag_on_no_marker_still_converts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        # No composer marker → legacy conversion runs.
        _write_schema(tmp_path, "dashboard", _chart_with_literal_data_schema(marker=False))
        _write_plan_with_dashboard(tmp_path)
        result = guard_chart_data_sources(str(tmp_path))
        assert result.get("asserts_logged", 0) == 0


# ─────────────────────────── widget_data_source_guard ──────────────────


class TestWidgetDataSourceGuardAssertMode:
    def test_flag_on_with_marker_asserts_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        p = _write_schema(tmp_path, "dashboard", _widget_needing_binding_schema(marker=True))
        _write_plan_with_dashboard(tmp_path)
        before = p.read_text()
        result = bind_static_widgets(str(tmp_path))
        assert result["bound"] == 0
        assert result["asserts_logged"] == 1
        assert p.read_text() == before

    def test_flag_off_still_binds_or_skips_legacy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")  # explicit opt-out — the flag now defaults ON
        _write_schema(tmp_path, "dashboard", _widget_needing_binding_schema(marker=True))
        _write_plan_with_dashboard(tmp_path)
        result = bind_static_widgets(str(tmp_path))
        # Legacy path took over; assert counter untouched.
        assert result.get("asserts_logged", 0) == 0


# ─────────────────────────── dashboard_completeness ───────────────────


class TestDashboardCompletenessAssertMode:
    def test_flag_on_with_marker_asserts_only_no_topup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        p = _write_schema(tmp_path, "dashboard", _sparse_dashboard_schema(marker=True))
        _write_plan_with_dashboard(tmp_path)
        before = p.read_text()
        result = apply_dashboard_completeness(str(tmp_path))
        # No top-up; assert logged for the sparse-but-composer-authored dash.
        assert result["sections_added"] == 0
        assert result["asserts_logged"] == 1
        assert p.read_text() == before

    def test_flag_on_no_marker_takes_legacy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # No composer marker → asserts_logged stays at 0 regardless of
        # whether the legacy top-up ends up adding sections (that depends
        # on the legacy path's own schema-shape heuristics, tested
        # separately in test_dashboard_completeness.py).
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        _write_schema(tmp_path, "dashboard", _sparse_dashboard_schema(marker=False))
        _write_plan_with_dashboard(tmp_path)
        result = apply_dashboard_completeness(str(tmp_path))
        assert result.get("asserts_logged", 0) == 0

    def test_flag_off_ignores_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")  # explicit opt-out — the flag now defaults ON
        _write_schema(tmp_path, "dashboard", _sparse_dashboard_schema(marker=True))
        _write_plan_with_dashboard(tmp_path)
        result = apply_dashboard_completeness(str(tmp_path))
        # Legacy behaviour preserved: no assert path.
        assert result.get("asserts_logged", 0) == 0

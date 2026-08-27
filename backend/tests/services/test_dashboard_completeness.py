"""Tests for services.dashboard_completeness (B-022.10 root fix)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.dashboard_completeness import apply_dashboard_completeness


def _make_app(root: Path, *, plan: dict, schemas: dict[str, dict]) -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))
    for name, doc in schemas.items():
        (root / "src" / "schemas" / f"{name}.json").write_text(json.dumps(doc))


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "src" / "schemas" / f"{name}.json").read_text())


# ---------- bare dashboard gets topped up ---------------------------------

class TestBareDashboardTopUp:
    def test_empty_dashboard_gets_kpi_and_recent(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Recipe": {"fields": []}, "Cook": {"fields": []}},
            "pages": [{"route": "/", "type": "dashboard"}],
        }, schemas={"home": {
            "route": "/",
            "type": "dashboard",
            "nodes": [
                {"type": "Heading", "props": {"content": "Dashboard"}},
            ],
        }})
        r = apply_dashboard_completeness(str(tmp_path))
        assert "home.json" in r["pages_touched"]
        assert r["sections_added"] >= 4
        after = _read(tmp_path, "home")
        types = [n.get("type") for n in after["nodes"]]
        assert "MetricTile" in [
            child["type"]
            for n in after["nodes"] if n.get("type") == "Row"
            for child in n.get("children", [])
        ]
        # Recent items card
        assert any(n.get("type") == "Card" for n in after["nodes"])

    def test_dashboard_with_two_widgets_still_topped_up(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Recipe": {"fields": []}},
            "pages": [{"route": "/", "type": "dashboard"}],
        }, schemas={"home": {
            "route": "/",
            "type": "dashboard",
            "nodes": [
                {"type": "Stat", "props": {"value": 42}},
                {"type": "Chart", "props": {"binding": "{{trends}}"}},
            ],
        }})
        r = apply_dashboard_completeness(str(tmp_path))
        # Two widgets < 3 minimum → top-up
        assert r["sections_added"] > 0

    def test_route_dashboard_alias(self, tmp_path: Path):
        """/dashboard, /home, /overview also count as dashboard pages."""
        _make_app(tmp_path, plan={
            "entities": {"Order": {"fields": []}},
            "pages": [{"route": "/dashboard"}],
        }, schemas={"dashboard": {
            "route": "/dashboard",
            "nodes": [],
        }})
        r = apply_dashboard_completeness(str(tmp_path))
        assert "dashboard.json" in r["pages_touched"]


# ---------- populated dashboards untouched --------------------------------

class TestPopulatedDashboards:
    def test_three_widgets_not_topped_up(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Recipe": {"fields": []}},
            "pages": [{"route": "/", "type": "dashboard"}],
        }, schemas={"home": {
            "route": "/",
            "type": "dashboard",
            "nodes": [
                {"type": "Stat", "props": {}},
                {"type": "Chart", "props": {}},
                {"type": "Table", "props": {}},
            ],
        }})
        r = apply_dashboard_completeness(str(tmp_path))
        assert r["pages_touched"] == []


# ---------- non-dashboard pages untouched ---------------------------------

class TestNonDashboard:
    def test_list_page_untouched(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Recipe": {"fields": []}},
            "pages": [{"route": "/recipes", "type": "list", "entity": "Recipe"}],
        }, schemas={"recipes": {
            "route": "/recipes",
            "type": "list",
            "nodes": [{"type": "Heading", "props": {"content": "Recipes"}}],
        }})
        r = apply_dashboard_completeness(str(tmp_path))
        assert r["pages_touched"] == []


# ---------- idempotency --------------------------------------------------

class TestIdempotency:
    def test_second_run_no_op(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Recipe": {"fields": []}},
            "pages": [{"route": "/", "type": "dashboard"}],
        }, schemas={"home": {
            "route": "/",
            "type": "dashboard",
            "nodes": [{"type": "Heading", "props": {"content": "Dashboard"}}],
        }})
        r1 = apply_dashboard_completeness(str(tmp_path))
        first_touched = r1["sections_added"]
        r2 = apply_dashboard_completeness(str(tmp_path))
        assert r2["sections_added"] == 0
        assert first_touched > 0


# ---------- entity handling ----------------------------------------------

class TestEntityHandling:
    def test_skips_system_entities_for_kpis(self, tmp_path: Path):
        """User / Role / Notification shouldn't be KPI'd."""
        _make_app(tmp_path, plan={
            "entities": {
                "User": {"fields": []},
                "Role": {"fields": []},
                "Recipe": {"fields": []},
            },
            "pages": [{"route": "/", "type": "dashboard"}],
        }, schemas={"home": {"route": "/", "type": "dashboard", "nodes": []}})
        r = apply_dashboard_completeness(str(tmp_path))
        after = _read(tmp_path, "home")
        # Find the KPI row.
        kpi_row = next(
            n for n in after["nodes"]
            if n.get("type") == "Row" and any(
                c.get("type") == "MetricTile" for c in n.get("children", [])
            )
        )
        labels = [c["props"]["label"] for c in kpi_row["children"]]
        assert "Total Recipes" in labels
        assert "Total Users" not in labels
        assert "Total Roles" not in labels

    def test_no_primary_entities_no_op(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"User": {"fields": []}, "Role": {"fields": []}},
            "pages": [{"route": "/", "type": "dashboard"}],
        }, schemas={"home": {"route": "/", "type": "dashboard", "nodes": []}})
        r = apply_dashboard_completeness(str(tmp_path))
        # No primary entities → no KPIs to synthesize → no-op
        assert r["pages_touched"] == []

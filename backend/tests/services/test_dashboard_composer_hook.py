"""Tests for the Spec C Slice 1 C1 pipeline hook — build_dashboard_page
routes through compose_dashboard when page.dashboard_composition is set
AND FORGE_POLISH_DASHBOARD is on.
"""
from __future__ import annotations

import pytest

from services.deterministic_pages import build_dashboard_page


def _minimal_composition() -> dict:
    return {
        "tiles": [
            {"kind": "stat", "label": "Total Widgets", "calc": "count", "entity": "Widget"},
        ],
        "widgets": [],
    }


def _entities() -> dict:
    return {
        "Widget": {"fields": {"id": {}, "name": {}, "status": {}}},
    }


class TestFlagGated:
    def test_flag_off_ignores_composition_falls_through_to_widgets(self, monkeypatch):
        monkeypatch.delenv("FORGE_POLISH_DASHBOARD", raising=False)
        page = {"route": "/dashboard", "dashboard_composition": _minimal_composition()}
        # No `widgets[]` present → the widgets path returns None.
        result = build_dashboard_page(page, registry=_entities(), design_spec=None)
        assert result is None

    def test_flag_on_composition_produces_page(self, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_DASHBOARD", "1")
        page = {"route": "/dashboard", "dashboard_composition": _minimal_composition()}
        result = build_dashboard_page(page, registry=_entities(), design_spec=None)
        assert isinstance(result, dict)
        assert result.get("route") == "/dashboard"
        assert isinstance(result.get("root"), dict)
        assert result["root"].get("type") == "Stack"


class TestBackwardCompat:
    def test_no_composition_field_uses_widgets_path(self, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_DASHBOARD", "1")
        # Page without `dashboard_composition` — flag on doesn't matter,
        # the existing widgets[] path runs unchanged.
        page = {"route": "/dashboard"}
        result = build_dashboard_page(page, registry=_entities(), design_spec=None)
        assert result is None  # no widgets → widgets path returns None (unchanged)

    def test_empty_composition_falls_through(self, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_DASHBOARD", "1")
        page = {"route": "/dashboard", "dashboard_composition": {}}
        result = build_dashboard_page(page, registry=_entities(), design_spec=None)
        # Empty dict is falsy per the guard — fall through.
        assert result is None


class TestFlagValues:
    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_enable(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_POLISH_DASHBOARD", val)
        page = {"route": "/dashboard", "dashboard_composition": _minimal_composition()}
        result = build_dashboard_page(page, registry=_entities(), design_spec=None)
        assert isinstance(result, dict), f"failed for {val!r}"

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_falsy_values_stay_off(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_POLISH_DASHBOARD", val)
        page = {"route": "/dashboard", "dashboard_composition": _minimal_composition()}
        result = build_dashboard_page(page, registry=_entities(), design_spec=None)
        assert result is None, f"leaked for {val!r}"


class TestNoRegression:
    def test_widgets_path_still_works_when_flag_off(self, monkeypatch):
        """The whole point: existing generated apps unchanged."""
        monkeypatch.delenv("FORGE_POLISH_DASHBOARD", raising=False)
        page = {
            "route": "/dashboard",
            "widgets": [
                {"kind": "stat", "label": "Count", "entity": "Widget", "calc": "count"},
            ],
        }
        # Widgets path is the pre-existing behavior — result depends on
        # the existing widgets-path logic; the important guarantee here
        # is: we did NOT throw and we did NOT return the composition
        # branch (which requires the flag).
        # (Either None or dict is acceptable; must not raise.)
        try:
            build_dashboard_page(page, registry=_entities(), design_spec=None)
        except Exception as exc:
            pytest.fail(f"unrelated regression: {exc!r}")

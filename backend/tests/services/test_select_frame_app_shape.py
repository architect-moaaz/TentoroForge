"""Tests for M3-T2: select_frame reads plan.app_shape.layout.shell.

The four-axis substrate's shape.layout.shell has higher priority than
the design_spec nav pref and the IA heuristic; this is the seam that
makes Snap2App-shaped apps stop being wrapped in a sidebar."""
from __future__ import annotations

import pytest

from services.shell_templates import (
    _APP_SHAPE_TO_FRAME,
    _frame_from_app_shape,
    build_shell_deterministic,
    select_frame,
)


NAV_FLOW_WITH_MANY_ITEMS = {
    "pages": [
        {"id": "p1", "route": "/dashboard", "shell": True, "title": "Dashboard"},
        {"id": "p2", "route": "/candidates", "shell": True, "title": "Candidates"},
        {"id": "p3", "route": "/pipeline", "shell": True, "title": "Pipeline"},
        {"id": "p4", "route": "/offers", "shell": True, "title": "Offers"},
        {"id": "p5", "route": "/reports", "shell": True, "title": "Reports"},
        {"id": "p6", "route": "/settings", "shell": True, "title": "Settings"},
        {"id": "p7", "route": "/team", "shell": True, "title": "Team"},
        {"id": "p8", "route": "/audit", "shell": True, "title": "Audit"},
        {"id": "p9", "route": "/roles", "shell": True, "title": "Roles"},
        {"id": "p10", "route": "/reports2", "shell": True, "title": "Reports2"},
    ]
}

NAV_FLOW_SNAP2APP = {
    "pages": [
        {"id": "p1", "route": "/", "shell": True, "title": "Home"},
        {"id": "p2", "route": "/scan", "shell": True, "title": "Scan"},
    ]
}


def _shape(shell_value: str) -> dict:
    return {
        "layout": {
            "shell": shell_value,
            "hero": "none",
            "primaryInteraction": "data-grid",
            "density": "comfortable",
        },
        "auth": {"surface": "route", "gating": "on-load"},
        "nav": {"menu": "sidebar-links", "back": "crumb"},
        "workflows": {"executionMode": "await-with-progress"},
        "data": {"readShape": "list", "denormalization": "moderate"},
        "identity": {"usageMode": "multi-user-team"},
    }


# ══════════════════════════════════════════════════════════════════
# _frame_from_app_shape — the pure translator
# ══════════════════════════════════════════════════════════════════


class TestFrameFromAppShape:
    def test_returns_none_when_plan_missing(self):
        assert _frame_from_app_shape(None) is None
        assert _frame_from_app_shape({}) is None

    def test_returns_none_when_shape_missing(self):
        assert _frame_from_app_shape({"industry": "x"}) is None

    def test_returns_none_when_shell_missing(self):
        assert _frame_from_app_shape({"app_shape": {"auth": {}}}) is None

    def test_translates_all_six_shape_values(self):
        # Every shape.layout.shell value in vocabulary.json maps to a frame.
        for shape_value in ("none", "sidebar", "header", "three-pane", "bottom-tabs", "map-canvas"):
            plan = {"app_shape": _shape(shape_value)}
            got = _frame_from_app_shape(plan)
            assert got is not None, f"{shape_value!r} → no frame"
            assert got == _APP_SHAPE_TO_FRAME[shape_value]

    def test_unknown_shell_value_returns_none(self):
        # An LLM-emitted value not in the vocabulary → falls through to
        # the IA heuristic (silent fallback rather than crash).
        plan = {"app_shape": {"layout": {"shell": "chocolate"}}}
        assert _frame_from_app_shape(plan) is None


# ══════════════════════════════════════════════════════════════════
# select_frame — shape.layout.shell honored above other signals
# ══════════════════════════════════════════════════════════════════


class TestSelectFrameHonorsAppShape:
    def test_shape_none_overrides_ten_items(self):
        plan = {"app_shape": _shape("none"), "pages": []}
        # 10 items → IA heuristic would say "sidebar"; shape wins with "none"
        assert select_frame(plan, NAV_FLOW_WITH_MANY_ITEMS, {}) == "none"

    def test_shape_sidebar_overrides_topbar_pref(self):
        plan = {"app_shape": _shape("sidebar"), "pages": []}
        # design_spec asks for topbar; shape wins with sidebar
        design_spec = {"navigation": "topbar"}
        assert select_frame(plan, NAV_FLOW_SNAP2APP, design_spec) == "sidebar"

    def test_shape_header_maps_to_topbar(self):
        plan = {"app_shape": _shape("header"), "pages": []}
        assert select_frame(plan, NAV_FLOW_WITH_MANY_ITEMS, {}) == "topbar"

    def test_shape_three_pane_maps_to_split(self):
        plan = {"app_shape": _shape("three-pane"), "pages": []}
        assert select_frame(plan, NAV_FLOW_SNAP2APP, {}) == "split"

    def test_shape_map_canvas_maps_to_topbar(self):
        plan = {"app_shape": _shape("map-canvas"), "pages": []}
        assert select_frame(plan, NAV_FLOW_WITH_MANY_ITEMS, {}) == "topbar"

    def test_missing_shape_falls_through_to_heuristic(self):
        # No app_shape → existing IA behavior picks a full-shell frame.
        # The heuristic returns sidebar / rail / split / topbar depending
        # on IA signals — anything but "none" (which only the shape can produce).
        plan_no_shape = {"pages": []}
        got = select_frame(plan_no_shape, NAV_FLOW_WITH_MANY_ITEMS, {})
        assert got in {"sidebar", "rail", "split", "topbar"}
        assert got != "none"

    def test_missing_shape_uses_design_spec_pref(self):
        plan_no_shape = {"pages": []}
        # sidebar-dark → sidebar; existing behavior preserved
        assert select_frame(plan_no_shape, NAV_FLOW_SNAP2APP, {"navigation": "sidebar-dark"}) == "sidebar"


# ══════════════════════════════════════════════════════════════════
# build_shell_deterministic — "none" frame yields passthrough shell
# ══════════════════════════════════════════════════════════════════


class TestBuildShellNone:
    def test_shape_none_yields_passthrough_shell(self):
        plan = {"app_shape": _shape("none"), "pages": []}
        shell = build_shell_deterministic(plan, NAV_FLOW_SNAP2APP)
        assert shell["frame"] == "none"
        # Passthrough shell renders children with no chrome
        assert shell["children"] == [{"type": "Slot", "props": {}}]

    def test_shape_sidebar_yields_sidebar_shell(self):
        plan = {"app_shape": _shape("sidebar"), "pages": []}
        shell = build_shell_deterministic(plan, NAV_FLOW_WITH_MANY_ITEMS)
        assert shell["frame"] == "sidebar"
        # Full shell tree — not the "none" passthrough
        assert shell["children"] != [{"type": "Slot", "props": {}}]

    def test_missing_shape_falls_through_normally(self):
        plan = {"pages": []}
        shell = build_shell_deterministic(plan, NAV_FLOW_WITH_MANY_ITEMS)
        # Whatever IA-derived frame it picks, it's NOT "none"
        assert shell["frame"] != "none"

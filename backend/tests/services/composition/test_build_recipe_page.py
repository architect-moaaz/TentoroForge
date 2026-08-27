"""Slice 4 tests — build_recipe_page emits a valid schemaVersion:"2" tree."""
from __future__ import annotations

from services.composition.build_recipe_page import build_recipe_page


class TestBuildRecipePage:
    def test_unknown_recipe_returns_none(self):
        assert build_recipe_page("/home", "definitely_not_a_recipe") is None

    def test_member_home_emits_page_with_v1_anchor_components(self):
        page = build_recipe_page("/home", "member_home")
        assert page is not None
        assert page["schemaVersion"] == "2"
        assert page["route"] == "/home"
        assert page["layout"] == "main"
        assert page["id"] == "home"
        assert page["meta"]["recipe"] == "member_home"
        assert page["meta"]["category"] == "home"

    def test_member_home_root_is_stack_of_v1_components(self):
        page = build_recipe_page("/dashboard", "member_home")
        assert page is not None
        root = page["root"]
        assert root["type"] == "Stack"
        child_types = [c["type"] for c in root["children"]]
        # v1 anchors implemented in Slice 2 — all six should be present.
        assert child_types == [
            "PinnedMomentHero",
            "VitalsInContext",
            "ScanStrip",
            "RecsRailReasoned",
            "CommunityPulse",
            "StickyPrimaryCta",
        ]

    def test_route_id_normalisation(self):
        page = build_recipe_page("/", "member_home")
        assert page is not None and page["id"] == "home"
        page2 = build_recipe_page("/dashboard/member", "member_home")
        assert page2 is not None and page2["id"] == "dashboard_member"

    def test_unresolved_anchors_returns_none(self):
        # A recipe whose anchors have no `component` field yet → recipe skips.
        # `operator_console` in Slice 2 has NO v1-implemented components.
        page = build_recipe_page("/ops", "citizen_service")
        assert page is None  # Nothing to render yet — caller falls back.

    def test_every_child_has_props_dict(self):
        page = build_recipe_page("/home", "member_home")
        assert page is not None
        for child in page["root"]["children"]:
            assert isinstance(child.get("props"), dict)

    def test_custom_layout_id(self):
        page = build_recipe_page("/home", "member_home", layout="app-shell")
        assert page is not None
        assert page["layout"] == "app-shell"

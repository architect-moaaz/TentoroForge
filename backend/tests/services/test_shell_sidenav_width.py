"""Tests for the content-fit expandedWidth computation on SideNav.

Locks the sizing contract so a long menu label doesn't silently
truncate to an ellipsis. Independent of the library's runtime — pure
arithmetic against the label set.
"""
from __future__ import annotations

from services.shell_templates import _expanded_width_for, _widest_label


class TestWidestLabel:
    def test_finds_top_level_group_label(self):
        groups = [{"label": "Recruitment", "items": []}]
        assert _widest_label(groups) == "Recruitment"

    def test_finds_nested_item_label(self):
        groups = [{"label": "Ops", "items": [
            {"label": "Front-Desk Staff Availability"},
        ]}]
        assert _widest_label(groups) == "Front-Desk Staff Availability"

    def test_finds_sub_item_label(self):
        groups = [{"label": "X", "items": [
            {"label": "Y", "items": [
                {"label": "A very deeply nested and long label"},
            ]},
        ]}]
        assert _widest_label(groups) == "A very deeply nested and long label"

    def test_empty_groups_returns_empty(self):
        assert _widest_label([]) == ""

    def test_tolerates_malformed_group(self):
        # Not a dict, has no items, missing labels — never raises.
        assert _widest_label([None, "string", {"noise": True}]) == ""


class TestExpandedWidthFor:
    def test_short_labels_get_library_default(self):
        groups = [{"label": "Home"}, {"label": "Users"}]
        # A 5-char label → base 80 + 5*8.4 = 122 → clamped up to 236.
        assert _expanded_width_for(groups, "App") == 236

    def test_medium_label_gets_content_fit(self):
        # ~24 chars — should sit above 236, below 320.
        groups = [{"label": "Recruitment Pipeline"}]
        w = _expanded_width_for(groups, "App")
        assert 236 <= w <= 320
        # Concretely: 80 + 20*8.4 ≈ 248 → not clamped.
        assert w == 248

    def test_long_label_clamps_at_ceiling(self):
        # 60-char label would want 80 + 60*8.4 = 584px. Clamp to 320.
        groups = [{"label": "A very long menu label that goes on and on and on and…"}]
        assert _expanded_width_for(groups, "App") == 320

    def test_app_name_considered_when_wider_than_menu(self):
        # Brand name is what shows in the header of the rail — if it's
        # the widest string, it still drives the sizing.
        groups = [{"label": "Home"}]
        w = _expanded_width_for(groups, "Comprehensive Recruitment Platform")
        assert w > 236

    def test_never_below_library_default(self):
        # Sanity: even empty groups + short app name → default 236.
        assert _expanded_width_for([], "") == 236

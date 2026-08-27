"""A widget's slot must fit what the widget actually holds.

Three symptoms on opmk18qr /dashboard, one cause: the composer lays every
section out as an equal-width Grid without asking what goes in the cells.

  • BLEEDING — "Pending Leave by Department" is a 3-column table and
    "Approvals Due Today" a 4-column one, each in a third of the width. The
    header reads "AVG DURATION (DAY" and "Dates"/"Status" are cut off. The
    scroll box contains it, so the card no longer widens, but a column sliced
    mid-word still reads as broken.

  • WHITE SPACE — "Trends & Activity" is Chart | Gauge | ActivityFeed. The
    feed renders ten rows and is roughly twice the height of its neighbours,
    so the row is as tall as the feed and two thirds of it is empty.

Grid rows are as tall as their tallest child and as wide as their narrowest
column, so an unbounded list and a wide table are the two ways to wreck one.
"""
from services.dashboard_slot_fit import (
    columns_that_fit, row_cap_for, fit_dashboard_slots, widget_min_columns,
)


class TestHowMuchWidthAWidgetNeeds:
    def test_a_wide_table_needs_more_than_a_third(self):
        table = {"type": "Table", "props": {"columns": [1, 2, 3, 4]}}
        assert widget_min_columns(table) >= 2

    def test_a_two_column_table_is_content_in_a_third(self):
        table = {"type": "Table", "props": {"columns": [1, 2]}}
        assert widget_min_columns(table) == 1

    def test_a_chart_or_gauge_is_happy_narrow(self):
        for t in ("Chart", "Gauge", "MetricTile"):
            assert widget_min_columns({"type": t, "props": {}}) == 1


class TestChoosingTheGridsColumnCount:
    def test_a_three_up_row_holding_a_wide_table_drops_to_two(self):
        kids = [{"type": "Chart"}, {"type": "Table", "props": {"columns": [1, 2, 3, 4]}}]
        assert columns_that_fit(3, kids) == 2

    def test_a_row_of_narrow_widgets_keeps_its_three(self):
        kids = [{"type": "Chart"}, {"type": "Gauge"}, {"type": "MetricTile"}]
        assert columns_that_fit(3, kids) == 3

    def test_it_never_widens_a_grid_the_author_made_narrow(self):
        kids = [{"type": "Table", "props": {"columns": [1, 2, 3, 4]}}]
        assert columns_that_fit(1, kids) == 1

    def test_it_never_returns_less_than_one(self):
        assert columns_that_fit(2, [{"type": "Table", "props": {"columns": list(range(9))}}]) >= 1


class TestCappingAListThatWouldTowerOverItsNeighbours:
    def test_a_feed_beside_other_widgets_is_capped(self):
        assert row_cap_for({"type": "ActivityFeed", "props": {}}, columns=3) == 5

    def test_a_list_beside_other_widgets_is_capped(self):
        assert row_cap_for({"type": "List", "props": {}}, columns=2) == 5

    def test_a_full_width_feed_is_left_alone(self):
        # Nothing sits beside it, so its height stands for nothing to strand.
        assert row_cap_for({"type": "ActivityFeed", "props": {}}, columns=1) is None

    def test_an_author_declared_limit_is_respected(self):
        feed = {"type": "ActivityFeed", "props": {"limit": 3}}
        assert row_cap_for(feed, columns=3) is None

    def test_a_chart_has_no_row_cap(self):
        assert row_cap_for({"type": "Chart", "props": {}}, columns=3) is None


class TestFittingAWholePage:
    def _page(self):
        return {"root": {"type": "Stack", "children": [
            {"type": "Section", "props": {"title": "Trends & Activity"}, "children": [
                {"type": "Grid", "props": {"columns": 3}, "children": [
                    {"type": "Card", "children": [{"type": "Chart", "props": {}}]},
                    {"type": "Card", "children": [{"type": "Gauge", "props": {}}]},
                    {"type": "Card", "children": [
                        {"type": "ActivityFeed", "props": {"entries": "{{notifications}}"}}]},
                ]},
            ]},
            {"type": "Section", "props": {"title": "Leave Overview"}, "children": [
                {"type": "Grid", "props": {"columns": 3}, "children": [
                    {"type": "Card", "children": [
                        {"type": "Table", "props": {"columns": [1, 2, 3]}}]},
                    {"type": "Card", "children": [
                        {"type": "Table", "props": {"columns": [1, 2, 3, 4]}}]},
                ]},
            ]},
        ]}}

    def test_the_wide_table_row_narrows(self):
        page = self._page()
        fit_dashboard_slots(page)
        overview = page["root"]["children"][1]["children"][0]
        assert overview["props"]["columns"] == 2

    def test_the_feed_gets_a_row_cap(self):
        page = self._page()
        fit_dashboard_slots(page)
        feed = page["root"]["children"][0]["children"][0]["children"][2]["children"][0]
        assert feed["props"]["limit"] == 5

    def test_the_chart_row_keeps_its_three_columns(self):
        page = self._page()
        fit_dashboard_slots(page)
        trends = page["root"]["children"][0]["children"][0]
        assert trends["props"]["columns"] == 3

    def test_it_is_idempotent(self):
        page = self._page()
        fit_dashboard_slots(page)
        assert fit_dashboard_slots(page)["changed"] == 0

    def test_it_says_what_it_did(self):
        page = self._page()
        report = fit_dashboard_slots(page)
        assert report["changed"] >= 2
        assert any("Table" in n or "column" in n for n in report["notes"])

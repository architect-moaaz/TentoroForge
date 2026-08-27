"""A KPI may not be formatted as something its own metric cannot be.

Live on opmk18qr: a tile labelled "Utilization Rate" carried
``format: "percent"`` while its dataSource was ``{"fn": "count"}`` over
LeaveBalance. The count was 10 rows; the percent formatter multiplied by 100
and the dashboard reported **1,000%**. Nothing was broken in the formatter —
it faithfully rendered a count as a ratio, because nobody checked that a
count can never *be* a ratio.

The rule is a type statement, not a heuristic: count / sum / max produce a
magnitude, and a magnitude formatted as a percent is a fabricated number.
"""
from services.kpi_format_honesty import honest_format, reconcile_kpi_formats


class TestTheFormatAKpiIsAllowedToClaim:
    def test_a_count_is_never_a_percent(self):
        assert honest_format("percent", "count") == "number"

    def test_a_sum_is_never_a_percent(self):
        assert honest_format("percent", "sum") == "number"

    def test_a_max_is_never_a_percent(self):
        assert honest_format("percent", "max") == "number"

    def test_an_average_may_be_a_percent(self):
        # avg over a rate/boolean column is a genuine ratio — left alone.
        assert honest_format("percent", "avg") == "percent"

    def test_a_declared_ratio_op_may_be_a_percent(self):
        assert honest_format("percent", "ratio") == "percent"

    def test_every_other_format_passes_through_untouched(self):
        for fmt in ("number", "currency", "duration"):
            for op in ("count", "sum", "avg", "max"):
                assert honest_format(fmt, op) == fmt

    def test_an_unknown_op_is_left_alone_rather_than_guessed_at(self):
        # Silence beats a confident wrong demotion: an op this module does not
        # model may well be a ratio.
        assert honest_format("percent", "median") == "percent"
        assert honest_format("percent", "") == "percent"


class TestReconcilingAWholePage:
    def _page(self, fmt, fn):
        return {
            "root": {"children": [
                {"type": "MetricTile", "props": {
                    "label": "Utilization Rate",
                    "value": "{{utilizationrate.value}}", "format": fmt}},
            ]},
            "dataSources": [
                {"name": "utilizationrate", "op": "aggregate",
                 "metrics": {"value": {"fn": fn}}},
            ],
        }

    def test_it_demotes_the_live_defect(self):
        page = self._page("percent", "count")
        report = reconcile_kpi_formats(page)
        tile = page["root"]["children"][0]
        assert tile["props"]["format"] == "number"
        assert report["changed"] == 1

    def test_it_leaves_an_honest_percent_alone(self):
        page = self._page("percent", "avg")
        assert reconcile_kpi_formats(page)["changed"] == 0
        assert page["root"]["children"][0]["props"]["format"] == "percent"

    def test_it_is_idempotent(self):
        page = self._page("percent", "count")
        reconcile_kpi_formats(page)
        assert reconcile_kpi_formats(page)["changed"] == 0

    def test_a_tile_whose_source_it_cannot_find_is_left_alone(self):
        page = self._page("percent", "count")
        page["dataSources"] = []
        assert reconcile_kpi_formats(page)["changed"] == 0

    def test_it_reports_what_it_changed_for_the_build_log(self):
        page = self._page("percent", "count")
        report = reconcile_kpi_formats(page)
        assert "Utilization Rate" in str(report["notes"])
        assert "count" in str(report["notes"])

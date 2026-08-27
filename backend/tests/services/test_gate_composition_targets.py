"""Density stops being a side effect only when something checks it.

Nothing in the pipeline had an opinion about how MUCH belongs on a page. The
maquette author picked columns from whatever the entity happened to carry, the
vocabulary spoke about shape but never amount, and the delivery gate checked
plan↔artifact symmetry — so a six-column entity produced a six-column table
and nobody could say whether that was rich or thin. It wasn't a decision; it
was arithmetic on the schema.

The montage now sets a bar (``columns_target``, ``kpis_target``). This rule
reads it back off the shipped pages, which is what makes the bar real rather
than advisory.

Deliberately ``warn``, never ``error``: an entity with five columns cannot
honour a bar of eight, and that is a legitimate shortfall, not a defect. The
gate's job here is to make the gap visible — silence was the actual bug.
"""
from __future__ import annotations

from services.delivery_gate import check_composition_targets

_TARGETS = {"collection": {"shape": "table", "columns_target": 8},
            "dashboard": {"kpis_target": 4}}


def _table(n_cols: int) -> dict:
    return {"type": "Table",
            "props": {"columns": [{"key": f"c{i}"} for i in range(n_cols)]}}


def _dashboard(n_tiles: int) -> dict:
    return {"type": "Stack",
            "children": [{"type": "MetricTile", "props": {"label": f"m{i}"}}
                         for i in range(n_tiles)]}


class TestAShortfallIsSurfaced:
    def test_a_thin_table_warns(self):
        vs = check_composition_targets(_TARGETS, [("/conferences", _table(4))],
                                       {"/conferences": "collection"})
        assert len(vs) == 1
        assert vs[0].severity == "warn"
        assert "4" in vs[0].msg and "8" in vs[0].msg

    def test_a_thin_dashboard_warns(self):
        vs = check_composition_targets(_TARGETS, [("/", _dashboard(2))],
                                       {"/": "dashboard"})
        assert len(vs) == 1
        assert "kpi" in vs[0].rule.lower() or "kpi" in vs[0].msg.lower()

    def test_the_violation_names_a_repair_seam(self):
        """A gate finding nobody can act on is noise."""
        vs = check_composition_targets(_TARGETS, [("/conferences", _table(4))],
                                       {"/conferences": "collection"})
        assert vs[0].repair_hint


class TestMeetingTheBarIsSilent:
    def test_an_exact_hit_passes(self):
        assert check_composition_targets(
            _TARGETS, [("/conferences", _table(8))],
            {"/conferences": "collection"}) == []

    def test_exceeding_the_bar_passes(self):
        """The target is a floor, not a ceiling."""
        assert check_composition_targets(
            _TARGETS, [("/conferences", _table(11))],
            {"/conferences": "collection"}) == []


class TestNoBarMeansNoOpinion:
    def test_no_montage_yields_no_violations(self):
        assert check_composition_targets({}, [("/conferences", _table(2))],
                                         {"/conferences": "collection"}) == []

    def test_a_kind_without_a_target_is_ignored(self):
        assert check_composition_targets(
            {"dashboard": {"kpis_target": 4}}, [("/conferences", _table(2))],
            {"/conferences": "collection"}) == []

    def test_a_page_of_unknown_kind_is_ignored(self):
        assert check_composition_targets(_TARGETS, [("/x", _table(2))], {}) == []


class TestItNeverJudgesWhatItCannotMeasure:
    def test_a_collection_with_no_table_is_not_a_shortfall(self):
        """A kanban or card-list carries no columns; absence is not thinness."""
        kanban = {"type": "Kanban", "props": {"groupBy": "status"}}
        assert check_composition_targets(_TARGETS, [("/c", kanban)],
                                         {"/c": "collection"}) == []

    def test_malformed_columns_do_not_raise(self):
        broken = {"type": "Table", "props": {"columns": "not-a-list"}}
        assert check_composition_targets(_TARGETS, [("/c", broken)],
                                         {"/c": "collection"}) == []


# ── Plan vocabulary vs montage vocabulary ───────────────────────────────
# The montage layer names screen kinds `dashboard | collection | record`.
# The planner names the same pages `dashboard | list | detail`. The rule
# keyed on the montage words, so on a real build every one of the thirteen
# `list` pages was invisible to it: eight tables shipped under the seven-
# column bar and the gate reported nothing. Only the dashboard — the one
# kind whose name happens to match — produced a finding.

class TestPlanKindsAreUnderstood:
    _T = {"collection": {"columns_target": 7}, "record": {"fields_target": 9}}

    def _thin_table(self):
        return {"type": "Table", "props": {"columns": [{"key": f"c{i}"} for i in range(5)]}}

    def test_a_plan_typed_list_is_judged_as_a_collection(self):
        vs = check_composition_targets(self._T, [("/bills", self._thin_table())],
                                       {"/bills": "list"})
        assert len(vs) == 1 and "5" in vs[0].msg and "7" in vs[0].msg

    def test_the_montage_word_still_works(self):
        assert len(check_composition_targets(
            self._T, [("/bills", self._thin_table())], {"/bills": "collection"})) == 1

    def test_index_and_table_are_collections_too(self):
        for word in ("index", "table"):
            assert len(check_composition_targets(
                self._T, [("/b", self._thin_table())], {"/b": word})) == 1, word

    def test_a_form_page_is_not_a_collection(self):
        assert check_composition_targets(
            self._T, [("/bills/new", self._thin_table())], {"/bills/new": "form"}) == []

    def test_overview_and_home_count_as_dashboards(self):
        tiles = {"type": "Stack", "children": [{"type": "MetricTile"} for _ in range(2)]}
        for word in ("overview", "home", "admin"):
            assert len(check_composition_targets(
                {"dashboard": {"kpis_target": 5}}, [("/x", tiles)], {"/x": word})) == 1, word

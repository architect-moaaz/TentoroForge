"""Turn a vision critique into findings the pipeline can actually act on.

Fidelity scoring produced prose ("cards lack elevation") which routed
nowhere. These tests pin the contract that makes it routable: typed
findings, split by whether they are safe to repair per-phase.
"""
import pytest

from services.visual_findings import (
    GLOBAL_TYPES,
    PAGE_TYPES,
    parse_findings,
    partition,
    route_visual_findings,
)


class TestParse:
    def test_maps_a_vision_finding_to_a_typed_record(self):
        out = parse_findings(
            {"findings": [{"type": "density_off", "detail": "rows are cramped"}]},
            route="/products",
        )
        assert out == [{
            "type": "density_off", "route": "/products",
            "detail": "rows are cramped", "source": "fidelity",
        }]

    def test_drops_types_no_seam_can_fix(self):
        # A vision model will invent categories. Anything without a fixer is
        # dropped here rather than surfaced as an unactionable "finding".
        out = parse_findings(
            {"findings": [{"type": "vibes_wrong", "detail": "feels corporate"}]},
            route="/products",
        )
        assert out == []

    def test_tolerates_a_scorer_that_returned_only_prose(self):
        # The old shape — no findings key at all. Must not raise.
        assert parse_findings({"qualitative_notes": "looks fine"}, route="/x") == []
        assert parse_findings({}, route="/x") == []
        assert parse_findings(None, route="/x") == []

    def test_ignores_malformed_entries_without_losing_the_good_ones(self):
        out = parse_findings(
            {"findings": [
                "not a dict",
                {"no_type": 1},
                {"type": "bare_surface", "detail": "table sits on the page"},
            ]},
            route="/orders",
        )
        assert [f["type"] for f in out] == ["bare_surface"]

    def test_detail_is_optional(self):
        out = parse_findings({"findings": [{"type": "weak_hierarchy"}]}, route="/x")
        assert out[0]["detail"] == ""


class TestPartition:
    def test_splits_page_scoped_from_global(self):
        page, glob = partition([
            {"type": "density_off",      "route": "/a"},
            {"type": "palette_mismatch", "route": "/a"},
            {"type": "bare_surface",     "route": "/b"},
            {"type": "type_scale_off",   "route": "/b"},
        ])
        assert [f["type"] for f in page] == ["density_off", "bare_surface"]
        assert [f["type"] for f in glob] == ["palette_mismatch", "type_scale_off"]

    def test_the_two_sets_are_disjoint_and_cover_everything_parseable(self):
        # If a type were in both, partition would double-report it; if in
        # neither, parse_findings would have dropped it. This is the invariant
        # that keeps the taxonomy honest as it grows.
        assert PAGE_TYPES & GLOBAL_TYPES == set()

    def test_global_findings_are_never_repaired_per_phase(self):
        # `design` runs once. Repairing palette mid-build repaints features
        # the user already reviewed — so global findings must fall out of the
        # per-phase repair path entirely.
        page, glob = partition([{"type": "palette_mismatch", "route": "/a"}])
        assert page == []
        assert len(glob) == 1


class TestRouting:
    def test_runs_only_the_fixers_the_findings_call_for(self):
        # A page critiqued for density must not trigger the hierarchy pass —
        # every extra pass is another chance to churn a page nobody complained
        # about.
        ran = []
        fixers = {
            "density_off":    lambda d: (ran.append("density"), 2)[1],
            "bare_surface":   lambda d: (ran.append("surface"), 0)[1],
            "weak_hierarchy": lambda d: (ran.append("anatomy"), 0)[1],
        }
        out = route_visual_findings(
            "/tmp/app", [{"type": "density_off", "route": "/a"}], fixers=fixers)
        assert ran == ["density"]
        assert out["fixed"] == 2
        assert out["made_progress"] is True

    def test_each_fixer_runs_once_even_for_many_pages(self):
        # The passes are app-wide and idempotent; running one per finding
        # would be pure waste.
        calls = []
        fixers = {"density_off": lambda d: (calls.append(d), 1)[1]}
        route_visual_findings("/tmp/app", [
            {"type": "density_off", "route": "/a"},
            {"type": "density_off", "route": "/b"},
            {"type": "density_off", "route": "/c"},
        ], fixers=fixers)
        assert len(calls) == 1

    def test_a_type_with_no_seam_is_reported_unhandled_not_fixed(self):
        # flat_composition has no repair pass today — composition_recipes
        # selects, it does not retrofit. Claiming it fixed would make the
        # report lie.
        out = route_visual_findings(
            "/tmp/app", [{"type": "flat_composition", "route": "/a"}], fixers={})
        assert out["fixed"] == 0
        assert out["made_progress"] is False
        assert [f["type"] for f in out["unhandled"]] == ["flat_composition"]

    def test_global_findings_are_refused_by_the_repair_path(self):
        out = route_visual_findings(
            "/tmp/app", [{"type": "palette_mismatch", "route": "/a"}], fixers={})
        assert out["fixed"] == 0
        assert [f["type"] for f in out["unhandled"]] == ["palette_mismatch"]

    def test_a_failing_fixer_does_not_abort_the_others(self):
        def boom(_d):
            raise RuntimeError("guard blew up")
        out = route_visual_findings("/tmp/app", [
            {"type": "density_off",  "route": "/a"},
            {"type": "bare_surface", "route": "/a"},
        ], fixers={"density_off": boom, "bare_surface": lambda d: 3})
        assert out["fixed"] == 3
        assert [f["type"] for f in out["unhandled"]] == ["density_off"]

    def test_nothing_to_do_is_not_progress(self):
        out = route_visual_findings("/tmp/app", [], fixers={})
        assert out == {"fixed": 0, "ran": [], "unhandled": [],
                       "made_progress": False}

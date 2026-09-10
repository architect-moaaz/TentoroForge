"""Tests for the read-only app scoreboard.

The scoreboard's whole value is that its numbers can be trusted enough
to delete pipeline layers on the strength of them. So these tests care
most about the ways a scorer can lie: crediting a metric it didn't
measure, punishing an app for something that isn't its fault, and
silently scoring 100% because the denominator was zero.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import scoreboard as sb


# ── fixtures ────────────────────────────────────────────────────────

def _app(tmp_path: Path, *, plan: dict, schemas: dict[str, dict],
         shell: dict | None = None) -> Path:
    root = tmp_path / "app"
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    for slug, doc in schemas.items():
        p = root / "src" / "schemas" / f"{slug}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc), encoding="utf-8")
    if shell is not None:
        (root / "src" / "schemas" / "shell.json").write_text(json.dumps(shell), encoding="utf-8")
    return root


def _menu(*routes: str) -> dict:
    return {"type": "Shell", "children": [
        {"type": "NavLink", "props": {"href": r, "label": r}} for r in routes
    ]}


# ── the zero-denominator trap ───────────────────────────────────────

class TestEmptyDenominators:
    def test_metric_with_no_denominator_is_none_not_one(self):
        """An app with no forms must not score 100% on forms."""
        m = sb.Metric(ok=0, total=0)
        assert m.rate is None

    def test_composite_excludes_undefined_metrics(self):
        metrics = {"a": sb.Metric(1, 1), "b": sb.Metric(0, 0)}
        # 1.0 from 'a' only — 'b' must not drag it to 0.5 nor lift to 1.0
        assert sb._composite(metrics) == pytest.approx(1.0)

    def test_composite_is_none_when_nothing_measurable(self):
        assert sb._composite({"a": sb.Metric(0, 0)}) is None


# ── route comparison ────────────────────────────────────────────────

class TestRouteMatching:
    def test_dynamic_segment_matches_concrete_path(self):
        shipped = {"/bills/*"}
        assert sb._route_exists("/bills/42", shipped)
        assert sb._route_exists("/bills/[id]", shipped)

    def test_unrelated_route_does_not_match(self):
        assert not sb._route_exists("/invoices/42", {"/bills/*"})

    def test_deeper_path_is_served_by_catch_all_parent(self):
        assert sb._route_exists("/bills/42/history", {"/bills/*"})

    def test_trailing_slash_is_not_a_different_route(self):
        assert sb._route_exists("/bills/", {"/bills"})


class TestCaseDupes:
    def test_entity_cased_twin_is_flagged(self):
        dupes = sb._case_dupes({"/bills/new", "/Bill/new"})
        assert dupes == {"/Bill/new"}

    def test_no_twin_means_no_dupe(self):
        """A PascalCase route with no slug sibling is a real route, not junk."""
        assert sb._case_dupes({"/Bill/new"}) == set()

    def test_all_lowercase_never_flags(self):
        assert sb._case_dupes({"/bills", "/bills/new"}) == set()


# ── the metrics, end to end ─────────────────────────────────────────

class TestScoring:
    def test_planned_page_that_never_shipped_fails_coverage(self, tmp_path):
        root = _app(
            tmp_path,
            plan={"pages": [{"route": "/bills"}, {"route": "/ghost"}]},
            schemas={"bills": {"root": {"type": "Stack"}}},
            shell=_menu("/bills"),
        )
        s = sb.score_app(root)
        assert s.metrics["coverage"].ok == 1
        assert s.metrics["coverage"].total == 2
        assert any("ghost" in f for f in s.metrics["coverage"].failures)

    def test_route_absent_from_menu_fails_reach(self, tmp_path):
        root = _app(
            tmp_path,
            plan={"pages": [{"route": "/bills"}, {"route": "/orphan"}]},
            schemas={"bills": {"root": {}}, "orphan": {"root": {}}},
            shell=_menu("/bills"),
        )
        s = sb.score_app(root)
        assert any("/orphan" in f for f in s.metrics["reach"].failures)

    def test_child_route_is_reachable_via_its_parent(self, tmp_path):
        """/bills/new is reached from a button on /bills, not the menu."""
        root = _app(
            tmp_path,
            plan={"pages": [{"route": "/bills"}]},
            schemas={"bills": {"root": {}}, "bills/new": {"root": {}}},
            shell=_menu("/bills"),
        )
        s = sb.score_app(root)
        assert not any("/bills/new" in f for f in s.metrics["reach"].failures)

    def test_auth_routes_are_not_counted_unreachable(self, tmp_path):
        root = _app(
            tmp_path,
            plan={"pages": [{"route": "/bills"}]},
            schemas={"bills": {"root": {}}, "login": {"root": {}}},
            shell=_menu("/bills"),
        )
        s = sb.score_app(root)
        assert not any("login" in f for f in s.metrics["reach"].failures)

    def test_case_dupe_is_reported_but_not_scored_as_unreachable(self, tmp_path):
        root = _app(
            tmp_path,
            plan={"pages": [{"route": "/bills"}]},
            schemas={"bills": {"root": {}}, "bills/new": {"root": {}},
                     "Bill/new": {"root": {}}},
            shell=_menu("/bills"),
        )
        s = sb.score_app(root)
        assert s.dupe_routes == 1
        assert not any("/Bill/new" in f for f in s.metrics["reach"].failures)


# ── failure modes that must never crash ─────────────────────────────

class TestTolerance:
    def test_missing_plan_scores_none_without_raising(self, tmp_path):
        (tmp_path / "empty").mkdir()
        s = sb.score_app(tmp_path / "empty")
        assert s.composite is None
        assert "plan" in s.note

    def test_corrupt_plan_is_treated_as_missing(self, tmp_path):
        root = tmp_path / "app"
        (root / "src" / "contracts").mkdir(parents=True)
        (root / "src" / "contracts" / "plan.json").write_text("{not json", encoding="utf-8")
        s = sb.score_app(root)
        assert s.composite is None

    def test_plan_with_no_schemas_is_noted(self, tmp_path):
        root = tmp_path / "app"
        (root / "src" / "contracts").mkdir(parents=True)
        (root / "src" / "contracts" / "plan.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
        s = sb.score_app(root)
        assert "no page schemas" in s.note

    def test_missing_shell_does_not_crash(self, tmp_path):
        root = _app(tmp_path, plan={"pages": [{"route": "/bills"}]},
                    schemas={"bills": {"root": {}}}, shell=None)
        s = sb.score_app(root)          # no shell.json at all
        assert s.metrics["reach"].total >= 1


# ── reporting ───────────────────────────────────────────────────────

class TestReporting:
    def test_pooled_row_sums_counts_not_rates(self):
        """One 100-button app at 50% must outweigh one 2-button app at 100%."""
        a = sb.AppScore("big", {m: sb.Metric() for m in sb.METRICS}, 0.5)
        a.metrics["wired"] = sb.Metric(ok=50, total=100)
        b = sb.AppScore("small", {m: sb.Metric() for m in sb.METRICS}, 1.0)
        b.metrics["wired"] = sb.Metric(ok=2, total=2)
        out = sb.render_table([a, b])
        pooled = [l for l in out.splitlines() if l.startswith("POOLED")][0]
        # 52/102 ≈ 51.0%, NOT the 75% a naive mean of rates would give
        assert "51.0" in pooled

    def test_table_renders_with_undefined_metrics(self):
        s = sb.AppScore("x", {m: sb.Metric() for m in sb.METRICS}, None)
        assert "x" in sb.render_table([s])

    def test_failure_shapes_cluster_across_apps(self):
        a = sb.AppScore("a", {m: sb.Metric() for m in sb.METRICS}, 1.0)
        a.metrics["wired"].failures = ["/bills: 'New Bill' has no action"]
        b = sb.AppScore("b", {m: sb.Metric() for m in sb.METRICS}, 1.0)
        b.metrics["wired"].failures = ["/orders: 'New Order' has no action"]
        out = sb.top_failures([a, b])
        # Both collapse to the same shape and count 2, not two shapes of 1
        assert "2  wired: /X: 'X' has no action" in out


# ── the guarantee that keeps this out of the pipeline ───────────────

def test_scoreboard_is_not_imported_by_generation():
    """If a service ever imports this, it has become a pipeline stage."""
    import subprocess
    out = subprocess.run(
        ["grep", "-rl", "tools.scoreboard", "services", "agents", "routers"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2],
    )
    assert out.stdout.strip() == "", f"scoreboard imported by: {out.stdout}"


def test_scoreboard_never_writes_to_the_app(tmp_path):
    """Scoring must leave the app byte-identical."""
    root = _app(tmp_path, plan={"pages": [{"route": "/bills"}]},
                schemas={"bills": {"root": {}}}, shell=_menu("/bills"))
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    sb.score_app(root)
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after

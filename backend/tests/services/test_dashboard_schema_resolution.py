"""The landing dashboard must resolve to the file that actually holds it.

`_route_to_slug` mapped the root route `/` to the single candidate
`dashboard.json`. Real pipelines write the landing page as `home.json`, so
`/` could never resolve — and because the resolver keeps walking the route
list on a miss, it fell through to a *different* dashboard-typed page.

On x4fcmdyi that meant the landing maquette (4 KPIs, a primary chart, an
activity feed, a personalised-greeting hero) resolved to `/analytics`, and
the actual landing page `home.json` was left to a completeness guard: three
bare tiles and a table. The montage reached the maquette author intact and
was then dropped on the floor one step later.

Root is the only route with this ambiguity — every other route names its own
file — so the fix is a candidate list for `/`, and a miss must not silently
promote a lower-priority route.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.apply_dashboard_maquette import _find_dashboard_schema


def _tree(tmp: Path, schema_files: list[str], pages: list[dict]) -> Path:
    root = tmp / "app"
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    for name in schema_files:
        p = root / "src" / "schemas" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"root": {"type": "Stack"}}), encoding="utf-8")
    (root / "src" / "contracts" / "plan.json").write_text(
        json.dumps({"pages": pages}), encoding="utf-8")
    return root


class TestRootResolvesToItsRealFile:
    def test_root_route_finds_home_json(self, tmp_path):
        """The live shape: plan says "/" is the dashboard, file is home.json."""
        root = _tree(tmp_path, ["home.json", "analytics.json"],
                     [{"route": "/", "type": "dashboard"},
                      {"route": "/analytics", "type": "dashboard"}])
        assert _find_dashboard_schema(root).name == "home.json"

    def test_root_still_finds_dashboard_json_when_that_is_the_name(self, tmp_path):
        root = _tree(tmp_path, ["dashboard.json", "analytics.json"],
                     [{"route": "/", "type": "dashboard"},
                      {"route": "/analytics", "type": "dashboard"}])
        assert _find_dashboard_schema(root).name == "dashboard.json"

    def test_root_falls_back_to_index_json(self, tmp_path):
        root = _tree(tmp_path, ["index.json"], [{"route": "/", "type": "dashboard"}])
        assert _find_dashboard_schema(root).name == "index.json"

    def test_dashboard_json_wins_over_home_when_both_exist(self, tmp_path):
        """Deterministic order — not whichever the filesystem lists first."""
        root = _tree(tmp_path, ["home.json", "dashboard.json"],
                     [{"route": "/", "type": "dashboard"}])
        assert _find_dashboard_schema(root).name == "dashboard.json"


class TestTheLandingRouteIsNotSkipped:
    def test_a_named_landing_route_still_beats_a_later_dashboard(self, tmp_path):
        """/dashboard outranks /analytics — unchanged behaviour."""
        root = _tree(tmp_path, ["dashboard.json", "analytics.json"],
                     [{"route": "/analytics", "type": "dashboard"},
                      {"route": "/dashboard", "type": "dashboard"}])
        assert _find_dashboard_schema(root).name == "dashboard.json"

    def test_a_genuine_miss_still_falls_through(self, tmp_path):
        """No landing file at all → the next dashboard page is correct."""
        root = _tree(tmp_path, ["analytics.json"],
                     [{"route": "/", "type": "dashboard"},
                      {"route": "/analytics", "type": "dashboard"}])
        assert _find_dashboard_schema(root).name == "analytics.json"

    def test_no_dashboard_pages_resolves_to_nothing_or_a_known_slug(self, tmp_path):
        root = _tree(tmp_path, ["bills.json"], [{"route": "/bills", "type": "list"}])
        got = _find_dashboard_schema(root)
        assert got is None or got.name != "bills.json"

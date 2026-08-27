"""Tests for services.smith_recent_edits — per-project route memory."""
from __future__ import annotations

import pytest

from services import smith_recent_edits as sre


@pytest.fixture(autouse=True)
def _isolate():
    sre.clear_all()
    yield
    sre.clear_all()


class TestPushGet:
    def test_empty_initially(self):
        assert sre.get("p1") == []

    def test_push_then_get(self):
        sre.push("p1", ["/candidates"])
        assert sre.get("p1") == ["/candidates"]

    def test_newest_first(self):
        sre.push("p1", ["/a"])
        sre.push("p1", ["/b"])
        assert sre.get("p1") == ["/b", "/a"]

    def test_dupe_moves_to_front(self):
        sre.push("p1", ["/a", "/b", "/c"])
        sre.push("p1", ["/b"])
        assert sre.get("p1") == ["/b", "/a", "/c"]

    def test_maxlen_5(self):
        for r in ["/a", "/b", "/c", "/d", "/e", "/f"]:
            sre.push("p1", [r])
        got = sre.get("p1")
        assert len(got) == 5
        # /a evicted; /f is newest.
        assert "/a" not in got
        assert got[0] == "/f"

    def test_isolated_by_project(self):
        sre.push("p1", ["/x"])
        sre.push("p2", ["/y"])
        assert sre.get("p1") == ["/x"]
        assert sre.get("p2") == ["/y"]

    def test_falsy_ignored(self):
        sre.push("p1", ["", None, "/a"])  # type: ignore[list-item]
        assert sre.get("p1") == ["/a"]


class TestRoutesFromEditedPaths:
    def test_top_level_schema(self):
        assert sre._routes_from_edited_paths(
            ["src/schemas/candidates.json"]
        ) == ["/candidates"]

    def test_nested_route(self):
        assert sre._routes_from_edited_paths(
            ["src/schemas/candidates/[id]/edit.json"]
        ) == ["/candidates/[id]/edit"]

    def test_index_becomes_root(self):
        assert sre._routes_from_edited_paths(
            ["src/schemas/index.json"]
        ) == ["/"]

    def test_non_schema_paths_dropped(self):
        assert sre._routes_from_edited_paths([
            "src/lib/thing.ts",
            "package.json",
            "src/schemas/x.json",
        ]) == ["/x"]

    def test_backslashes_tolerated(self):
        assert sre._routes_from_edited_paths(
            ["src\\schemas\\a.json"]
        ) == ["/a"]

    def test_empty(self):
        assert sre._routes_from_edited_paths([]) == []


class TestRecordEdit:
    def test_records_derived_routes(self):
        sre.record_edit("p1", ["src/schemas/candidates.json"])
        assert sre.get("p1") == ["/candidates"]

    def test_multiple_paths_one_call(self):
        sre.record_edit("p1", [
            "src/schemas/a.json",
            "src/schemas/b.json",
        ])
        # Prepended in given order → later item ends up ahead of first.
        assert sre.get("p1") == ["/a", "/b"]

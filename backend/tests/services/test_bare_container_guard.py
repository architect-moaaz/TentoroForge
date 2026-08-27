"""Tests for services.bare_container_guard (B-022.5 targeted fix)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.bare_container_guard import apply_bare_container_guard


def _make(root: Path, schemas: dict[str, dict]) -> None:
    (root / "src" / "schemas").mkdir(parents=True)
    for name, doc in schemas.items():
        (root / "src" / "schemas" / f"{name}.json").write_text(json.dumps(doc))


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "src" / "schemas" / f"{name}.json").read_text())


class TestPruneEmptyContainers:
    def test_removes_empty_card_with_no_children_or_title(self, tmp_path: Path):
        _make(tmp_path, {"p": {"nodes": [
            {"type": "Heading", "props": {"content": "Title"}},
            {"type": "Card"},   # bare, no props of interest
            {"type": "Text", "props": {"content": "body"}},
        ]}})
        r = apply_bare_container_guard(str(tmp_path))
        assert r["empty_removed"] >= 1
        after = _read(tmp_path, "p")
        types = [n.get("type") for n in after["nodes"]]
        assert "Card" not in types

    def test_keeps_card_that_has_a_title(self, tmp_path: Path):
        """Card with a title but no body gets an empty-state child, not removal."""
        _make(tmp_path, {"p": {"nodes": [
            {"type": "Card", "props": {"title": "Summary"}, "children": []},
        ]}})
        r = apply_bare_container_guard(str(tmp_path))
        assert r["empty_states_added"] == 1
        after = _read(tmp_path, "p")
        card = after["nodes"][0]
        assert card["type"] == "Card"
        assert len(card["children"]) == 1
        assert card["children"][0]["type"] == "EmptyState"


class TestHeadingOnly:
    def test_card_with_only_heading_gets_empty_state(self, tmp_path: Path):
        _make(tmp_path, {"p": {"nodes": [
            {"type": "Card", "children": [
                {"type": "Heading", "props": {"content": "Overview"}},
            ]},
        ]}})
        r = apply_bare_container_guard(str(tmp_path))
        assert r["empty_states_added"] == 1
        after = _read(tmp_path, "p")
        card = after["nodes"][0]
        types = [c["type"] for c in card["children"]]
        assert types == ["Heading", "EmptyState"]


class TestPopulatedUntouched:
    def test_card_with_real_content_untouched(self, tmp_path: Path):
        _make(tmp_path, {"p": {"nodes": [
            {"type": "Card", "children": [
                {"type": "Heading", "props": {"content": "Recent"}},
                {"type": "Table", "props": {"columns": []}},
            ]},
        ]}})
        r = apply_bare_container_guard(str(tmp_path))
        assert r["empty_states_added"] == 0
        assert r["empty_removed"] == 0


class TestIdempotency:
    def test_second_run_is_stable(self, tmp_path: Path):
        _make(tmp_path, {"p": {"nodes": [
            {"type": "Card", "children": [
                {"type": "Heading", "props": {"content": "Overview"}},
            ]},
        ]}})
        r1 = apply_bare_container_guard(str(tmp_path))
        first_added = r1["empty_states_added"]
        r2 = apply_bare_container_guard(str(tmp_path))
        assert r2["empty_states_added"] == 0
        assert first_added > 0


class TestNestedRecursion:
    def test_bare_container_inside_populated_container_still_fixed(self, tmp_path: Path):
        _make(tmp_path, {"p": {"nodes": [
            {"type": "Section", "children": [
                {"type": "Heading", "props": {"content": "Section"}},
                {"type": "Card", "children": [
                    {"type": "Heading", "props": {"content": "Bare card"}},
                ]},
                {"type": "Table", "props": {"columns": []}},
            ]},
        ]}})
        r = apply_bare_container_guard(str(tmp_path))
        assert r["empty_states_added"] >= 1


class TestNoOp:
    def test_no_schemas_dir(self, tmp_path: Path):
        r = apply_bare_container_guard(str(tmp_path))
        assert r["files_touched"] == []
        assert r["empty_states_added"] == 0
        assert r["empty_removed"] == 0

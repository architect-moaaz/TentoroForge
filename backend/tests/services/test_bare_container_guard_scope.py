"""The bare-container guard must not editorialise app chrome.

Two live defects on 6q7oqejv, both from the guard being scoped wider than
its own docstring claims ("Applies to Section / Card / Cluster / Split"):

1. It globbed `src/schemas/*.json`, which includes `shell.json`. The shell is
   the nav frame + brand + header slots, not page content.
2. `heading_only` fired on Stack / Row / Grid / Container — invisible layout
   wrappers. A Stack holding the logo and the app name is ordinary chrome.

Together they wedged an EmptyState reading "Nothing here yet." into the
shell header, next to the app title, on every page of the app.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.bare_container_guard import apply_bare_container_guard


def _write(root: Path, name: str, doc: dict) -> Path:
    d = root / "src" / "schemas"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _brand_stack() -> dict:
    """The exact shape that broke: a Stack wrapping only a Heading."""
    return {
        "children": [{
            "type": "Stack",
            "props": {"className": "gap-0"},
            "children": [
                {"type": "Heading",
                 "props": {"content": "Inventory Management System",
                           "level": 3}},
            ],
        }],
    }


def _has_empty_state(doc: dict) -> bool:
    return "EmptyState" in json.dumps(doc)


class TestShellIsNotAPage:
    def test_shell_json_is_left_alone(self, tmp_path: Path):
        p = _write(tmp_path, "shell.json", _brand_stack())
        apply_bare_container_guard(str(tmp_path))
        after = json.loads(p.read_text(encoding="utf-8"))
        assert not _has_empty_state(after), (
            "shell.json is app chrome — the guard must not add copy to it")

    def test_shell_is_not_reported_as_touched(self, tmp_path: Path):
        _write(tmp_path, "shell.json", _brand_stack())
        res = apply_bare_container_guard(str(tmp_path))
        assert "shell.json" not in res["files_touched"]


class TestLayoutWrappersAreNotSurfaces:
    @pytest.mark.parametrize("wrapper", ["Stack", "Row", "Grid", "Container"])
    def test_heading_only_layout_wrapper_untouched(self, wrapper, tmp_path):
        doc = {"children": [{
            "type": wrapper,
            "children": [{"type": "Heading", "props": {"content": "Title"}}],
        }]}
        p = _write(tmp_path, "page.json", doc)
        apply_bare_container_guard(str(tmp_path))
        assert not _has_empty_state(json.loads(p.read_text(encoding="utf-8")))

    @pytest.mark.parametrize("surface", ["Card", "Section"])
    def test_heading_only_painted_surface_still_repaired(self, surface, tmp_path):
        """The original bug this guard exists for must still be caught."""
        doc = {"children": [{
            "type": surface,
            "children": [{"type": "Heading", "props": {"content": "Title"}}],
        }]}
        p = _write(tmp_path, "page.json", doc)
        res = apply_bare_container_guard(str(tmp_path))
        assert _has_empty_state(json.loads(p.read_text(encoding="utf-8")))
        assert res["empty_states_added"] == 1


class TestUnrelatedBehaviourHolds:
    def test_surface_with_real_content_untouched(self, tmp_path: Path):
        doc = {"children": [{
            "type": "Card",
            "children": [
                {"type": "Heading", "props": {"content": "Stock"}},
                {"type": "Table", "props": {}},
            ],
        }]}
        p = _write(tmp_path, "page.json", doc)
        apply_bare_container_guard(str(tmp_path))
        assert not _has_empty_state(json.loads(p.read_text(encoding="utf-8")))

    def test_running_twice_adds_nothing_extra(self, tmp_path: Path):
        doc = {"children": [{
            "type": "Card",
            "children": [{"type": "Heading", "props": {"content": "Title"}}],
        }]}
        p = _write(tmp_path, "page.json", doc)
        apply_bare_container_guard(str(tmp_path))
        first = p.read_text(encoding="utf-8")
        apply_bare_container_guard(str(tmp_path))
        assert p.read_text(encoding="utf-8") == first

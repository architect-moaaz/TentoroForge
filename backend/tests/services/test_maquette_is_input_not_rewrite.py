"""The maquette informs the author; it does not overwrite the author.

Maquettes are authored in the bootstrap band, long before any page is
written. For most of this system's life they were read only in
post-generation, where a composer used them to REPLACE whatever the page
author had produced — the design was decided, ignored, then imposed. The
two invariants here are the reversal:

  1. the composed (merged) vocabulary is what the maquette authors read,
  2. an already-authored page is never rewritten.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.apply_collection_maquette import _apply_one as _apply_collection
from services.apply_record_maquette import _apply_one as _apply_record


def _app(tmp_path: Path, route: str, slug: str) -> Path:
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "schemas" / f"{slug}.json").write_text(json.dumps({
        "schemaVersion": "2", "id": slug, "route": route,
        # A page the author already built — deliberately NOT the shape the
        # composer would emit, so a rewrite is unmistakable.
        "root": {"type": "Stack", "children": [
            {"type": "Kanban", "props": {"groupBy": "status"}},
        ]},
    }))
    return tmp_path


def _untouched(tmp_path: Path, slug: str) -> bool:
    d = json.loads((tmp_path / "src" / "schemas" / f"{slug}.json").read_text())
    kinds = [c.get("type") for c in d["root"]["children"]]
    return kinds == ["Kanban"]


def test_collection_applier_refuses_to_rewrite_an_authored_page(tmp_path):
    _app(tmp_path, "/events", "events")
    res = _apply_collection(tmp_path, {
        "entity": "Event", "route": "/events", "layout": "table",
        "columns": [{"name": "name", "label": "Event"}],
    }, {"entities": {}}, allow_bootstrap=False)
    assert res["applied"] is False
    assert "not overwriting" in res["reason"]
    assert _untouched(tmp_path, "events"), "the author's page was rewritten"


def test_record_applier_refuses_to_rewrite_an_authored_page(tmp_path):
    _app(tmp_path, "/events/[id]", "events-id")
    res = _apply_record(tmp_path, {
        "entity": "Event", "route": "/events/[id]", "mode": "view",
        "section_grouping": [{"label": "Overview", "fields": ["name"]}],
    }, {"entities": {}}, allow_bootstrap=False)
    assert res["applied"] is False
    assert "not overwriting" in res["reason"]
    assert _untouched(tmp_path, "events-id"), "the author's page was rewritten"


def test_the_authors_read_the_composed_vocabulary_not_the_base(monkeypatch):
    """The merge exists to pick a business vocabulary for THIS app. If the
    authors read the single base archetype instead, the composition is
    computed and then discarded — which is what used to happen."""
    import services.page_vocabulary as pv

    sentinel = object()
    monkeypatch.setattr(pv, "vocabulary_for_output_dir", lambda _root: sentinel)
    assert pv.vocabulary_for_plan(
        {"_output_dir": "/somewhere", "archetype": "booking-platform"}
    ) is sentinel


def test_base_archetype_is_only_the_fallback(monkeypatch):
    """No output dir (unit-test path) → the single archetype is still
    better than nothing."""
    import services.page_vocabulary as pv
    monkeypatch.setattr(pv, "vocabulary_for_output_dir", lambda _root: None)
    v = pv.vocabulary_for_plan({"archetype": "booking-platform"})
    assert v is not None and v.id == "booking-platform"


def test_all_three_authors_go_through_the_shared_resolver():
    """Guards the wiring: a future edit that reverts one author back to
    load_vocabulary would silently un-fix the inversion for that layer."""
    for mod in ("dashboard_maquette", "collection_maquette", "record_maquette"):
        src = Path(f"services/{mod}.py").read_text()
        assert "vocabulary_for_plan" in src, mod
        assert "load_vocabulary(plan.get(\"archetype\"))" not in src, mod

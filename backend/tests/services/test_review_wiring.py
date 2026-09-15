"""The re-compose seam: drop exactly the reviewed page's layout so the resume
re-composes it, and carry the brief in a transient file (not the Blueprint, so
no schema field must be declared) that the composer reads and that is cleaned
up afterwards."""

import json
from pathlib import Path

from services.smith.review_wiring import (
    invalidate_for_recompose, write_review_briefs, clear_review_briefs,
    _slug_for,
)
from services.a2ui_authority import _review_brief_for


def _doc():
    return {
        "pages": [
            {"id": "PAGE-001", "route": "/master-data"},
            {"id": "PAGE-002", "route": "/add-data"},
        ],
        "pageLayouts": [
            {"page": "PAGE-001", "root": {"type": "Stack"}},
            {"page": "PAGE-002", "root": {"type": "Stack"}},
        ],
    }


def test_invalidate_drops_only_the_reviewed_pages_layout():
    doc = _doc()
    hit = invalidate_for_recompose(doc, {"PAGE-001": "make it denser"})
    assert hit == ["PAGE-001"]
    # Only the reviewed page's layout is gone (so the resume re-composes it).
    assert [l["page"] for l in doc["pageLayouts"]] == ["PAGE-002"]
    # The Blueprint page is NOT mutated — no undeclared field written.
    assert all("reviewBrief" not in p for p in doc["pages"])


def test_a_brief_for_no_live_page_or_empty_does_nothing():
    doc = _doc()
    assert invalidate_for_recompose(doc, {"PAGE-404": "x", "PAGE-001": "  "}) == []
    assert len(doc["pageLayouts"]) == 2  # nothing dropped


def test_brief_round_trips_through_the_transient_file(tmp_path):
    out = str(tmp_path)
    write_review_briefs(out, {"PAGE-001": "denser, one search"})
    # The composer reads exactly this on the re-compose.
    assert _review_brief_for(Path(out), "PAGE-001") == "denser, one search"
    assert _review_brief_for(Path(out), "PAGE-002") == ""     # no brief for it
    # ...and it is a real file, not the Blueprint.
    assert (tmp_path / "contracts" / "review-briefs.json").exists()

    clear_review_briefs(out)
    assert not (tmp_path / "contracts" / "review-briefs.json").exists()
    assert _review_brief_for(Path(out), "PAGE-001") == ""     # gone after clear


def test_review_brief_for_is_quiet_when_absent(tmp_path):
    assert _review_brief_for(tmp_path, "PAGE-001") == ""      # no file
    assert _review_brief_for(tmp_path, "") == ""             # no page id


def test_slug_derivation_matches_route():
    doc = _doc()
    assert _slug_for("/master-data", doc) == "master-data"
    assert _slug_for("/records/[id]/edit", doc) == "records-edit"  # dynamic seg dropped
    assert _slug_for("/", doc) == "index"


# --- a refused re-compose restores the page's previous tree ---

from services.smith.review_wiring import (
    layouts_of, restore_refused_layouts, refused_pages, _capture_pages,
)


def test_the_pre_image_is_restored_only_for_the_refused_pages():
    doc = _doc()
    before = layouts_of(doc, ["PAGE-001", "PAGE-002"])
    assert set(before) == {"PAGE-001", "PAGE-002"}
    invalidate_for_recompose(doc, {"PAGE-001": "b", "PAGE-002": "b"})
    # PAGE-002 was re-composed (a new tree landed); PAGE-001 was refused.
    doc["pageLayouts"].append({"page": "PAGE-002", "root": {"type": "Container"}})
    assert restore_refused_layouts(doc, before, ["PAGE-001"]) == ["PAGE-001"]
    by = {l["page"]: l["root"] for l in doc["pageLayouts"]}
    assert by == {"PAGE-002": {"type": "Container"}, "PAGE-001": {"type": "Stack"}}
    # Restoring again, or a page that has a tree, changes nothing.
    assert restore_refused_layouts(doc, before, ["PAGE-001", "PAGE-002"]) == []


def test_refused_pages_are_read_from_the_build_report():
    built = {"report": {"failed": [
        {"node": "page_layouts:PAGE-001", "why": "InvalidPatternTemplate: Table runs Update Record"},
        {"node": "frontend", "why": "skipped"},
    ]}}
    assert refused_pages(built) == {"PAGE-001": "InvalidPatternTemplate: Table runs Update Record"}
    assert refused_pages({}) == {} and refused_pages(None) == {}


def test_the_review_can_be_narrowed_to_named_routes(monkeypatch):
    import services.smith.review_wiring as rw
    asked = []
    monkeypatch.setattr(rw, "_screenshot", lambda url: asked.append(url) or b"png")
    monkeypatch.setattr(rw, "_preview_url", lambda out, route, doc: route)
    doc = _doc()
    assert [s["route"] for s in _capture_pages("out", doc)] == ["/master-data", "/add-data"]
    assert [s["route"] for s in _capture_pages("out", doc, ["/add-data"])] == ["/add-data"]
    assert _capture_pages("out", doc, ["/nowhere"]) == []


def test_unrepaired_pages_are_read_from_the_build_report():
    from services.smith.review_wiring import unrepaired_pages
    built = {"report": {"unrepaired": [
        {"node": "page_layouts:PAGE-001", "why": "Observer↔Requirement: REQ-012: Female filters on Male"},
        {"node": "composition", "why": "not a page"},
    ]}}
    assert unrepaired_pages(built) == {"PAGE-001": "Observer↔Requirement: REQ-012: Female filters on Male"}
    assert unrepaired_pages({}) == {} and unrepaired_pages(None) == {}

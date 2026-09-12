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

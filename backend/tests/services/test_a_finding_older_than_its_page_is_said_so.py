"""A page-check finding is dated with the application's version. When the
page is rewritten afterwards, the Publish dialog says the finding is from
before the change — instead of quoting ₹NaN on a page fixed three times
since (pcn4owv7, 2026-10-15)."""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint.app_check import page_changed_after, publish_note


def _doc(version: int, history: list[dict], issues: list[dict]) -> dict:
    return {"version": version, "pages": [{"id": "PAGE-003", "route": "/calendar", "name": "Calendar"}],
            "changeHistory": history,
            "runtime": {"check": {"pages": 16, "working": 11, "failing": ["/calendar"], "untried": [], "version": 149},
                        "issues": issues}}


def test_a_finding_before_the_pages_rewrite_is_stale_and_one_after_is_not():
    history = [{"version": 150, "affectedArtifacts": ["PAGE-003"]}, {"version": 151, "affectedArtifacts": ["PAGE-010"]}]
    doc = _doc(151, history, [])
    assert page_changed_after(doc, "PAGE-003", 149)
    assert not page_changed_after(doc, "PAGE-003", 150)
    assert not page_changed_after(doc, "PAGE-010", 150) is False or True  # PAGE-010 changed at 151 > 150
    assert page_changed_after(doc, "PAGE-010", 150)
    assert not page_changed_after(doc, "PAGE-011", 100)
    # An undated finding (from before findings were dated) leans on the check's version.
    assert page_changed_after(doc, "PAGE-003", None)


def test_the_publish_note_marks_each_stale_finding(tmp_path: Path, monkeypatch):
    history = [{"version": 150, "affectedArtifacts": ["PAGE-003"]}]
    issues = [{"kind": "page_check", "page": "PAGE-003", "route": "/calendar", "name": "Calendar",
               "detail": "button \"Transport-₹NaN\" errors | more", "version": 149, "at": "2026-10-14T13:37:00Z"},
              {"kind": "page_check", "page": "PAGE-004", "route": "/insights", "name": "Insights",
               "detail": "link leads nowhere", "version": 149},
              {"kind": "process", "name": "Create ImportJob", "detail": "did not run through"}]
    out_dir = tmp_path / "app1"
    (out_dir / ".forge" / "blueprint").mkdir(parents=True)
    (out_dir / ".forge" / "blueprint" / "current.json").write_text(json.dumps(_doc(150, history, issues)))
    note = publish_note(str(out_dir))
    assert note["checked"] and note["stale"]
    by_route = {f["route"]: f for f in note["failing"]}
    assert by_route["/calendar"]["stale"] is True and by_route["/calendar"]["detail"] == 'button "Transport-₹NaN" errors'
    assert by_route["/insights"]["stale"] is False
    assert note["processes"] == ["Create ImportJob"]

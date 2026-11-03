"""The same fault on many screens is one change (`edit_pages`, 2026-10-31).

DITANS's filters filtered nothing on about sixty screens, and the hand cursor
was missing on five hundred controls. Each was one brief: Smith had
`write_page_code` for one screen and `rewrite_pages` to lay screens out again
from the start, and nothing that made one change in each. `edit_pages` edits
each screen inside the layout it has, in parallel, as one version, and only
the screens whose code holds the fault when `having` says what it looks like.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.blueprint.service import BlueprintService
from services.smith import tools, writes


@pytest.fixture(autouse=True)
def _their_words_ask_for_it(monkeypatch):
    monkeypatch.setattr("services.smith4.turn.asked_for", lambda words, change: True)


def _svc(tmp_path: Path) -> BlueprintService:
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Jobs", domain="hiring")
    svc.doc["pages"] = [{"id": f"PAGE-00{i}", "name": n, "route": r, "purpose": "x"}
                        for i, (n, r) in enumerate([("Talent", "/talent"), ("Jobs", "/jobs"), ("Home", "/")], 1)]
    svc.doc["pageCode"] = [
        {"page": "PAGE-001", "rationale": "first", "load": "export {}", "view": "<Chip onClick={() => {}} />"},
        {"page": "PAGE-002", "rationale": "first", "load": "export {}", "view": "<Chip onClick={() => {}} />",
         "parts": {"Panel": "export default function Panel() { return <div/> }"}},
        {"page": "PAGE-003", "rationale": "first", "load": "export {}", "view": "<Hero />"},
    ]
    svc.save()
    return svc


@pytest.fixture
def writers(monkeypatch):
    import services.blueprint.ui_engineer as ue
    from services.blueprint import app_sdk
    monkeypatch.setattr(ue, "ensure_sdk", lambda doc, root: None)
    monkeypatch.setattr(app_sdk, "project_code_pages", lambda doc, root: [])
    seen: list[tuple[str, str, str]] = []

    def compose(doc, page, root, client, *, brief, current=None, relayout_of=None, **kw):
        assert relayout_of is None, "an edit is not a fresh layout"
        seen.append((page["route"], "edit", brief))
        if page["route"] == "/":
            return {**current, "rationale": "nothing here filters"}, []
        return {**current, "view": current["view"].replace("() => {}", "() => setFilter('remote')")}, []

    def reshape(doc, page, root, client, current, *, brief, critic=None):
        seen.append((page["route"], "reshape", brief))
        return {**current, "view": current["view"].replace("() => {}", "() => setFilter('remote')")}, []
    monkeypatch.setattr(ue, "compose_page", compose)
    monkeypatch.setattr(ue, "reshape_screen", reshape)
    return seen


def test_one_brief_changes_every_screen_inside_its_layout_as_one_version(tmp_path, writers):
    svc = _svc(tmp_path)
    before = svc.doc["version"]
    out = writes.edit_pages(str(tmp_path), ["all"], "make each filter chip set the filter")
    assert sorted((r, how) for r, how, _b in writers) == [("/", "edit"), ("/jobs", "reshape"), ("/talent", "edit")]
    assert out["applied"] and "Changed 2 screen(s)" in out["said"]
    # The screen with nothing to change is said, and not counted as done.
    assert "Left as they were (1): / — nothing here filters" in out["said"]
    doc = BlueprintService.load(output_dir=str(tmp_path)).doc
    assert doc["version"] == before + 1
    views = {r["page"]: r["view"] for r in doc["pageCode"]}
    assert views["PAGE-001"] == views["PAGE-002"] == "<Chip onClick={() => setFilter('remote')} />"
    assert views["PAGE-003"] == "<Hero />"


def test_only_the_screens_whose_code_holds_the_fault_are_changed(tmp_path, writers):
    _svc(tmp_path)
    out = writes.edit_pages(str(tmp_path), ["all"], "make each filter chip set the filter", having="onClick={() => {}}")
    assert sorted(r for r, _h, _b in writers) == ["/jobs", "/talent"]
    assert out["applied"]
    nothing = writes.edit_pages(str(tmp_path), ["all"], "x", having="onDoubleClick")
    assert not nothing["applied"] and "No screen's code contains" in nothing["finding"]


def test_the_catalogue_sizes_many_screens_apart_from_one_and_from_a_redesign():
    said = next(d for n, d, _a in writes.WRITES if n == "edit_pages")
    assert "inside the layout it has" in said and "ONE version" in said and "shared file" in said
    assert "`edit_pages`" in tools.render()

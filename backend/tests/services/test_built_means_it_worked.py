"""The completion message says what using the app proved, and Publish warns
while something still does not work.

"Your application is built — everything else works" was said of apps whose
pages were on disk and broken. Once the build has used the app
(`app_check`), the message opens with how much of it worked and names what
did not; the Publish dialog says the same before anything goes live.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint import app_check as ac

FLOWS = [{"id": "FLOW-001", "name": "Add Child", "trigger": {"kind": "manual"}},
         {"id": "FLOW-002", "name": "Book Slot", "trigger": {"kind": "manual"}},
         {"id": "FLOW-003", "name": "Digest", "trigger": {"kind": "schedule"}}]


def _doc(check=None, issues=()):
    doc = {"pages": [{"id": f"PAGE-00{i}", "route": f"/p{i}"} for i in range(1, 4)],
           "pageCode": [{"page": f"PAGE-00{i}", "view": "export default () => null"} for i in range(1, 4)],
           "workflows": FLOWS, "runtime": {"pages": {"planned": 3, "served": 3}, "issues": list(issues)}}
    if check is not None:
        doc["runtime"]["check"] = check
    return doc


def test_a_build_that_used_the_app_says_what_worked():
    from routers.blueprint_generate import _build_complete_message
    msg = _build_complete_message(_doc({"pages": 3, "working": 3, "fixed": ["/p2"], "failing": []}))
    assert msg.startswith("Your application is built. I used the whole application before handing it over: "
                          "3 of 3 pages opened and worked for every kind of person they are for; "
                          "2 of 2 processes ran through and showed what they saved.")
    assert "Fixed while checking: /p2." in msg and "Still not working" not in msg


def test_what_still_fails_is_named_with_its_first_finding():
    from routers.blueprint_generate import _build_complete_message
    issues = [{"kind": "page_check", "route": "/p3", "detail": "as Parent: it answers HTTP 500 | as Doctor: x"},
              {"kind": "process", "workflow": "FLOW-002", "name": "Book Slot"}]
    msg = _build_complete_message(_doc({"pages": 3, "working": 2, "failing": ["/p3"]}, issues))
    assert "2 of 3 pages opened and worked" in msg and "1 of 2 processes ran through" in msg
    assert "Still not working:\n- /p3 — as Parent: it answers HTTP 500" in msg
    assert "as Doctor" not in msg


def test_a_build_from_before_the_check_keeps_its_old_words():
    from routers.blueprint_generate import _build_complete_message
    assert _build_complete_message(_doc()).startswith("Your application is built — 3 pages ready.")


def test_after_a_checked_build_the_offer_is_for_how_pages_look():
    from routers import blueprint_generate as bg
    said = []
    bg._announce_build_complete(_doc({"pages": 3, "working": 3}), lambda e, d: said.append(d), offer_verify=True)
    assert said[1]["text"] == bg._LOOK_OFFER_TEXT and said[1]["options"] == list(bg._VERIFY_OFFER_OPTIONS)
    said.clear()
    bg._announce_build_complete(_doc(), lambda e, d: said.append(d), offer_verify=True)
    assert said[1]["text"] == bg._VERIFY_OFFER_TEXT


def test_publish_is_told_what_still_does_not_work(tmp_path, monkeypatch):
    from services.blueprint import service
    issues = [{"kind": "page_check", "route": "/p3", "detail": "as Parent: it answers HTTP 500 | more"},
              {"kind": "process", "workflow": "FLOW-002", "name": "Book Slot"}]
    doc = _doc({"pages": 3, "working": 2, "failing": ["/p3"]}, issues)
    monkeypatch.setattr(service.BlueprintService, "load", classmethod(
        lambda cls, output_dir: type("S", (), {"doc": doc})()))
    assert ac.publish_note(str(tmp_path)) == {
        "checked": True, "stale": False, "pages": 3, "working": 2,
        "failing": [{"route": "/p3", "detail": "as Parent: it answers HTTP 500"}], "processes": ["Book Slot"]}


def test_a_project_with_nothing_to_read_says_it_was_not_checked(tmp_path):
    assert ac.publish_note(str(tmp_path / "nowhere"))["checked"] is False


def test_the_dialog_asks_and_warns_without_blocking():
    root = Path(__file__).resolve().parents[3]
    dialog = (root / "frontend/src/components/deploy/PublishDialog.tsx").read_text()
    assert "`/api/projects/${projectId}/check`" in dialog
    assert "Publishing puts them live as they are" in dialog
    routes = (root / "backend/routers/deployments.py").read_text()
    assert '@router.get("/api/projects/{project_id}/check")' in routes

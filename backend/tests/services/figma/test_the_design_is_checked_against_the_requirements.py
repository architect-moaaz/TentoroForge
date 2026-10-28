"""A connected Figma design is checked against the requirements before it is built from.

The model reports what each frame covers; CODE decides whether the design is sufficient, and holds
the answer to what was actually sent — a frame or requirement it invents is dropped, a requirement it
forgets is not a requirement that passed."""
from __future__ import annotations

import json

import pytest

from services.figma import coverage as cv
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget

REQS = [{"id": "REQ-001", "description": "Staff can see all leave requests"},
        {"id": "REQ-002", "description": "A manager can approve a leave request"},
        {"id": "REQ-003", "description": "Emails go out when a request is decided"}]
FRAMES = [{"nodeId": "1:1", "name": "Requests", "labels": ["Leave requests", "Status"]},
          {"nodeId": "1:2", "name": "Calendar"}]


def _reply(**over):
    base = {"requirements": [
        {"id": "REQ-001", "status": "covered", "frames": ["1:1"], "reason": "the list"},
        {"id": "REQ-002", "status": "partial", "frames": ["1:1"], "reason": "no approve button"},
        {"id": "REQ-003", "status": "not_a_screen", "frames": [], "reason": "an email"}],
        "unmatchedFrames": [{"nodeId": "1:2", "note": "a team calendar"}],
        "missingScreens": [], "frameChanges": [
            {"nodeId": "1:1", "change": "add an Approve action", "requirements": ["REQ-002"]}]}
    base.update(over)
    return base


def test_a_design_that_shows_what_a_screen_can_show_is_sufficient():
    cov = cv.interpret(_reply(), REQS, FRAMES)
    assert cov.sufficient
    assert [r["id"] for r in cov.covered] == ["REQ-001"] and [r["id"] for r in cov.partial] == ["REQ-002"]
    assert [r["id"] for r in cov.not_a_screen] == ["REQ-003"], "an email is not a missing screen"
    assert cov.frame_changes[0]["name"] == "Requests" and cov.unmatched_frames[0]["name"] == "Calendar"
    assert "covers the application" in cv.report(cov) and "Worth tightening" in cv.report(cov)


def test_a_requirement_no_frame_shows_makes_the_design_insufficient():
    reply = _reply(requirements=[
        {"id": "REQ-001", "status": "covered", "frames": ["1:1"], "reason": ""},
        {"id": "REQ-002", "status": "missing", "frames": [], "reason": "no approval screen"},
        {"id": "REQ-003", "status": "not_a_screen", "frames": [], "reason": ""}],
        missingScreens=[{"name": "Approve request", "why": "managers decide here", "requirements": ["REQ-002"]}])
    cov = cv.interpret(reply, REQS, FRAMES)
    assert not cov.sufficient
    text = cv.report(cov)
    assert "missing 1 thing" in text and "A manager can approve a leave request" in text
    assert "**Approve request**" in text
    for option in cv.OPTIONS:
        assert option in text, option


def test_a_requirement_the_model_forgot_does_not_pass():
    reply = _reply(requirements=[{"id": "REQ-001", "status": "covered", "frames": ["1:1"], "reason": ""}])
    cov = cv.interpret(reply, REQS, FRAMES)
    assert not cov.sufficient
    assert {r["id"] for r in cov.missing} == {"REQ-002", "REQ-003"}
    assert all(r["reason"] == "the check did not assess it" for r in cov.missing)


def test_covered_by_no_frame_is_not_covered_and_invented_names_are_dropped():
    reply = _reply(requirements=[
        {"id": "REQ-001", "status": "covered", "frames": ["9:9"], "reason": ""},          # a frame never sent
        {"id": "REQ-099", "status": "covered", "frames": ["1:1"], "reason": ""},         # a requirement never sent
        {"id": "REQ-002", "status": "bogus", "frames": ["1:1"], "reason": ""},           # a status that is not one
        {"id": "REQ-003", "status": "not_a_screen", "frames": [], "reason": ""}],
        unmatchedFrames=[{"nodeId": "7:7", "note": "invented"}],
        frameChanges=[{"nodeId": "7:7", "change": "x", "requirements": []}])
    cov = cv.interpret(reply, REQS, FRAMES)
    assert [r["id"] for r in cov.missing] == ["REQ-001", "REQ-002"]
    assert not cov.covered and not cov.unmatched_frames and not cov.frame_changes


def _doc(tmp_path):
    ref = DesignReference(target=FigmaTarget(file_key="abc"), screens=[
        ScreenRef(node_id="1:1", name="Requests", width=1440, height=900,
                  structure={"labels": ["Leave requests", "Status"]}),
        ScreenRef(node_id="1:2", name="Icons", looks_like_screen=False)])
    store.save(ref, tmp_path)
    return {"requirements": [{"id": r["id"], "description": r["description"], "status": "APPROVED"} for r in REQS]
            + [{"id": "REQ-100", "description": "gone", "status": "DEPRECATED"}],
            "designSources": [{"id": "FIGMA-001", "provider": "figma"},
                              {"id": "UXPILOT-001", "provider": "uxpilot"}]}


def test_the_check_reads_the_stored_frames_and_the_live_requirements(tmp_path):
    doc = _doc(tmp_path)
    assert [r["id"] for r in cv.requirements_of(doc)] == ["REQ-001", "REQ-002", "REQ-003"]
    frames = cv.frames_of(doc, tmp_path)
    assert frames == [{"nodeId": "1:1", "name": "Requests", "size": "1440x900",
                       "labels": ["Leave requests", "Status"]}], "icon sheets and UX Pilot designs are not frames here"

    seen = {}

    def client(*, system, user, schema):
        seen.update(system=system, user=user, schema=schema)
        return json.dumps(_reply())

    cov = cv.check(doc, tmp_path, client)
    assert cov.sufficient and "REQ-002" in seen["user"] and "Leave requests" in seen["user"]
    assert "REQ-100" not in seen["user"] and seen["schema"] is cv.SCHEMA


def test_a_check_that_cannot_be_made_says_so_instead_of_passing_the_design(tmp_path):
    doc = _doc(tmp_path)

    def broken(**_):
        raise RuntimeError("provider down")

    with pytest.raises(cv.CoverageUnavailable, match="could not check"):
        cv.check(doc, tmp_path, broken)
    with pytest.raises(cv.CoverageUnavailable, match="no requirements"):
        cv.check({"requirements": [], "designSources": doc["designSources"]}, tmp_path, lambda **_: "{}")
    with pytest.raises(cv.CoverageUnavailable, match="No screens"):
        cv.check({**doc, "designSources": []}, tmp_path, lambda **_: "{}")

"""A design read over the REST API has words, and a design nobody has checked does not start a build.

Two things the first live run of the Figma gate showed. With the hosted MCP refusing a personal token, a
frame arrived as a node tree, and the words on it were never read off: the coverage check was sent a name
and a size and could judge nothing. And a design that was read but not checked — the check interrupted, or
the design named in the brief — passed the build's own gate."""
from __future__ import annotations

import json

import pytest

from services.blueprint.service import BlueprintService
from services.figma import coverage as cv
from services.figma import store
from services.figma.brief import design_brief, screen_entry
from services.figma.reference import DesignReference, ScreenRef, labels_from_document
from services.figma.url import FigmaTarget
from services.smith import figma_gate as fg
from services.smith import ui_designer as ud

URL = "https://www.figma.com/design/llRwGmNM8NX72r9r4gmnEq/ToolShare?node-id=2-619"


def _text(chars, x, y, **extra):
    return {"type": "TEXT", "characters": chars, "absoluteBoundingBox": {"x": x, "y": y, "width": 80, "height": 16}, **extra}


DOC = {"type": "FRAME", "name": "Community Tool Sharing Platform", "children": [
    {"type": "FRAME", "name": "Reviews", "children": [
        _text("Reviews received", 700, 300), _text("Great tool, thanks", 700, 340)]},
    {"type": "FRAME", "name": "Header", "children": [_text("My Profile", 40, 20), _text("Edit profile", 900, 22)]},
    {"type": "FRAME", "name": "Stats", "children": [_text("Verified Resident", 40, 120), _text("4.8", 200, 120)]},
    _text("My Profile", 40, 20),                                   # said twice: kept once
    _text("Never shown", 40, 500, visible=False),
    _text("   ", 0, 0),
]}


def test_the_words_on_a_rest_frame_are_read_in_reading_order():
    labels = labels_from_document(DOC)
    assert labels == ["My Profile", "Edit profile", "Verified Resident", "4.8", "Reviews received", "Great tool, thanks"]
    assert labels_from_document(None) == [] and labels_from_document({"type": "FRAME"}) == []


def test_a_design_stored_before_its_words_were_read_gets_them_without_a_second_fetch():
    screen = ScreenRef(node_id="2:619", name="Community Tool Sharing Platform", width=1257, height=982,
                       structure={"source": "rest_node_document", "document": DOC})   # no "labels": as stored
    entry = screen_entry(screen)
    assert entry["labels"][:3] == ["My Profile", "Edit profile", "Verified Resident"]
    ref = DesignReference(target=FigmaTarget(file_key="k"), screens=[screen])
    assert design_brief(ref)["screens"][0]["labels"], "what the design agent is shown carries the words too"


def test_the_coverage_check_is_shown_the_words(tmp_path):
    screen = ScreenRef(node_id="2:619", name="Community Tool Sharing Platform", width=1257, height=982,
                       structure={"source": "rest_node_document", "document": DOC})
    store.save(DesignReference(target=FigmaTarget(file_key="k"), screens=[screen]), tmp_path)
    doc = {"requirements": [{"id": "REQ-001", "description": "x", "status": "APPROVED"}],
           "designSources": [{"id": "FIGMA-001", "provider": "figma"}]}
    frames = cv.frames_of(doc, tmp_path)
    assert frames[0]["labels"][0] == "My Profile" and "Verified Resident" in frames[0]["labels"]


# --------------------------------------------------------------------------- #
# A design nobody checked does not start a build
# --------------------------------------------------------------------------- #

@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_UI_DESIGNER", raising=False)
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="ToolShare", domain="community")
    s.doc["requirements"] = [{"id": "REQ-001", "description": "A neighbour keeps a profile", "status": "VERIFIED"}]
    s.validate()
    s.save()
    return s


def _connect(output_dir, url):
    svc = BlueprintService.load(output_dir=str(output_dir))
    screen = ScreenRef(node_id="2:619", name="Community Tool Sharing Platform", width=1257, height=982,
                       structure={"source": "rest_node_document", "document": DOC})
    store.connect(svc, DesignReference(target=FigmaTarget(file_key="k", source_url=url), screens=[screen]))


def _model(*, system, user, schema):
    assert "My Profile" in user and "Verified Resident" in user, "the model is shown the frame's words"
    return json.dumps({"requirements": [{"id": "REQ-001", "status": "covered", "frames": ["2:619"], "reason": "the profile"}],
                       "unmatchedFrames": [], "missingScreens": [], "frameChanges": []})


def test_a_design_that_was_read_but_never_checked_is_not_let_through(svc):
    ud.record(svc, "figma")
    _connect(svc.output_dir, URL)                                    # read; no check was made
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    stop = ud.gate(doc, svc.output_dir)
    assert stop is not None and fg.is_check_pending(stop["text"]) and stop["status"] == "asked"
    assert stop["options"] == [fg.CHECK_NOW, ud.USE_FORGE_INSTEAD]


def test_checking_it_now_runs_the_check_and_lets_the_build_go_on_when_it_passes(svc):
    ud.record(svc, "figma")
    _connect(svc.output_dir, URL)
    asked = ud.gate(BlueprintService.load(output_dir=svc.output_dir).doc, svc.output_dir)["text"]
    assert fg.choice_in(fg.CHECK_NOW, [("smith", asked)]) == "check"
    assert fg.choice_in(fg.CHECK_NOW, [("smith", "Which language?")]) == "", "the words alone decide nothing"
    out = fg.handle(svc, svc.output_dir, choice="check", client=_model)
    assert out.proceed and "covers the application" in out.message["text"]
    assert ud.gate(BlueprintService.load(output_dir=svc.output_dir).doc, svc.output_dir) is None


def test_forge_instead_is_a_way_out_of_the_check_request(svc):
    ud.record(svc, "figma")
    _connect(svc.output_dir, URL)
    asked = ud.gate(BlueprintService.load(output_dir=svc.output_dir).doc, svc.output_dir)["text"]
    assert ud.answer_in(ud.USE_FORGE_INSTEAD, [("smith", asked)]) == "forge"

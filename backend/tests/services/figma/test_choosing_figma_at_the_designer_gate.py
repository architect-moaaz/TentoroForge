"""Choosing Figma where the person is asked who designs the screens.

The flow: Smith asks for the link (and the token, which is stored outside the chat) → the design is
read → it is checked against the requirements → the build goes on, or Smith says what is missing and
offers update / Forge fills the gaps / only what I drew. Every step is a chat turn recognised by the
turn before it, and nothing here reaches the network: the read and the model are stand-ins."""
from __future__ import annotations

import json

import pytest

from services.blueprint.service import BlueprintService
from services.figma import coverage as cv
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget
from services.smith import figma_gate as fg
from services.smith import ui_designer as ud
from services.uxpilot.generate import designer_for

URL = "https://www.figma.com/design/llRwGmNM8NX72r9r4gmnEq/Leave?node-id=1-2"


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_UI_DESIGNER", raising=False)
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Leave", domain="HR")
    s.doc["requirements"] = [
        {"id": "REQ-001", "description": "Staff can see their leave requests", "status": "VERIFIED"},
        {"id": "REQ-002", "description": "A manager can approve a request", "status": "VERIFIED"}]
    s.validate()
    s.save()
    return s


def _connect(output_dir, url):
    """The read, as a stand-in: stores one frame and records the design on the Blueprint."""
    svc = BlueprintService.load(output_dir=str(output_dir))
    ref = DesignReference(target=FigmaTarget(file_key="abc123", node_id="1:2", source_url=url), screens=[
        ScreenRef(node_id="1:2", name="My requests", width=1440, height=900,
                  structure={"labels": ["My leave requests", "Status"]})])
    store.connect(svc, ref)


def _model(approve_covered: bool):
    def client(*, system, user, schema):
        second = ({"id": "REQ-002", "status": "covered", "frames": ["1:2"], "reason": "the approve button"}
                  if approve_covered else
                  {"id": "REQ-002", "status": "missing", "frames": [], "reason": "no approval screen"})
        return json.dumps({"requirements": [
            {"id": "REQ-001", "status": "covered", "frames": ["1:2"], "reason": "the list"}, second],
            "unmatchedFrames": [], "frameChanges": [],
            "missingScreens": [] if approve_covered else
            [{"name": "Approve request", "why": "managers decide here", "requirements": ["REQ-002"]}]})
    return client


# --------------------------------------------------------------------------- #
# The question and the choice
# --------------------------------------------------------------------------- #

def test_figma_is_an_answer_to_the_designer_question_and_is_recorded(svc):
    q = ud.question(svc.doc)
    assert ud.answer_in("Figma", [("smith", q)]) == "figma"
    assert ud.answer_in("my figma design", [("assistant", q)]) == "figma"
    assert ud.answer_in("Figma", [("assistant", "Which language?")]) == "", "the word alone is not a decision"
    said = ud.record(svc, "figma")
    assert "Figma it is" in said
    reloaded = BlueprintService.load(output_dir=svc.output_dir)
    assert reloaded.doc["application"]["uiDesigner"] == "figma" and ud.chosen(reloaded.doc) == "figma"
    assert any(d["decision"].endswith("Figma.") for d in reloaded.doc["decisions"])


def test_a_page_with_no_frame_goes_to_the_forge_designer_even_under_a_platform_default(svc, monkeypatch):
    ud.record(svc, "figma")
    monkeypatch.setenv("FORGE_UI_DESIGNER", "uxpilot")
    assert designer_for(svc.doc, {"id": "PAGE-001"}) == "forge"


# --------------------------------------------------------------------------- #
# Asking for the design
# --------------------------------------------------------------------------- #

def test_without_a_saved_token_the_prompt_asks_for_it_in_a_field_and_never_in_the_chat(svc, monkeypatch):
    monkeypatch.setattr(fg, "token_configured", lambda _o: False)
    ud.record(svc, "figma")
    stop = ud.gate(svc.doc, svc.output_dir)
    assert fg.is_prompt(stop["text"]) and stop["status"] == "asked"
    field = stop["secret"]
    assert field["provider"] == "figma" and field["key"] == "FIGMA_TOKEN" and field["saved"] == fg.FIGMA_SAVED
    assert field["extra"]["label"].startswith("Link") and "value" not in field
    assert stop["options"] == [ud.USE_FORGE_INSTEAD]


def test_with_a_saved_token_only_the_link_is_asked_for(svc, monkeypatch):
    monkeypatch.setattr(fg, "token_configured", lambda _o: True)
    ud.record(svc, "figma")
    stop = ud.gate(svc.doc, svc.output_dir)
    assert fg.is_prompt(stop["text"]) and "already saved" in stop["text"]
    # the link still has its own field and button, so it never depends on the chat box; nothing is stored
    field = stop["secret"]
    assert field["skipSave"] is True and field["extra"]["label"].startswith("Link") and field["action"] == "Read design"
    assert fg.link_in(f"{field['saved']}: {URL}", [("smith", stop["text"])]) == URL


def test_a_link_counts_only_as_the_answer_to_the_request_for_one(svc, monkeypatch):
    monkeypatch.setattr(fg, "token_configured", lambda _o: False)
    ud.record(svc, "figma")
    asked = ud.gate(svc.doc, svc.output_dir)["text"]
    assert fg.link_in(URL, [("smith", asked)]) == URL
    assert fg.link_in(f"{fg.FIGMA_SAVED}: {URL}", [("assistant", asked)]) == URL, "what the field sends"
    assert fg.link_in(URL, [("smith", "Which language should the interface be in?")]) == ""
    assert fg.link_in("here is a link: https://example.com/x", [("smith", asked)]) == ""
    assert fg.link_in(URL, []) == ""
    # a way out
    assert ud.answer_in(ud.USE_FORGE_INSTEAD, [("smith", asked)]) == "forge"


# --------------------------------------------------------------------------- #
# Reading, checking, deciding
# --------------------------------------------------------------------------- #

def test_a_design_that_covers_the_requirements_lets_the_build_go_on(svc):
    ud.record(svc, "figma")
    out = fg.handle(svc, svc.output_dir, link=URL, connect=_connect, client=_model(approve_covered=True))
    assert out.proceed and "covers the application" in out.message["text"]
    assert ud.gate(BlueprintService.load(output_dir=svc.output_dir).doc, svc.output_dir) is None


def test_a_design_that_falls_short_stops_the_build_and_offers_the_three_ways_forward(svc):
    ud.record(svc, "figma")
    out = fg.handle(svc, svc.output_dir, link=URL, connect=_connect, client=_model(approve_covered=False))
    assert not out.proceed
    assert out.message["options"] == list(cv.OPTIONS) and out.message["status"] == "asked"
    assert "A manager can approve a request" in out.message["text"] and "Approve request" in out.message["text"]
    # asked again at the build's own gate, from what was stored, with no model call
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    again = ud.gate(doc, svc.output_dir)
    assert again["text"] == out.message["text"] and again["options"] == list(cv.OPTIONS)


def test_forge_filling_the_gaps_holds_the_design_as_evidence_and_goes_on(svc):
    ud.record(svc, "figma")
    fg.handle(svc, svc.output_dir, link=URL, connect=_connect, client=_model(False))
    report = ud.gate(BlueprintService.load(output_dir=svc.output_dir).doc, svc.output_dir)["text"]
    assert fg.choice_in(cv.FILL_WITH_FORGE, [("smith", report)]) == "fill"
    out = fg.handle(svc, svc.output_dir, choice="fill")
    assert out.proceed and "Forge designs" in out.message["text"]
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    assert doc["designSources"][0]["treatAs"] == "evidence" and ud.gate(doc, svc.output_dir) is None


def test_only_what_i_drew_holds_the_design_as_the_specification(svc):
    ud.record(svc, "figma")
    fg.handle(svc, svc.output_dir, link=URL, connect=_connect, client=_model(False))
    out = fg.handle(svc, svc.output_dir, choice="only")
    assert out.proceed and "exactly the screens in your design" in out.message["text"]
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    assert doc["designSources"][0]["treatAs"] == "specification" and ud.gate(doc, svc.output_dir) is None


def test_update_and_check_again_reads_the_file_again_and_can_now_pass(svc):
    ud.record(svc, "figma")
    reads = []
    fg.handle(svc, svc.output_dir, link=URL, connect=lambda o, u: (reads.append(u), _connect(o, u))[1],
              client=_model(False))
    out = fg.handle(svc, svc.output_dir, choice="update",
                    connect=lambda o, u: (reads.append(u), _connect(o, u))[1], client=_model(True))
    assert reads == [URL, URL], "the same file, read again"
    assert out.proceed and "covers the application" in out.message["text"]


def test_a_choice_counts_only_as_the_answer_to_the_report_just_shown(svc):
    assert fg.choice_in(cv.FILL_WITH_FORGE, [("smith", "Which language should the interface be in?")]) == ""
    assert fg.choice_in(cv.FILL_WITH_FORGE, []) == ""


def test_a_design_that_cannot_be_read_is_asked_for_again_with_the_reason(svc, monkeypatch):
    from services.smith.figma_connect import FigmaConnectError

    monkeypatch.setattr(fg, "token_configured", lambda _o: False)
    ud.record(svc, "figma")

    def refuse(_o, _u):
        raise FigmaConnectError("Figma auth: the token was refused")

    out = fg.handle(svc, svc.output_dir, link=URL, connect=refuse, client=_model(True))
    assert not out.proceed and fg.is_prompt(out.message["text"])
    assert "the token was refused" in out.message["text"] and out.message["secret"]["key"] == "FIGMA_TOKEN"


def test_when_the_check_cannot_be_made_the_design_is_still_used_and_the_person_is_told(svc):
    ud.record(svc, "figma")

    def down(**_):
        raise RuntimeError("provider down")

    out = fg.handle(svc, svc.output_dir, link=URL, connect=_connect, client=down)
    assert out.proceed and "could not check" in out.message["text"] and "starting point" in out.message["text"]


def test_a_design_named_in_the_brief_is_checked_when_figma_is_then_chosen(svc):
    _connect(svc.output_dir, URL)                      # connected by the opening brief
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    assert fg.unchecked(doc, svc.output_dir)
    ud.record(svc, "figma")
    out = fg.handle(svc, svc.output_dir, client=_model(True))
    assert out.proceed and not fg.unchecked(doc, svc.output_dir)


def test_the_router_recognises_the_figma_turns_before_the_generic_designer_answer():
    import inspect

    from routers import blueprint_generate

    chat = inspect.getsource(blueprint_generate.smith_chat)
    assert "ui_figma_gate.link_in(" in chat and "ui_figma_gate.choice_in(" in chat
    assert chat.index("ui_figma_gate.link_in(") < chat.index("ui_designer.answer_in(")


# --------------------------------------------------------------------------- #
# Everyone is asked, configured or not, and each option says what it needs
# --------------------------------------------------------------------------- #

def test_every_option_is_offered_even_when_nothing_is_configured(svc, monkeypatch):
    monkeypatch.setattr(ud, "configured", lambda _o: False)           # no UX Pilot key saved
    monkeypatch.setattr(fg, "token_configured", lambda _o: False)     # no Figma token saved
    assert not svc.doc.get("designSources")                           # and no design connected
    stop = ud.gate(svc.doc, svc.output_dir)
    assert ud.is_question(stop["text"]) and stop["options"] == ["Forge UI Designer", "UX Pilot", "Figma"]


def test_the_question_says_what_ux_pilot_and_figma_need(svc):
    q = ud.question(svc.doc)
    assert "If no UX Pilot key is saved yet, I will ask for it here in the chat" in q
    assert "only if you already have your screens designed in Figma" in q
    assert "paste the link to your Figma file here" in q and "I do not create one" in q


def test_ux_pilot_without_a_key_is_asked_for_it_in_the_chat(svc, monkeypatch):
    monkeypatch.setattr(ud, "configured", lambda _o: False)
    ud.record(svc, "uxpilot")
    stop = ud.gate(svc.doc, svc.output_dir)
    assert "UX Pilot API key" in stop["text"] and stop["secret"]["provider"] == "uxpilot"


def test_the_figma_request_says_a_design_must_already_exist_and_which_link_to_paste(svc, monkeypatch):
    monkeypatch.setattr(fg, "token_configured", lambda _o: False)
    ud.record(svc, "figma")
    text = ud.gate(svc.doc, svc.output_dir)["text"]
    assert "design you have already made in Figma" in text and "I do not create one" in text
    assert "choose Forge or UX Pilot instead" in text
    assert "single frame reads only that one screen" in text, "a node link reads one frame"


def test_a_design_held_as_the_specification_has_answered_who_designs_and_needs_no_check(svc, tmp_path):
    """DITANS (2026-10-30): 589 drawn screens, connected as the specification and
    converted, and the build stopped to ask who designs the screens — then to
    check the design against requirements written from it, by connecting it
    again as evidence."""
    svc.doc["designSources"] = [{"id": "FIGMA-001", "type": "figma", "fileKey": "abc123", "url": URL,
                                 "name": "Leave", "treatAs": "specification", "frames": []}]
    assert ud.chosen(svc.doc) == ud.FIGMA and not ud.undecided(svc.doc)
    assert ud.gate(svc.doc, tmp_path) is None
    svc.doc["designSources"][0]["treatAs"] = "evidence"     # evidence still asks
    assert ud.chosen(svc.doc) == "" and ud.gate(svc.doc, tmp_path) is not None

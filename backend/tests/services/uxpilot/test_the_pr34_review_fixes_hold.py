"""The faults found reviewing PR #34 (UX Pilot on smithv5), each held by a test.

- The loading screens' component is written with the frame, so a page Smith adds later
  (which completes no imports) never imports a component the app does not have.
- A UX Pilot key pasted into the chat box is scrubbed like any other key.
- "Who designs the screens?" hears a short answer, not only the button's words.
- `FORGE_UI_DESIGNER=uxpilot` with no key asks for the key instead of building quietly with Forge.
- The Figma coverage check's model calls are spend, recorded under a usage scope.
- A recompose of an unchanged page reuses the app run's drawing instead of paying for another.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services.smith import sync_app, ui_designer
from services.smith.secrets_scrub import MASK, scrub
from services.uxpilot import generate as g
from tests.services.uxpilot.test_uxpilot_react_reference import HTML, _doc, _Gateway

FOUNDATION = Path(__file__).resolve().parents[3] / "templates" / "app-foundation"


# --- the loading screens' component reaches an app built before them -------------

def test_every_loading_screen_import_is_a_file_the_refresh_writes():
    from services.blueprint.app_sdk import loading_module

    module = loading_module({"id": "PAGE-001", "name": "Cases", "pattern": "entity_list"})
    assert 'from "@/components/PageSkeleton"' in module
    assert "src/components/PageSkeleton.tsx" in sync_app.FRAME_FILES
    assert (FOUNDATION / "src/components/PageSkeleton.tsx").is_file()


def test_an_app_without_the_component_gets_it_on_its_next_sync(tmp_path):
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    changed = sync_app.refresh_frame(app, {"application": {"name": "Desk"}}, complete=False)
    assert "src/components/PageSkeleton.tsx" in changed
    assert "export function PageSkeleton" in (app / "src/components/PageSkeleton.tsx").read_text()


# --- a pasted key ---------------------------------------------------------------

def test_a_ux_pilot_key_pasted_into_the_chat_is_scrubbed():
    key = "ep_" + "Ab3dEf6hIj9kLmNo"
    said = scrub(f"here is my key {key} thanks")
    assert key not in said and MASK in said
    assert scrub("the step ep_short stays") == "the step ep_short stays"


# --- the designer question hears a short answer -----------------------------------

QUESTION = [("user", "build it"), ("smith", ui_designer.question({"requirements": [{"id": "R1"}]}))]
KEY_ASK = [("user", "UX Pilot"), ("smith", ui_designer.KEY_TEXT)]


@pytest.mark.parametrize("said,choice", [
    ("UX Pilot", "uxpilot"), ("Let's use UX Pilot", "uxpilot"), ("figma please", "figma"),
    ("go with the forge designer", "forge"), ("the first one", "forge"), ("option 2", "uxpilot"),
    ("not figma", ""), ("forge or figma?", ""), ("yes", ""),
    ("I want an inventory app with screens for stock, orders and suppliers and reports", ""),
])
def test_a_short_reply_naming_one_designer_is_the_answer(said, choice):
    assert ui_designer.answer_in(said, QUESTION) == choice


def test_a_designer_named_while_the_key_is_asked_for_is_a_change_of_mind():
    assert ui_designer.answer_in(ui_designer.USE_FORGE_INSTEAD, KEY_ASK) == "forge"
    assert ui_designer.answer_in("just use forge", KEY_ASK) == "forge"
    assert ui_designer.answer_in("figma then", KEY_ASK) == "figma"


def test_a_designer_named_out_of_the_blue_is_not_an_answer():
    assert ui_designer.answer_in("UX Pilot", [("user", "hi"), ("smith", "Hello, what shall we build?")]) == ""


# --- the platform's choice of UX Pilot asks for the key ----------------------------

def test_a_platform_that_chose_ux_pilot_asks_for_the_key(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_UI_DESIGNER", "uxpilot")
    monkeypatch.setattr(ui_designer, "configured", lambda out: False)
    defined = {"requirements": [{"id": "R1", "statement": "x"}]}
    asked = ui_designer.gate(defined, tmp_path)
    assert asked and ui_designer.is_key_prompt(asked["text"])
    assert ui_designer.gate({}, tmp_path) is None                      # nothing to build, nothing to ask
    monkeypatch.setattr(ui_designer, "configured", lambda out: True)
    assert ui_designer.gate(defined, tmp_path) is None
    monkeypatch.setattr(ui_designer, "configured", lambda out: False)
    chose_forge = {**defined, "application": {"uiDesigner": "forge"}}
    assert ui_designer.gate(chose_forge, tmp_path) is None             # the app's own choice outranks it


# --- the coverage check is spend ---------------------------------------------------

def test_the_figma_step_records_its_model_calls_under_a_scope(monkeypatch, tmp_path):
    from services import build_usage
    from services.smith import figma_gate

    flushed = []
    monkeypatch.setattr(build_usage, "_flush", lambda scope: flushed.append(scope))
    figma_gate.handle(SimpleNamespace(doc={}), tmp_path, choice="update")
    assert [s.agent for s in flushed] == ["figma_coverage"] and flushed[0].output_dir == str(tmp_path)


# --- a recompose reuses the app run's drawing ----------------------------------------

def test_a_recompose_of_an_unchanged_page_reuses_the_app_run(tmp_path):
    doc = _doc()
    gw = _Gateway()
    g.app_designs(doc, tmp_path, gateway=gw)                           # the build's one run
    assert gw.calls == ["start_design_agent"]
    svc = SimpleNamespace(doc=doc, output_dir=str(tmp_path))
    design = g.generate(svc, doc["pages"][0], gateway=gw)
    assert design.reused and design.html == HTML and gw.calls == ["start_design_agent"]


def test_a_redraw_the_person_asked_for_still_draws(tmp_path):
    doc = _doc()
    gw = _Gateway()
    g.app_designs(doc, tmp_path, gateway=gw)
    svc = SimpleNamespace(doc=doc, output_dir=str(tmp_path))
    # The stand-in answers in the app run's shape, so the single-page run it starts reads no
    # drawing; what matters here is that it was started — the person asked for it.
    with pytest.raises(g.GenerationFailed):
        g.generate(svc, doc["pages"][0], gateway=gw, feedback="make the table denser")
    assert gw.calls == ["start_design_agent", "start_design_agent"]

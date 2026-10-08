"""Who designs the screens — asked once at the approval gate, recorded where
code reads it and where people can cite it."""
from __future__ import annotations

import inspect

import pytest

from services.blueprint.service import BlueprintService
from services.smith import ui_designer as ud


@pytest.fixture()
def svc(tmp_path):
    """A definition as it stands at the approval gate: requirements, no pages.
    The define run is two nodes; pages arrive with the build."""
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Taskboard", domain="Operations")
    s.doc["requirements"] = [{"id": "REQ-001", "description": "User can add a task.",
                              "status": "VERIFIED"}]
    s.validate()
    return s


def test_asked_at_the_gate_where_requirements_exist_and_pages_do_not(svc):
    assert not svc.doc.get("pages")
    assert ud.undecided(svc.doc) is True
    assert ud.undecided({}) is False
    assert ud.undecided({"requirements": [], "pages": []}) is False
    # A built application re-approved is asked too, once.
    assert ud.undecided({"pages": [{"id": "PAGE-001", "name": "x"}]}) is True
    svc.doc["application"]["uiDesigner"] = "forge"
    assert ud.undecided(svc.doc) is False and ud.chosen(svc.doc) == "forge"


def test_the_question_names_both_designers_and_the_cost(svc):
    q = ud.question(svc.doc)
    assert ud.is_question(q)
    assert "Forge UI Designer" in q and "UX Pilot" in q
    assert "one UX Pilot run draws every screen" in q and "9 UX Pilot credits per screen" in q
    assert "per page" not in q, "it is one run for the application now, not a credit per page"
    assert list(ud.OPTIONS) == ["Forge UI Designer", "UX Pilot"]
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Tasks", "route": "/tasks", "purpose": "x"}]
    assert "(1 screen)" in ud.question(svc.doc)


def test_an_option_counts_only_as_the_answer_to_the_question_just_asked(svc):
    q = ud.question(svc.doc)
    assert ud.answer_in("UX Pilot", [("smith", q)]) == "uxpilot"
    assert ud.answer_in("forge ui designer", [("assistant", q)]) == "forge"
    assert ud.answer_in("uxpilot", [("assistant", q)]) == "uxpilot"
    # The words alone are not a decision.
    assert ud.answer_in("UX Pilot", [("assistant", "Which language should the interface be in?")]) == ""
    assert ud.answer_in("UX Pilot", []) == ""
    assert ud.answer_in("UX Pilot", [("smith", q), ("user", "later"), ("smith", "Done.")]) == ""
    assert ud.answer_in("make it blue", [("smith", q)]) == ""


def test_recording_writes_the_fact_and_the_citation(svc):
    said = ud.record(svc, "uxpilot")
    assert "UX Pilot" in said
    reloaded = BlueprintService.load(output_dir=svc.output_dir)
    assert reloaded.doc["application"]["uiDesigner"] == "uxpilot"
    rows = [d for d in reloaded.doc["decisions"] if "UX Pilot" in d["decision"]]
    assert rows and rows[0]["source"] == "user" and rows[0]["approvedBy"] == "user"
    assert rows[0]["status"] == "APPROVED" and rows[0]["binding"] is True
    # Changing one's mind is a supersession, not a duplicate.
    ud.record(svc, "forge")
    again = BlueprintService.load(output_dir=svc.output_dir)
    assert again.doc["application"]["uiDesigner"] == "forge"
    rows = [d for d in again.doc["decisions"] if "designed by" in d["decision"]]
    live = [d for d in rows if d.get("status") != "DEPRECATED"]
    assert len(rows) == 2 and len(live) == 1
    assert live[0]["decision"].endswith("Forge UI Designer.")
    assert live[0]["supersedes"] == next(d["id"] for d in rows if d["status"] == "DEPRECATED")
    # The same answer again is not a third row.
    ud.record(svc, "forge")
    assert len([d for d in svc.doc["decisions"] if "designed by" in d["decision"]]) == 2
    with pytest.raises(ValueError):
        ud.record(svc, "figma")


def test_every_build_passes_the_designer_gate():
    """UX Pilot's drawing now guides each page's code, so who designs is a real choice: every
    build starts through `_run_dag`, which stops to ask it, and the answer is recognised
    before the generic approval handling."""
    from routers import blueprint_generate

    assert "ui_designer.gate(" in inspect.getsource(blueprint_generate._run_dag)
    chat = inspect.getsource(blueprint_generate.smith_chat)
    assert "ui_designer.answer_in(" in chat and "ui_designer.key_saved_in(" in chat


def test_an_undecided_application_is_asked_and_a_decided_one_is_not(svc, monkeypatch):
    monkeypatch.delenv("FORGE_UI_DESIGNER", raising=False)
    stop = ud.gate(svc.doc, svc.output_dir)
    assert stop and ud.is_question(stop["text"]) and stop["options"] == list(ud.OPTIONS)
    assert stop["status"] == "asked"
    svc.doc["application"]["uiDesigner"] = "forge"
    assert ud.gate(svc.doc, svc.output_dir) is None


def test_an_operators_platform_default_is_not_asked_again(svc, monkeypatch):
    monkeypatch.setenv("FORGE_UI_DESIGNER", "uxpilot")
    monkeypatch.setattr(ud, "configured", lambda _o: True)
    assert ud.gate(svc.doc, svc.output_dir) is None


def test_choosing_ux_pilot_without_a_key_asks_for_the_key_in_the_chat(svc, monkeypatch):
    monkeypatch.setattr(ud, "configured", lambda _o: False)
    svc.doc["application"]["uiDesigner"] = "uxpilot"
    stop = ud.gate(svc.doc, svc.output_dir)
    assert stop and ud.is_key_prompt(stop["text"])
    assert stop["secret"] == ud.SECRET_FIELD
    assert stop["options"] == [ud.USE_FORGE_INSTEAD], "a way out that needs no key"
    monkeypatch.setattr(ud, "configured", lambda _o: True)
    assert ud.gate(svc.doc, svc.output_dir) is None


def test_the_key_request_names_the_field_and_never_carries_a_key():
    prompt = ud.key_prompt()
    assert prompt["secret"] == {"provider": "uxpilot", "key": "UXPILOT_API_KEY",
                                "label": "UX Pilot API key", "placeholder": "ep_...",
                                "saved": ud.KEY_SAVED}
    # A descriptor of a field to fill, never a value; and the words promise the key stays out of the chat.
    assert "value" not in prompt["secret"]
    assert "never written into this conversation" in ud.KEY_TEXT
    from services.uxpilot.credentials import looks_like_key

    assert not looks_like_key(str(prompt))


def test_the_saved_key_and_the_forge_chip_count_only_after_the_key_request():
    prompt = ud.key_prompt()["text"]
    assert ud.key_saved_in(ud.KEY_SAVED, [("smith", prompt)]) is True
    assert ud.key_saved_in(ud.KEY_SAVED, [("smith", "Anything else?")]) is False
    assert ud.key_saved_in("key saved please", [("smith", prompt)]) is False
    assert ud.answer_in(ud.USE_FORGE_INSTEAD, [("smith", prompt)]) == "forge"
    assert ud.answer_in("UX Pilot", [("smith", prompt)]) == ""
    assert ud.answer_in(ud.USE_FORGE_INSTEAD, [("smith", "Anything else?")]) == ""


def test_the_field_descriptor_is_what_the_transcript_keeps():
    """The message's metadata is persisted with the conversation, so `secret` must be allowed
    through - and it is only the field's name, which is why that is safe."""
    from routers import blueprint_generate

    assert '"secret"' in inspect.getsource(blueprint_generate)

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
    assert "per page the build defines" in q and "credit" in q
    assert list(ud.OPTIONS) == ["Forge UI Designer", "UX Pilot"]
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Tasks", "route": "/tasks", "purpose": "x"}]
    assert "(1 page)" in ud.question(svc.doc)


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


def test_the_gate_asks_before_building_and_refuses_uxpilot_without_a_key():
    """The router's approved path consults the question before the graph, and
    the answer path resumes the build the approval asked for."""
    from routers import blueprint_generate

    src = inspect.getsource(blueprint_generate.smith_chat)
    approved_at = src.index("if req.approved:")
    assert "ui_designer.undecided(svc.doc)" in src[approved_at:approved_at + 2000]
    assert "ui_designer.configured(output_dir)" in src[approved_at:approved_at + 2000]
    assert src.index("ui_designer.answer_in(") < approved_at
    answer_at = src.index("ui_designer.answer_in(")
    assert "approved=True" in src[answer_at:answer_at + 1500]


def test_the_configure_text_never_asks_for_the_key_itself():
    assert "Settings" in ud.CONFIGURE_TEXT and "UXPILOT_API_KEY" in ud.CONFIGURE_TEXT
    assert "never take the key" in ud.CONFIGURE_TEXT

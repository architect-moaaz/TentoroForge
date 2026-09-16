"""The ask survives the question Smith asks about it, and reaches the composer.

"Add a simple arithmetic calculator and it should not store the values" was
answered with a chip, "A new page at /calculator". That label was the whole of
the next turn: it became the page's purpose, and the composer — briefed from
the page contract and the application's entities — returned a workforce
dashboard of nurse counts and ward capacities. Twice: the correction could not
reach it either, because a composition carried no brief.
"""

from __future__ import annotations

import json
from pathlib import Path

from services.smith import pending_ask


# --- the ask between two turns ---------------------------------------------

def test_an_ask_is_kept_for_the_turn_that_answers_it(tmp_path):
    assert pending_ask.take(tmp_path) == ""            # nothing recorded
    pending_ask.remember(tmp_path, "add a simple arithmetic calculator")
    assert (tmp_path / pending_ask.PENDING_PATH).is_file()
    assert pending_ask.take(tmp_path) == "add a simple arithmetic calculator"
    # TAKEN, NOT READ: an ask that outlived its answer would qualify every
    # later turn.
    assert pending_ask.take(tmp_path) == ""
    assert not (tmp_path / pending_ask.PENDING_PATH).exists()


def test_recording_nothing_records_nothing_and_a_broken_note_is_no_note(tmp_path):
    pending_ask.remember(tmp_path, "   ")
    assert not (tmp_path / pending_ask.PENDING_PATH).exists()
    (tmp_path / ".forge").mkdir()
    (tmp_path / pending_ask.PENDING_PATH).write_text("{ not json")
    assert pending_ask.take(tmp_path) == ""             # and it is cleared
    assert not (tmp_path / pending_ask.PENDING_PATH).exists()


def test_the_whole_ask_is_what_was_asked_then_what_was_answered():
    assert pending_ask.joined("add a calculator", "A new page at /calculator") == \
        "add a calculator\n\nA new page at /calculator"
    assert pending_ask.joined("", "add a calculator") == "add a calculator"
    assert pending_ask.joined("add a calculator", "") == "add a calculator"
    # A resent message must not appear twice.
    assert pending_ask.joined("add a calculator", "add a calculator") == "add a calculator"


def test_a_turn_carries_the_ask_from_the_turn_that_asked(tmp_path):
    """The session's own contract: a clarification keeps the ask, and the next
    turn hands the whole of it to the seam."""
    from services.smith_session import SmithSession, TurnResult

    asked_with: list[str] = []

    def _understand(message, ctx, **kw):
        if "calculator" in message and "/calculator" not in message:
            return {"clarification_needed": "Where should it live?",
                    "clarification_options": ["A new page at /calculator"]}
        return {"verb": "compose_route", "route": "/calculator"}

    def _session():
        s = SmithSession(project_id="p1", output_dir=str(tmp_path),
                         guards_fn=lambda *a, **kw: [],
                         understand_ask_fn=_understand,
                         iteration_move_fn=lambda *a, **kw: None)
        s._compose = lambda verb, understanding, ask: (          # noqa: ARG005
            asked_with.append(ask) or TurnResult(status="resolved", answer="done"))
        return s

    first = _session().run_iteration(user_message="add a simple arithmetic calculator")
    assert first.status == "asked" and asked_with == []
    assert json.loads((tmp_path / pending_ask.PENDING_PATH).read_text())["ask"] == \
        "add a simple arithmetic calculator"

    second = _session().run_iteration(user_message="A new page at /calculator")
    assert second.status == "resolved"
    assert asked_with == ["add a simple arithmetic calculator\n\nA new page at /calculator"]
    # Answered, so it is not carried into anything after it.
    assert not (tmp_path / pending_ask.PENDING_PATH).exists()
    _session().run_iteration(user_message="A new page at /calculator")
    assert asked_with[-1] == "A new page at /calculator"


# --- what the composer is told ---------------------------------------------

def _app(tmp_path) -> Path:
    root = tmp_path / "app"
    (root / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "contracts" / "app-plan.json").write_text(json.dumps(
        {"app_name": "Nurse Roster", "description": "Register nurses."}))
    return root


def test_a_screen_about_no_record_is_not_briefed_as_a_list_of_records(tmp_path):
    from services.a2ui_authority import build_requirement

    page = {"id": "PAGE-006", "route": "/calculator", "name": "Calculator",
            "purpose": "add a simple arithmetic calculator and it should not store the values",
            "primaryTasks": ["Add, subtract, multiply and divide two numbers"]}
    req = build_requirement(_app(tmp_path), "", "/calculator", contract=page,
                            page_id="PAGE-006",
                            brief="I asked for a simple arithmetic calculator, not one about nursing")

    assert "self-contained tool" in req
    assert "shows many records of one kind" not in req     # the collection job
    assert "not backed by the application's records" in req
    assert "Every number, row and category you show must come from the" not in req
    # The screen's own brief, and the words that asked for it.
    assert "WHAT THIS SCREEN IS FOR" in req
    assert "add a simple arithmetic calculator and it should not store the values" in req
    assert "- Add, subtract, multiply and divide two numbers" in req
    assert "WHAT THE PERSON ASKED FOR, IN THEIR OWN WORDS" in req
    assert "not one about nursing" in req


def test_the_domain_listing_does_not_contradict_the_job(tmp_path):
    """The screen still SEES the entities — it may run one of their workflows —
    but is not told that everything on it must come from them, which is the
    instruction a calculator was composed out of nurses under."""
    from services.a2ui_authority import build_domain_context, is_standalone

    reg = {"entities": {"Nurse": {"columns": [{"name": "id"}, {"name": "name"}]}}, "workflows": []}
    tool = build_domain_context(_app(tmp_path), reg, "PAGE-006", standalone=True)
    assert "This screen is not about them" in tool and "Nurse" in tool
    assert "Every number and every row on this screen comes from these" not in tool

    records = build_domain_context(_app(tmp_path), reg, "PAGE-002")
    assert "Every number and every row on this screen comes from these" in records

    assert is_standalone("", {"route": "/calculator"}) is True
    assert is_standalone("entity_list", {}) is False
    assert is_standalone("", {"data": {"primaryEntity": "ENTITY-001"}}) is False
    assert is_standalone("", {"data": {"supportingEntities": ["ENTITY-002"]}}) is False


def test_a_screen_about_records_keeps_the_brief_it_always_had(tmp_path):
    from services.a2ui_authority import build_requirement

    page = {"id": "PAGE-002", "route": "/master-data", "purpose": "Every nurse.",
            "pattern": "entity_list", "data": {"primaryEntity": "ENTITY-001"}}
    req = build_requirement(_app(tmp_path), "entity_list", "/master-data",
                            contract=page, page_id="PAGE-002")
    assert "shows many records of one kind" in req
    assert "Every number, row and category you show must come from the" in req
    assert "self-contained tool" not in req
    assert "Every nurse." in req
    # No brief given, so nothing claims the person said anything.
    assert "IN THEIR OWN WORDS" not in req


def test_an_entity_page_with_no_declared_pattern_is_still_about_its_records(tmp_path):
    from services.a2ui_authority import build_requirement

    page = {"id": "PAGE-003", "route": "/wards", "purpose": "Wards.",
            "data": {"primaryEntity": "ENTITY-002"}}
    req = build_requirement(_app(tmp_path), "", "/wards", contract=page, page_id="PAGE-003")
    assert "self-contained tool" not in req
    assert "Every number, row and category you show must come from the" in req


def test_the_composition_hands_the_turns_words_to_the_composer(tmp_path):
    """compose_route sets the brief on the task it runs; without it the second
    attempt at a page is the identical prompt."""
    from services.blueprint.service import BlueprintService
    from services.smith import compose

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Nurse Roster", domain="health")
    specs = []

    def _run(spec):
        specs.append(spec)
        raise compose.ComposeError("stop here")

    try:
        compose.compose_route(svc, "/calculator", executor=_run,
                              request="add a simple arithmetic calculator\n\nA new page at /calculator")
    except compose.ComposeError:
        pass
    assert specs and specs[0].brief == \
        "add a simple arithmetic calculator\n\nA new page at /calculator"
    # And the page the composition created says what it is for, on one line.
    page = next(p for p in svc.doc["pages"] if p["route"] == "/calculator")
    assert page["purpose"] == "add a simple arithmetic calculator A new page at /calculator"

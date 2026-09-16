"""No question is homework: a reply that asks carries what can be clicked.

Two dead ends. A missing fact was reported in the contract's own words — "I
can do that, I just need entity and field" — leaving the person to supply a
value the Blueprint already holds, spelled the way Smith spells it. And an
unrecognised ask was answered with all thirty capabilities: a wall to read
with nothing to click.
"""

from __future__ import annotations

import pytest

from services.smith import capabilities as cap
from services.smith.slot_options import ASKS, MAX_OPTIONS, ask_for, options_for

DOC = {
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Nurse", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "fullName", "type": "string"},
            {"name": "createdAt", "type": "timestamp"}]},
        {"id": "ENTITY-002", "name": "Ward", "fields": [{"name": "name", "type": "string"}]},
        {"id": "ENTITY-003", "name": "Gone", "status": "DEPRECATED", "fields": []},
    ]},
    "pages": [{"route": "/master-data"}, {"route": "/old", "status": "DEPRECATED"}],
    "workflows": [{"name": "Register Nurse"}],
    "businessRules": [{"name": "Years Non-Negative"}],
    "requirements": [{"id": "REQ-001", "description": "Register nurses with their details."}],
    "apis": [{"method": "GET", "path": "/api/data/nurses"}],
    "integrations": [{"name": "SendGrid"}],
}


def test_a_missing_fact_is_asked_for_with_the_answers_the_blueprint_holds():
    assert options_for("entity", DOC) == ["Nurse", "Ward"]          # retired ones are not offered
    assert options_for("route", DOC) == ["/master-data"]
    assert options_for("workflow", DOC) == ["Register Nurse"]
    assert options_for("rule", DOC) == ["Years Non-Negative"]
    assert options_for("api", DOC) == ["GET /api/data/nurses"]
    assert options_for("integration", DOC) == ["SendGrid"]
    assert options_for("requirement", DOC) == ["REQ-001 — Register nurses with their details."]


def test_the_boxes_offered_are_the_ones_on_the_record_they_named():
    # Nothing to offer until the record is known — so that is asked first.
    assert options_for("field", DOC, {}) == []
    # The key and the timestamps are the application's, not the person's.
    assert options_for("field", DOC, {"entity": "nurse"}) == ["fullName"]


def test_the_question_is_asked_in_their_words_not_the_contracts():
    question, choices = ask_for(["entity", "field"], DOC, {})
    assert question == "Which record?" and choices == ["Nurse", "Ward"]
    assert "entity" not in question and "field" not in question
    # The one that can be answered with a click is asked first.
    question, choices = ask_for(["change", "workflow"], DOC, {})
    assert question == ASKS["workflow"] and choices == ["Register Nurse"]


def test_a_genuinely_open_question_is_left_open():
    question, choices = ask_for(["new_value"], DOC, {})
    assert question == "What should it say instead?" and choices == []
    assert ask_for([], DOC, {}) == ("I need one more detail.", [])


def test_a_long_list_is_cut_rather_than_becoming_a_directory():
    many = {"data": {"entities": [{"name": f"E{i}", "fields": []} for i in range(12)]}}
    assert len(options_for("entity", many)) == MAX_OPTIONS


def test_an_unrecognised_ask_offers_the_closest_few_as_sentences():
    close = cap.nearest("make the colours nicer")
    assert close and close[0][0] == "restyle"
    assert close[0][1] == "change the theme colour to green"       # a sentence, not a verb name
    assert len(cap.nearest("the app should email someone")) <= 3
    # An ask with nothing in common offers nothing rather than guessing.
    assert cap.nearest("refactor the codebase") == []
    assert cap.nearest("") == []


def test_an_inflection_is_the_same_word():
    """Matching "change" to "changes" by prefix while counting them as two
    words made "changes" look unique to one verb, and ranked `revert` above
    `edit_access` for "change who can delete a nurse"."""
    assert cap._stem("changes") == cap._stem("change")
    assert cap._words("colours") == cap._words("colour")
    assert cap._words("registration") != set()      # a long word keeps its shape
    assert cap._stem("less") == "less"              # not trimmed below the floor
    assert cap.nearest("change who can delete a nurse")[0][0] == "edit_access"


def test_the_turn_asks_with_options_instead_of_naming_slots(tmp_path):
    from services.blueprint.service import BlueprintService
    from services.smith_session import SmithSession

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Roster", domain="health")
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                     "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}]}
    svc.save()

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": "add_field", "field": {"name": "phone"}},
        iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="add a phone number")
    assert result.status == "asked"
    assert result.answer == "Which record?" and result.options == ["Nurse"]
    assert "entity" not in result.answer


def test_the_turn_offers_the_closest_asks_when_the_verb_is_unknown(tmp_path):
    from services.smith_session import SmithSession

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": "make_it_nicer"},
        iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="make the colours nicer")
    assert result.status == "needs_user"
    assert "Did you mean one of these?" in result.answer
    assert "change the theme colour to green" in result.options
    assert result.options[-1] == "Something else"
    # The thirty-item wall is gone from this reply.
    assert "**The screens**" not in result.answer


def test_a_state_machines_name_is_not_an_answer():
    """"State: BLUEPRINT_REVIEW" tells a person nothing about what to do."""
    from routers.blueprint_generate import _status_report

    said = _status_report({"state": "BLUEPRINT_REVIEW", "requirements": [1] * 12,
                           "pages": [1] * 5, "decisions": []})
    assert "BLUEPRINT_REVIEW" not in said and "State:" not in said
    assert "waiting for you to read" in said and "Approve and build" in said
    assert "thing(s) it has to do" in said and "screen(s) described" in said

    empty = _status_report({})
    assert "DISCOVERY" not in empty and "Nothing is written down yet" in empty


def test_a_change_is_confirmed_in_the_words_on_the_screen(tmp_path):
    """"Changed /master-data — previous state → requested change" is the shape
    of a sentence with nothing in it."""
    import subprocess

    from services.smith_session import IterationMove, SmithSession

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "page.json").write_text('{"label": "Delete"}')
    for cmd in (["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"]):
        subprocess.run(cmd, cwd=tmp_path, check=True)

    def _move(understanding, output_dir):
        (tmp_path / "src" / "page.json").write_text('{"label": "Archive"}')
        return IterationMove(move_name="rename", touched_paths=["src/page.json"])

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {
            "verb": "rename", "target_file": "src/page.json",
            "element_label": "Delete", "new_value": "Archive",
            "screen": "x", "current_behavior": "", "desired_behavior": ""},
        iteration_move_fn=_move)
    result = session.run_iteration(user_message="change Delete to Archive")
    assert "previous state" not in result.answer and "requested change" not in result.answer
    assert "**Delete**" in result.answer and "**Archive**" in result.answer


def test_a_screen_named_in_the_message_is_not_asked_for_again():
    """"Delete the Master Data page" came back as remove_page with the screen
    in `target_file` and `route` empty, so the turn asked which screen — about
    a screen the understanding had already named."""
    from services.smith.slot_options import fill_from
    from services.smith.understand_ask import _is_route

    # The two names for one fact are reconciled in the understanding itself.
    assert _is_route("/master-data") and not _is_route("src/schemas/x.json")
    assert not _is_route("master-data") and not _is_route("/x.json")

    doc = {"pages": [{"route": "/master-data", "name": "Master Data"},
                     {"route": "/nurse-registration", "name": "Nurse Registration"}],
           "data": {"entities": [{"name": "Nurse", "fields": []},
                                 {"name": "Ward", "fields": []}]}}
    # Named by its title, which is not the option text.
    assert fill_from(["route"], "delete the Master Data page", doc) == {"route": "/master-data"}
    # Named by its route.
    assert fill_from(["route"], "the /nurse-registration screen is empty", doc) \
        == {"route": "/nurse-registration"}
    # Named among the records.
    assert fill_from(["entity"], "add a notes box to wards", doc) == {"entity": "Ward"}
    # Nothing named, or two things named: a real question either way.
    assert fill_from(["route"], "delete that page", doc) == {}
    assert fill_from(["entity"], "add notes to nurses and wards", doc) == {}

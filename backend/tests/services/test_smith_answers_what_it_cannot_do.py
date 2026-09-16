"""The asks that reach nothing now land somewhere and hand over the next move.

Eight things people ask for cannot be done. Each used to land on the verb that
looked nearest — "delete the Wards page" read as removing a control — or on "I
did not recognise that as something I can do", which is true and useless. Two
of the eight stopped being limits: undo exists, and "build it" builds.
"""

from __future__ import annotations

from services.smith.limits import answer, cannot
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP

DOC = {
    "pages": [{"id": "PAGE-001", "route": "/wards", "name": "Wards",
               "data": {"primaryEntity": "ENTITY-002"}}],
    "data": {"entities": [{"id": "ENTITY-002", "name": "Ward", "fields": []}]},
}


def test_each_refusal_is_a_verb_the_classifier_can_reach():
    for verb in ("remove_page", "rename_entity", "change_field_type", "edit_api", "reorder"):
        assert verb in REQUIRED_BY_VERB and verb in VERB_HELP, verb
        assert cannot(verb)
    assert not cannot("remove") and not cannot("rename_field") and not cannot("revert")


def test_a_screen_cannot_go_but_the_menu_and_the_record_can():
    said, options = answer("remove_page", {"route": "/wards"}, DOC)
    assert "cannot remove **Wards**" in said and "put it back" in said
    assert options == ["Take Wards off the menu",
                       "Retire the Ward record and everything built on it"]


def test_a_record_cannot_be_renamed_but_the_words_people_read_can():
    said, options = answer("rename_entity", {"entity": "Nurse", "new_value": "Colleague"}, DOC)
    assert "cannot rename the **Nurse** record" in said
    assert options == ["We say “Colleague”, never “Nurse”"]


def test_a_box_cannot_change_type_and_the_way_round_names_its_cost():
    said, options = answer("change_field_type", {"entity": "Nurse", "field": {"name": "phone"}}, DOC)
    assert "cannot change what kind of value **phone** holds" in said
    assert "loses what is in that box" in said
    assert options == ["Remove phone from Nurse", "Leave it as it is"]


def test_an_endpoint_is_added_or_removed_not_edited():
    said, options = answer("edit_api", {"api": "GET /api/data/wards"}, DOC)
    assert "not changed in place" in said and options[0] == "Remove GET /api/data/wards"


def test_a_screen_is_laid_out_again_rather_than_nudged():
    said, options = answer("reorder", {"route": "/wards"}, DOC)
    assert "cannot move things around" in said
    assert options == ["Lay /wards out again",
                       "Compose /wards with the most important thing first"]


def test_a_verb_that_is_not_a_refusal_answers_nothing_here():
    assert answer("restyle", {"change": "green"}, DOC) == ("", [])


def test_the_turn_says_why_and_offers_the_nearest_thing(tmp_path):
    import json

    from services.smith_session import SmithSession

    forge = tmp_path / ".forge" / "blueprint"
    forge.mkdir(parents=True)
    (forge / "current.json").write_text(json.dumps(DOC))

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": "remove_page", "route": "/wards"},
        iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="delete the Wards page")
    assert result.status == "needs_user"
    assert "cannot remove **Wards**" in result.answer
    assert "Take Wards off the menu" in result.options

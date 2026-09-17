"""The asks that reach nothing now land somewhere and hand over the next move.

Eight things people ask for cannot be done. Each used to land on the verb that
looked nearest — "delete the Wards page" read as removing a control — or on "I
did not recognise that as something I can do", which is true and useless.
Three of the eight have stopped being limits: undo exists, "build it" builds,
and a screen can be removed (`test_smith_removes_a_page`).
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
    for verb in ("rename_entity", "change_field_type", "edit_api", "reorder"):
        assert verb in REQUIRED_BY_VERB and verb in VERB_HELP, verb
        assert cannot(verb)
    assert not cannot("remove") and not cannot("rename_field") and not cannot("revert")
    # It was the fifth of these until a screen could actually be removed.
    assert "remove_page" in REQUIRED_BY_VERB and not cannot("remove_page")


def test_a_screen_is_no_longer_answered_here_at_all():
    assert answer("remove_page", {"route": "/wards"}, DOC) == ("", [])


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
    """`reorder` stands in for what `remove_page` used to demonstrate here."""
    import json

    from services.smith_session import SmithSession

    forge = tmp_path / ".forge" / "blueprint"
    forge.mkdir(parents=True)
    (forge / "current.json").write_text(json.dumps(DOC))

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": "reorder", "route": "/wards"},
        iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="move the chart above the table on /wards")
    assert result.status == "needs_user"
    assert "cannot move things around on **/wards**" in result.answer
    assert "Lay /wards out again" in result.options

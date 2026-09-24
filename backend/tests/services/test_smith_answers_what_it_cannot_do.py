"""The asks that reach nothing now land somewhere and hand over the next move.

Eight things people ask for cannot be done. Each used to land on the verb that
looked nearest — "delete the Wards page" read as removing a control — or on "I
did not recognise that as something I can do", which is true and useless.
Three of the eight have stopped being limits: undo exists, "build it" builds,
and a screen can be removed (`test_smith_removes_a_page`).
"""

from __future__ import annotations

from services.smith.limits import answer
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP

DOC = {
    "pages": [{"id": "PAGE-001", "route": "/wards", "name": "Wards",
               "data": {"primaryEntity": "ENTITY-002"}}],
    "data": {"entities": [{"id": "ENTITY-002", "name": "Ward", "fields": []}]},
}


def test_the_three_refusals_are_made_now_and_reorder_is_the_one_left():
    """`write_section` closed rename_entity, change_field_type and edit_api;
    `reorder` on a tree-laid page is the last honest refusal."""
    from services.smith4.verbs import PERFORM, honest_refusal, section_write, tree_edit
    for verb in ("rename_entity", "change_field_type", "edit_api"):
        assert verb in REQUIRED_BY_VERB and "Cannot be done" not in VERB_HELP[verb], verb
        assert PERFORM[verb] is section_write
    assert PERFORM["reorder"] is tree_edit and honest_refusal is not None
    assert answer("reorder", {"route": "/wards"}, DOC)[0]


def test_a_screen_is_no_longer_answered_here_at_all():
    assert answer("remove_page", {"route": "/wards"}, DOC) == ("", [])


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

    from tests.services._front_door import SmithSession

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

"""The words on the screen are in the tree; the person should not have to spell them.

`rename` and `remove` matched by string equality, so "remove the delete thing"
and "remove the Delete  button" both reached "I looked for it and could not
find it" while a control called Delete sat in the tree. That is string matching
delegated to the user.

A heuristic that ASKS, not one that guesses: the moment two controls answer to
the same words, neither is chosen — both are offered, with where they live,
because Delete on the list and Delete on the record are different buttons.
"""

from __future__ import annotations

from services.smith.labels import collect, describe, normalise, resolve

DOC = {
    "pages": [{"id": "PAGE-001", "route": "/master-data", "name": "Master Data"},
              {"id": "PAGE-002", "route": "/nurse-registration", "name": "Nurse Registration"}],
    "pageLayouts": [
        {"page": "PAGE-001", "root": {"type": "Stack", "props": {}, "children": [
            {"type": "Button", "props": {"label": "Add Nurse"}, "children": []},
            {"type": "Table", "props": {
                "columns": [{"key": "name", "label": "Name"}],
                "rowActions": [{"label": "Delete", "workflow": "FLOW-003"},
                               {"label": "Edit", "workflow": "FLOW-002"}]}, "children": []}]}},
        {"page": "PAGE-002", "root": {"type": "Stack", "props": {}, "children": [
            {"type": "Heading", "props": {"content": "Register a nurse"}, "children": []},
            {"type": "Form", "props": {"submitLabel": "Save",
                                       "fields": [{"name": "name", "label": "Name"}]}, "children": []},
            {"type": "Button", "props": {"label": "Delete"}, "children": []}]}},
        {"page": "PAGE-002", "status": "SUPERSEDED", "root": {"type": "Button",
                                                              "props": {"label": "Ghost"}, "children": []}},
    ],
}


def test_every_visible_label_is_found_with_where_it_lives():
    rows = collect(DOC)
    found = {(r["text"], r["kind"], r["route"]) for r in rows}
    assert ("Add Nurse", "button", "/master-data") in found
    assert ("Delete", "row action", "/master-data") in found
    assert ("Name", "column", "/master-data") in found
    assert ("Name", "field", "/nurse-registration") in found
    assert ("Register a nurse", "heading", "/nurse-registration") in found
    # A superseded layout is not on any screen.
    assert not any(r["text"] == "Ghost" for r in rows)


def test_the_words_are_matched_however_they_were_typed():
    assert resolve(DOC, "Add Nurse")["text"] == "Add Nurse"
    assert resolve(DOC, "add  nurse")["text"] == "Add Nurse"
    assert resolve(DOC, "Add-Nurse!")["text"] == "Add Nurse"
    # "the delete thing" contains the label; "Delete" is contained by nothing
    # else on that one screen.
    assert resolve(DOC, "the delete button", "/nurse-registration")["text"] == "Delete"
    assert normalise("Add  Nurse!") == "add nurse"


def test_two_controls_with_the_same_words_are_asked_about_not_guessed():
    got = resolve(DOC, "Delete")
    assert "text" not in got
    said = [describe(c) for c in got["candidates"]]
    assert "“Delete” — the row action on Master Data" in said
    assert "“Delete” — the button on Nurse Registration" in said


def test_naming_the_screen_settles_it_without_a_question():
    assert resolve(DOC, "Delete", "/master-data")["text"] == "Delete"
    assert resolve(DOC, "Delete", "Master Data")["text"] == "Delete"     # by name too
    assert resolve(DOC, "Delete", "/master-data")["matched"][0]["kind"] == "row action"


def test_nothing_like_it_is_nothing_rather_than_the_nearest_thing():
    assert resolve(DOC, "Archive") == {}
    assert resolve(DOC, "") == {}
    assert resolve({}, "Delete") == {}


def test_the_turn_asks_which_one_instead_of_changing_the_wrong_control(tmp_path):
    import json

    from tests.services._front_door import SmithSession

    forge = tmp_path / ".forge" / "blueprint"
    forge.mkdir(parents=True)
    (forge / "current.json").write_text(json.dumps(DOC))

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {
            "verb": "remove", "target_file": "", "element_label": "the delete thing"},
        iteration_move_fn=lambda *a, **kw: None)

    # No screen named: the screens are offered rather than asked for.
    result = session.run_iteration(user_message="remove the delete thing")
    assert result.status == "asked" and result.answer == "Which screen?"
    assert result.options == ["/master-data", "/nurse-registration"]


def test_the_turn_offers_what_is_on_the_screen_when_the_words_are_not_there(tmp_path):
    import json

    from tests.services._front_door import SmithSession

    forge = tmp_path / ".forge" / "blueprint"
    forge.mkdir(parents=True)
    (forge / "current.json").write_text(json.dumps(DOC))

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {
            "verb": "remove", "target_file": "/master-data", "element_label": "Archive"},
        iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="remove the archive button")
    assert result.status == "asked"
    assert "could not find “Archive”" in result.answer and "changed nothing" in result.answer
    assert "Add Nurse" in result.options and "Delete" in result.options

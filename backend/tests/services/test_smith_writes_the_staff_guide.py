"""The short guide an owner gives their staff (§06).

The phrasebook marks "can you write me a one-page guide for the team?" as
reaching nothing, in the section where the app stops being the owner's toy and
is handed to the people who have to use it — and the two asks recorded right
after it, "my staff say the form takes too long" and "two people can't find the
search", are what the missing guide costs.

The correctness claim these tests exist for is a single one: the guide is
derived from the screens that COMPOSED, never from the ones that were only
asked for. A guide that names a screen the build failed to produce sends the
reader looking for something that is not there, and they then stop believing
the parts that are true. It is structural, not a pass over the finished prose —
so it is tested where it lives, in what the writer is handed.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from services.blueprint.service import BlueprintService
from services.smith import handover


def doc(**over) -> dict:
    """A two-screen roster: one composed, one declared but never built."""
    base = {
        "application": {"id": "app", "name": "Ward Roster", "domain": "health"},
        "product": {
            "objectives": ["Know who is on shift today without ringing round."],
            "terminology": {"Nurse": "Someone who works a shift on a ward."},
        },
        "roles": [
            {"id": "ROLE-001", "name": "Ward Manager",
             "description": "Runs a ward and decides who is on it."},
            {"id": "ROLE-002", "name": "Nurse",
             "description": "Works the shifts."},
        ],
        "navigation": {
            "style": "sidebar",
            "initialRoute": {"ROLE-001": "/today"},
            "tree": [{"label": "Today", "page": "PAGE-001"},
                     {"label": "Reports", "page": "PAGE-002"}],
        },
        "pages": [
            {"id": "PAGE-001", "name": "Today", "route": "/today",
             "purpose": "Show the shifts running now.", "access": "authenticated",
             "primaryTasks": ["See who is on shift"], "actions": ["Mark absent"],
             "views": [{"key": "all", "label": "All wards"}],
             "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-002", "name": "Reports", "route": "/reports",
             "purpose": "Month-end numbers.", "access": "authenticated",
             "primaryTasks": ["Export the month"],
             "data": {"primaryEntity": "ENTITY-001"}},
        ],
        # ONLY PAGE-001 COMPOSED. PAGE-002 is declared and has no layout: the
        # build did not produce it, and it is the screen the guide must not
        # mention.
        "pageLayouts": [{"page": "PAGE-001", "root": {"type": "Stack"}}],
        "workflows": [
            {"id": "FLOW-001", "name": "Mark Absent", "launchedFrom": ["PAGE-001"],
             "purpose": "Records the nurse as absent and frees their shift.",
             "trigger": {"kind": "manual", "detail": "Manager presses Mark absent."}},
            {"id": "FLOW-002", "name": "Month Export", "launchedFrom": ["PAGE-002"],
             "purpose": "Writes the month's numbers to a file.",
             "trigger": {"kind": "manual", "detail": "From the reports screen."}},
        ],
        "businessRules": [
            {"id": "RULE-001", "name": "Reason required", "entity": "ENTITY-001",
             "statement": "An absence cannot be saved without a reason."},
            {"id": "RULE-002", "name": "Retired", "entity": "ENTITY-001",
             "status": "DEPRECATED", "statement": "Nobody may work twelve hours."},
        ],
        "data": {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                               "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}]},
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# What the guide is derived from
# --------------------------------------------------------------------------- #

def test_a_screen_that_never_composed_is_not_in_the_material():
    """The whole correctness argument: a declared page contributes nothing."""
    assert set(handover.composed(doc())) == {"PAGE-001"}

    sheet = handover.sheet(doc())
    named = [s["called"] for aud in sheet["audiences"] for s in aud["screens"]]
    assert named == ["Today", "Today"]          # one per role, and never Reports


def test_nothing_hanging_off_an_uncomposed_screen_reaches_the_writer():
    """Its workflow, its tasks and its menu entry go with it — the join runs
    THROUGH the composed set, so there is no second place to leak from."""
    text = handover.as_text(handover.sheet(doc()))
    assert "Reports" not in text
    assert "Month Export" not in text and "month's numbers" not in text
    assert "Export the month" not in text
    # And the screen that did build is there whole.
    assert "Today" in text and "Records the nurse as absent" in text
    assert "See who is on shift" in text and "All wards" in text


def test_a_retired_rule_is_not_advice_to_give_staff():
    text = handover.as_text(handover.sheet(doc()))
    assert "without a reason" in text
    assert "twelve hours" not in text


# --------------------------------------------------------------------------- #
# Who it is written for
# --------------------------------------------------------------------------- #

def test_each_role_gets_its_own_audience_with_what_it_can_open():
    sheet = handover.sheet(doc())
    assert [a["role"] for a in sheet["audiences"]] == ["Ward Manager", "Nurse"]
    assert sheet["audiences"][0]["lands_on"] == "/today"
    assert sheet["audiences"][0]["who"].startswith("Runs a ward")


def test_a_restricted_screen_reaches_only_the_roles_named_on_it():
    d = doc()
    d["pages"][0]["access"] = "role_restricted"
    d["pages"][0]["users"] = ["ROLE-001"]
    sheet = handover.sheet(d)
    assert [a["role"] for a in sheet["audiences"]] == ["Ward Manager"]


def test_a_screen_no_declared_role_can_open_is_left_out_and_named_back():
    """Not handed to whichever role looks nearest. The omission is reported so
    it is the owner's to fix, and `applied` stays false rather than writing a
    guide with nothing in it."""
    d = doc()
    d["pages"][0]["access"] = "role_restricted"
    d["pages"][0]["users"] = []
    sheet = handover.sheet(d)
    assert sheet["audiences"] == []
    assert sheet["omitted"] == ["Today"]


def test_with_no_roles_declared_there_is_one_audience_and_nothing_invented():
    d = doc()
    d["roles"] = []
    sheet = handover.sheet(d)
    assert [a["role"] for a in sheet["audiences"]] == [handover.EVERYONE]
    assert [s["called"] for s in sheet["audiences"][0]["screens"]] == ["Today"]
    # The document is not written back to.
    assert d["roles"] == []


def test_the_menu_is_the_order_and_the_menu_is_the_name():
    """The words on the menu are the words the reader will look for; a screen
    that is not on the menu says so rather than implying a menu entry."""
    d = doc()
    d["navigation"]["tree"] = [{"label": "Master Data", "children": [
        {"label": "Who's on today", "page": "PAGE-001"}]}]
    sheet = handover.sheet(d)
    screen = sheet["audiences"][0]["screens"][0]
    assert screen["called"] == "Who's on today"
    assert screen["grouped_under"] == "Master Data"

    d["navigation"]["tree"] = []
    off_menu = handover.sheet(d)["audiences"][0]["screens"][0]
    assert off_menu["called"] == "Today" and off_menu["in_menu"] is False
    assert "not in the menu" in handover.as_text(handover.sheet(d))


def test_the_business_words_travel_and_the_blueprints_do_not():
    text = handover.as_text(handover.sheet(doc()))
    assert "Someone who works a shift on a ward." in text
    for jargon in ("PAGE-001", "ENTITY-001", "FLOW-001", "ROLE-001", "pageLayouts"):
        assert jargon not in text


# --------------------------------------------------------------------------- #
# What the owner is handed
# --------------------------------------------------------------------------- #

@pytest.fixture()
def built(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="app",
                                  name="Ward Roster", domain="health")
    for key, value in doc().items():
        if key != "application":
            svc.doc[key] = value
    svc.save()
    return svc


def test_the_guide_comes_back_and_is_saved_where_it_survives_the_chat(built, tmp_path):
    out = handover.run(tmp_path, provider=lambda prompt: "# Using Ward Roster\n\nYou'll see today's shifts.")
    assert out["applied"] and out["path"] == handover.GUIDE_FILE
    saved = (tmp_path / "app" / handover.GUIDE_FILE).read_text("utf-8")
    assert saved.startswith("# Using Ward Roster")
    assert out["edited_paths"] == [handover.GUIDE_FILE]
    assert "You'll see today's shifts." in handover.summary_of(out)
    assert handover.GUIDE_FILE in handover.summary_of(out)


def test_the_printed_page_says_what_it_describes_and_when_to_ask_again(built, tmp_path):
    """A guide nobody can tell is out of date is how people get trained on a
    screen that moved. The version is written here, not asked of the writer."""
    handover.run(tmp_path, provider=lambda prompt: "# Guide")
    saved = (tmp_path / "app" / handover.GUIDE_FILE).read_text("utf-8")
    assert f"as it stood at version {built.doc['version']}" in saved
    assert "Ask for the guide again after you change anything." in saved
    # It is the printed page's footer, not part of what came back into the chat.
    assert "as it stood at version" not in handover.run(
        tmp_path, provider=lambda prompt: "# Guide")["guide"]


def test_the_writer_is_handed_the_sheet_and_nothing_else(built, tmp_path):
    seen: list[str] = []
    handover.run(tmp_path, provider=lambda prompt: seen.append(prompt) or "# Guide")
    assert len(seen) == 1
    assert "Reports" not in seen[0] and "Month Export" not in seen[0]
    assert "Records the nurse as absent" in seen[0]


def test_writing_a_guide_changes_nothing_about_the_application(built, tmp_path):
    before = json.dumps(built.snapshot(), sort_keys=True)
    handover.run(tmp_path, provider=lambda prompt: "# Guide")
    after = BlueprintService.load(output_dir=str(tmp_path))
    assert json.dumps(after.snapshot(), sort_keys=True) == before


def test_with_nothing_composed_it_refuses_and_says_what_to_do(built, tmp_path):
    built.doc["pageLayouts"] = []
    built.save()
    out = handover.run(tmp_path, provider=lambda prompt: "# Guide")
    assert not out["applied"]
    assert "have been built yet" in out["reason"] and "Build it first" in out["reason"]
    assert not (tmp_path / "app" / handover.GUIDE_FILE).exists()


def test_with_no_application_at_all_it_says_so(tmp_path):
    out = handover.run(tmp_path, provider=lambda prompt: "# Guide")
    assert not out["applied"] and "no application here yet" in out["reason"]


def test_a_writer_that_fails_is_a_refusal_not_a_crash(built, tmp_path):
    def boom(prompt: str) -> str:
        raise RuntimeError("upstream timeout")

    out = handover.run(tmp_path, provider=boom)
    assert not out["applied"] and "upstream timeout" in out["reason"]
    assert not (tmp_path / "app" / handover.GUIDE_FILE).exists()


def test_screens_nobody_can_open_are_named_back_beside_the_guide(built, tmp_path):
    built.doc["pages"].append(
        {"id": "PAGE-003", "name": "Payroll", "route": "/payroll",
         "purpose": "Pay runs.", "access": "role_restricted", "users": [],
         "data": {"primaryEntity": "ENTITY-001"}})
    built.doc["pageLayouts"].append({"page": "PAGE-003", "root": {"type": "Stack"}})
    built.save()
    out = handover.run(tmp_path, provider=lambda prompt: "# Guide")
    assert out["applied"] and out["omitted"] == ["Payroll"]
    assert "**Payroll**" in handover.summary_of(out)


# --------------------------------------------------------------------------- #
# The ask reaches it
# --------------------------------------------------------------------------- #

def test_the_turn_writes_the_guide_and_hands_back_the_file(built, monkeypatch):
    """The seam between the classified verb and the writer.

    `handover.run` and the classifier were each covered and the join between
    them was not, which is the one place a typo reaches nobody's test.
    """
    from services.smith_session import SmithSession

    monkeypatch.setattr("services.smith.handover.compose",
                        lambda data, **kw: "# Using Ward Roster\n\nYou'll see today's shifts.")
    session = SmithSession(project_id="p1", output_dir=str(built.output_dir),
                           guards_fn=lambda *a, **kw: [],
                           understand_ask_fn=lambda m, ctx, **kw: {"verb": "write_guide"},
                           iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="write me a one-page guide for the team")

    assert result.status == "resolved"
    assert "You'll see today's shifts." in result.answer
    assert result.touched_paths == [handover.GUIDE_FILE]
    saved = pathlib.Path(built.output_dir) / "app" / handover.GUIDE_FILE
    assert saved.read_text("utf-8").startswith("# Using Ward Roster")


def test_a_turn_with_nothing_composed_asks_rather_than_claiming_a_guide(built, monkeypatch):
    from services.smith_session import SmithSession

    built.doc["pageLayouts"] = []
    built.save()
    session = SmithSession(project_id="p1", output_dir=str(built.output_dir),
                           guards_fn=lambda *a, **kw: [],
                           understand_ask_fn=lambda m, ctx, **kw: {"verb": "write_guide"},
                           iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="write me a guide for the team")

    assert result.status == "needs_user"
    assert "Build it first" in result.answer
    assert result.touched_paths == []


def test_the_ask_is_a_verb_that_needs_nothing_and_has_a_home():
    from services.smith.capabilities import unaccounted
    from services.smith.limits import cannot
    from services.smith.verbs import REQUIRED_BY_VERB, is_known, missing_fields

    assert REQUIRED_BY_VERB["write_guide"] == set()
    assert is_known({"verb": "write_guide"})
    assert missing_fields({"verb": "write_guide"}) == []
    # It is a thing Smith DOES, not one of the asks it answers but cannot serve.
    assert not cannot("write_guide")
    assert unaccounted() == frozenset()


def test_the_phrasebooks_sentence_classifies_to_it():
    """§06's own wording, which reached nothing before this existed."""
    from services.smith.capabilities import nearest

    verbs = [v for v, _example in nearest("can you write me a one-page guide for the team?")]
    assert "write_guide" in verbs

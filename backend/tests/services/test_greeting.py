"""§107 step 1 — what Smith says before the user says anything.

The bug this exists to fix is not a missing welcome. §118 calls Smith the
persistent architect and `smith.py` spends its opening on what that means, and
then a user returning to an application with eighteen pages parked at the build
gate was asked what they would like to build.
"""
import pytest

from services.smith.greeting import NEXT_ACT, Greeting, Opener, greet


def app(**over) -> dict:
    doc = {"application": {"name": "ATS"}, "state": "PLAN_REVIEW",
           "requirements": [{"id": "REQ-001"}], "pages": [{"id": "PAGE-001"}],
           "data": {"entities": [{"id": "ENTITY-001"}]}}
    doc.update(over)
    return doc


# --- the empty case ---------------------------------------------------------

def test_an_empty_blueprint_really_is_asked_what_to_build():
    g = greet({})
    assert g.headline == "What would you like to build?"
    assert g.is_first_visit


def test_the_empty_case_offers_a_way_in():
    """A user staring at an empty box needs a way in more than a greeting."""
    g = greet({})
    assert g.openers
    assert all(o.kind and o.example for o in g.openers)


def test_the_openers_show_different_kinds_of_application():
    kinds = [o.kind for o in greet({}).openers]
    assert len(set(kinds)) == len(kinds), "one opener per interaction kind"


def test_the_openers_are_the_same_every_time():
    """A greeting that reshuffles between page loads reads as indecision."""
    assert greet({}).openers == greet({}).openers


def test_the_openers_come_from_the_anchor_file_not_from_python():
    """`reference_apps.json` says of itself: grow this file, never Python. A
    second list here would be one to keep in agreement with the first."""
    from services.shape_profile import _reference_apps

    glosses = {(a.get("gloss") or "").strip()
               for a in _reference_apps()["reference_apps"]}
    assert {o.example for o in greet({}).openers} <= glosses


def test_the_description_says_showing_is_allowed_too():
    """§5 — a brief, a specification, a design, screenshots."""
    detail = greet({}).detail
    assert "show me" in detail
    assert "before anything is built" in detail


# --- the returning case -----------------------------------------------------

def test_an_application_that_exists_is_not_asked_what_to_build():
    g = greet(app())
    assert "What would you like to build" not in g.headline
    assert not g.is_first_visit


def test_the_headline_says_what_the_application_is():
    g = greet(app(pages=[{}] * 18, workflows=[{}] * 6))
    assert "ATS" in g.headline
    assert "18 pages" in g.headline and "6 workflows" in g.headline


def test_a_dimension_with_nothing_in_it_is_not_mentioned():
    """"0 workflows" is noise in a greeting; it is the plan gate's job to
    count what is not there."""
    assert "workflows" not in greet(app(workflows=[])).headline


def test_an_unnamed_application_still_gets_a_headline():
    assert greet(app(application={})).headline.startswith("Your application")


def test_the_greeting_says_which_gate_the_user_is_standing_at():
    """They have not forgotten what they were building. They have forgotten
    which of the two gates they were at."""
    at_domain = greet(app(state="BLUEPRINT_REVIEW"))
    at_plan = greet(app(state="PLAN_REVIEW"))

    assert "Nothing is built yet" in at_domain.detail
    assert "approve" in at_domain.next_act
    assert "build" in at_plan.next_act
    assert at_domain.next_act != at_plan.next_act


def test_a_state_that_is_mid_run_asks_for_nothing():
    """Smith is working; there is no act for the user to take."""
    assert greet(app(state="BUILD")).next_act == ""


def test_every_state_the_machine_can_be_in_has_something_to_say():
    from services.blueprint.orchestrator import STATES

    assert set(STATES) <= set(NEXT_ACT), sorted(set(STATES) - set(NEXT_ACT))
    assert all(situation for situation, _act in NEXT_ACT.values())


def test_an_unknown_state_does_not_crash_the_greeting():
    g = greet(app(state="SOMETHING_NEW"))
    assert g.headline and g.detail == "" and g.next_act == ""


# --- the facts, for a caller that renders it differently ---------------------

def test_the_facts_carry_what_the_sentence_asserts():
    """So a UI can render it its own way rather than parsing the sentence back
    apart."""
    g = greet(app(pages=[{}] * 18), open_questions=4)
    assert g.facts["pages"] == 18
    assert g.facts["openQuestions"] == 4
    assert g.facts["named"] is True


def test_deprecated_requirements_are_not_counted():
    """§22 keeps them for history, not as obligations."""
    doc = app(requirements=[{"id": "REQ-001"},
                            {"id": "REQ-002", "status": "DEPRECATED"}])
    assert greet(doc).facts["requirements"] == 1


# --- no model -------------------------------------------------------------

def test_greeting_needs_no_model(tmp_path):
    """A status line is the one thing in a conversation that must say the same
    thing twice when nothing has changed."""
    from services.blueprint.service import BlueprintService
    from services.smith.smith import Smith

    svc = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="ATS", domain="ATS")
    smith = Smith(svc)          # no model, no executor

    assert smith.greet().headline == "What would you like to build?"

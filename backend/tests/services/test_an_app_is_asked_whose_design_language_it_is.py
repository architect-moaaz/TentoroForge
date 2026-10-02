"""Whose design language an application is built in — asked once, at the gate.

The answer reaches code, so both the question and the recognition of its
answer are fixed text. What these hold is the two ways that goes wrong: asking
when there is nothing to offer, and treating a passing mention of the company
as a decision.
"""
from __future__ import annotations

import inspect

import pytest

from services.blueprint.service import BlueprintService
from services.smith import design_language as dl


@pytest.fixture()
def svc(tmp_path):
    """A definition as it stands at the approval gate: requirements, no pages."""
    s = BlueprintService.create(output_dir=tmp_path, app_id="a",
                                name="Deliveries", domain="Operations")
    s.doc["requirements"] = [{"id": "REQ-001", "status": "VERIFIED",
                              "description": "A driver can mark a drop done."}]
    s.validate()
    return s


def test_nobody_is_asked_when_the_company_has_nothing_to_offer(svc):
    """A two-option question with an empty option is an obstacle in front of a
    build, not a choice."""
    assert dl.undecided(svc.doc, available=False) is False
    assert dl.undecided(svc.doc, available=True) is True
    # An empty document has nothing to ask about either.
    assert dl.undecided({}, available=True) is False
    assert dl.undecided({"requirements": [], "pages": []}, available=True) is False
    # A built application re-approved is asked, once.
    assert dl.undecided({"pages": [{"id": "PAGE-001", "name": "x"}]},
                        available=True) is True


def test_an_unasked_application_is_not_a_company_one(svc):
    """Absent must mean custom everywhere. An application that inherits a
    palette because nobody got round to offering the choice is the failure."""
    assert dl.chosen(svc.doc) == ""
    from services.blueprint import brand_language

    assert brand_language.chosen(svc.doc) is False
    assert brand_language.chosen({}) is False
    assert brand_language.chosen(None) is False
    assert brand_language.chosen(
        {"application": {"designLanguage": "company"}}) is True


def test_the_question_names_the_company_and_what_was_read():
    q = dl.question("Northwind", summary="#1B7F5A, set in Fraunces")
    assert dl.is_question(q)
    assert "Northwind's design language" in q
    assert "#1B7F5A, set in Fraunces" in q
    assert "storefront" in q  # says when NOT to use it
    assert dl.options("Northwind") == [
        "Use Northwind's design language", "Design this app its own look"]
    # No name on record is still a sentence a person can read.
    assert "your company" in dl.question("")


def test_the_summary_is_something_a_person_can_check_at_a_glance():
    assert dl.summary_of({"colors": {"primary": "#1B7F5A"},
                          "typography": {"fontFamilyHeading": "Fraunces"}}) \
        == "#1B7F5A, set in Fraunces"
    assert dl.summary_of({}) == ""
    assert dl.summary_of(None) == ""


def test_an_answer_counts_only_as_the_answer_to_the_question_just_asked():
    q = dl.question("Northwind")
    assert dl.answer_in("Use Northwind's design language", [("smith", q)],
                        "Northwind") == "company"
    assert dl.answer_in("Design this app its own look", [("assistant", q)],
                        "Northwind") == "custom"
    assert dl.answer_in("custom", [("smith", q)], "Northwind") == "custom"
    assert dl.answer_in("our brand", [("smith", q)], "Northwind") == "company"

    # THE NAME IN AN UNRELATED TURN IS NOT A DECISION. This matters more here
    # than for the designer question: a company's name appears in ordinary
    # conversation constantly.
    assert dl.answer_in("Use Northwind's design language", [], "Northwind") == ""
    assert dl.answer_in(
        "Use Northwind's design language",
        [("assistant", "Which of these should I change?")], "Northwind") == ""
    assert dl.answer_in("Northwind is our biggest customer", [("smith", q)],
                        "Northwind") == ""
    assert dl.answer_in("", [("smith", q)], "Northwind") == ""
    # The question, then something else, then a reply — not adjacent.
    assert dl.answer_in("custom", [("smith", q), ("user", "hang on"),
                                   ("smith", "Sure.")], "Northwind") == ""


def test_recording_writes_the_fact_and_the_citation(svc):
    said = dl.record(svc, "company", company_name="Northwind")
    assert "Northwind" in said

    reloaded = BlueprintService.load(output_dir=svc.output_dir)
    assert reloaded.doc["application"]["designLanguage"] == "company"
    rows = [d for d in reloaded.doc["decisions"]
            if str(d.get("decision", "")).startswith("The design language is")]
    assert rows and rows[0]["source"] == "user"
    assert rows[0]["approvedBy"] == "user" and rows[0]["binding"] is True
    assert rows[0]["status"] == "APPROVED"


def test_changing_your_mind_supersedes_rather_than_accumulates(svc):
    dl.record(svc, "company", company_name="Northwind")
    dl.record(svc, "custom")
    again = BlueprintService.load(output_dir=svc.output_dir)
    assert again.doc["application"]["designLanguage"] == "custom"

    rows = [d for d in again.doc["decisions"]
            if str(d.get("decision", "")).startswith("The design language is")]
    live = [d for d in rows if d.get("status") != "DEPRECATED"]
    assert len(rows) == 2 and len(live) == 1
    assert live[0]["supersedes"] == next(
        d["id"] for d in rows if d["status"] == "DEPRECATED")

    # The same answer twice is one row, not a third.
    dl.record(svc, "custom")
    final = BlueprintService.load(output_dir=svc.output_dir)
    assert len([d for d in final.doc["decisions"]
                if str(d.get("decision", "")).startswith("The design language is")]) == 2


def test_only_the_two_declared_answers_can_be_recorded(svc):
    for bad in ("figma", "", "COMPANY", None):
        with pytest.raises(ValueError):
            dl.record(svc, bad)


def test_the_gate_asks_before_it_builds():
    """The question has to come BEFORE `_run_dag`, because both nodes that
    consume the answer run inside that build."""
    from routers import blueprint_generate

    src = inspect.getsource(blueprint_generate.smith_chat)
    approved_at = src.index("if req.approved:")
    after = src[approved_at:]
    asked_at = after.index("design_language.question")
    built_at = after.index("_run_dag(")
    assert asked_at < built_at


# --------------------------------------------------------------------------- #
# the palette question, asked while defining
# --------------------------------------------------------------------------- #

def test_the_clarifier_offers_the_company_s_own_palette_first():
    """Smith asked "which colour palette should the calculator use?" of an
    organisation that had told us during onboarding exactly what it looks
    like, and offered every answer except their own."""
    from services.smith.clarify_brief import clarify_brief, company_palette_option

    option = company_palette_option("Tentoro Technologies", "#336791, set in Open Sans")
    assert option == "Use Tentoro Technologies's own palette (#336791, set in Open Sans)"

    seen: dict = {}

    def provider(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"questions": []}'

    clarify_brief("Build a simple arithmetic calculator",
                  provider=provider, company_palette=option)
    assert "DESIGN LANGUAGE ON RECORD" in seen["prompt"]
    assert option in seen["prompt"]
    # Offered, not imposed: an app that should not look like the company is a
    # real case, so the question still gets asked.
    assert "do not propose palettes" not in seen["prompt"]


def test_a_design_attached_to_this_app_outranks_the_company_default():
    """A file attached to THIS brief is a statement about this application;
    the company palette is only a default. They are not combined."""
    from services.smith.clarify_brief import clarify_brief, company_palette_option

    seen: dict = {}

    def provider(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"questions": []}'

    clarify_brief("Build it from this Figma file", provider=provider,
                  design_attached=True,
                  company_palette=company_palette_option("Tentoro", "#336791"))
    assert "do not propose palettes" in seen["prompt"]
    assert "DESIGN LANGUAGE ON RECORD" not in seen["prompt"]


def test_no_company_no_extra_instruction():
    from services.smith.clarify_brief import clarify_brief

    seen: dict = {}

    def provider(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"questions": []}'

    clarify_brief("Build a calculator", provider=provider)
    assert "DESIGN LANGUAGE ON RECORD" not in seen["prompt"]


def test_taking_the_option_while_defining_is_the_decision():
    """Answering it once is answering it. The gate must not put the same
    question a second time in different words."""
    option = "Use Tentoro Technologies's own palette (#336791, set in Open Sans)"
    history = [
        ("user", "Build a simple arithmetic calculator"),
        ("smith", "Which colour palette should the calculator use?"),
        ("user", option),
    ]
    assert dl.chose_company_earlier(history, "Tentoro Technologies") is True
    # The option without its summary, as a client may echo it back.
    assert dl.chose_company_earlier(
        [("user", "Use Tentoro Technologies's own palette")],
        "Tentoro Technologies") is True
    # Somebody else's answer is not theirs.
    assert dl.chose_company_earlier(
        [("user", "Soft cream and indigo: modern, app-like")],
        "Tentoro Technologies") is False
    # Smith proposing the option is not the user taking it.
    assert dl.chose_company_earlier([("smith", option)],
                                    "Tentoro Technologies") is False
    assert dl.chose_company_earlier([], "Tentoro Technologies") is False


def test_the_gate_stops_asking_once_it_has_been_answered(svc):
    dl.record(svc, dl.COMPANY, company_name="Tentoro Technologies")
    assert dl.undecided(svc.doc, available=True) is False

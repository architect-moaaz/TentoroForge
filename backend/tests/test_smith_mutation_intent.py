"""Smith mutation-intent guard coverage (Task 2 / RC-4).

The anti-fabrication guard only fires when _is_mutation_intent() is True. Its
verb list was too narrow, so common change phrasings slipped past and Smith could
reply a confident "Done!" with zero edits. These lock in the expanded coverage.
"""
from agents.smith_agent import _is_mutation_intent


def test_expanded_mutation_phrasings_are_caught():
    for m in (
        "get rid of the sidebar",
        "take out the footer",
        "turn the list into a grid",
        "convert this page to a card layout",
        "switch the theme to dark",
        "eliminate the header",
        "toggle the filter panel off",
        "disable public signups",
        "do away with the banner",
        "merge these two pages",
    ):
        assert _is_mutation_intent(m), f"{m!r} is a change request and must trip the guard"


def test_questions_and_discussion_do_not_trip_the_guard():
    for m in (
        "what does this page do?",
        "did you fix it?",
        "explain the workflow",
        "why is the list empty?",
    ):
        assert not _is_mutation_intent(m), f"{m!r} is a question, must NOT trip the guard"

"""'Fix the remaining issues' is the whole list — every open fault, by the
checks' own loop — however it is said, and also as a yes to the checks'
offer 'Tell me to carry on'. One page named is one page."""
from __future__ import annotations

from types import SimpleNamespace

from routers.blueprint_generate import _wants_the_whole_list

CHECKS_CLOSING = ("Checks finished: pages built and working 10 of 16. Still not right (30): Financial Dashboard, "
                  "Calendar and more. Tell me to carry on, or what to fix first.")
SMITH_OFFER = "It still does not work. Say “carry on” and I will keep at it."


def turn(role, text):
    return SimpleNamespace(role=role, text=text)


def test_the_words_people_use():
    for ask in ("Fix the remaining issues", "fix all open issues", "Review the app once again and fix if any open issues are present",
                "Review and fix any open issues", "check the app again", "Check the application again and fix everything that still fails",
                "run the checks again", "fix everything", "please resolve the outstanding problems", "fix them all"):
        assert _wants_the_whole_list(ask, []), ask


def test_one_page_or_one_thing_is_not_the_list():
    for ask in ("Fix /transactions", "Fix the issue in /calendar", "fix the NaN on the dashboard", "Show me the screens", "Rerun"):
        assert not _wants_the_whole_list(ask, []), ask


def test_a_yes_to_the_checks_offer_is_the_list_and_a_yes_to_smiths_offer_is_not():
    assert _wants_the_whole_list("carry on", [turn("assistant", CHECKS_CLOSING)])
    assert _wants_the_whole_list("Go ahead", [turn("assistant", CHECKS_CLOSING)])
    assert not _wants_the_whole_list("carry on", [turn("assistant", SMITH_OFFER)])
    assert not _wants_the_whole_list("carry on", [])

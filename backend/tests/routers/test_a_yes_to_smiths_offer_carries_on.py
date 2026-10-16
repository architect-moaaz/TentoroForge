"""Smith ended with "Say “carry on” and I will keep at it"; the person said
"Go ahead". That is the offer taken, not a build consent — it was answered
"It is already built from this definition… what would you like to do?"
(pcn4owv7, 2026-10-15 05:36)."""
from __future__ import annotations

from types import SimpleNamespace

from routers.blueprint_generate import _yes_to_a_carry_on_offer

OFFER = "It still does not work: I tried it again after the change and it failed the same way. Say “carry on” and I will keep at it."


def turn(role: str, text: str):
    return SimpleNamespace(role=role, text=text)


def test_a_plain_yes_after_the_offer_is_the_offer():
    history = [turn("user", "Rerun"), turn("assistant", OFFER)]
    for yes in ("Go ahead", "yes", "ok", "yes please", "proceed", "do it"):
        assert _yes_to_a_carry_on_offer(history, yes), yes


def test_without_the_offer_or_without_a_yes_it_is_not():
    assert not _yes_to_a_carry_on_offer([turn("assistant", "Here are the screens, as built.")], "Go ahead")
    assert not _yes_to_a_carry_on_offer([turn("assistant", OFFER)], "Fix the calendar")
    assert not _yes_to_a_carry_on_offer([], "Go ahead")
    # The last ASSISTANT line decides, not an older one.
    assert not _yes_to_a_carry_on_offer([turn("assistant", OFFER), turn("assistant", "Done."), turn("user", "ok")], "ok")
    assert _yes_to_a_carry_on_offer([("assistant", OFFER)], "go ahead")

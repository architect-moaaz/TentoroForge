"""When the chooser's reply is cut off, ask the model again — not the person.

UAT, 2026-09-18 (smithv2, 1be5ce23): a person described what she wanted twice
in her own words and twice got "I did not follow that" — the sentence the old
front door returned when the model's REPLY could not be parsed. The call was
capped at 1200 tokens; a long ask makes a long object; a truncated one looks
exactly like nonsense from the user. Ported to Smith v4's chooser, where the
same reply once ended a turn as `done` with nothing said at all.
"""
from services.smith.loop import next_step
from services.smith.understand_ask import _looks_cut_off

CUT_OFF = '{"tool": "write_page_code", "args": {"route": "/tools", "brief": "show the ar'
GOOD = '{"tool": "write_page_code", "args": {"route": "/tools", "brief": "show the area"}, "why": ""}'
ASK = ("I want the application to have good visuals and images of the tools "
       "also there should not be latitute or longititude it should have place name")


def test_a_cut_off_reply_is_asked_again():
    calls = []

    def provider(prompt):
        calls.append(prompt)
        return CUT_OFF if len(calls) == 1 else GOOD

    out = next_step(ASK, "ctx", [], [], provider=provider)
    assert len(calls) == 2, "the second ask costs one call and saves the turn"
    assert "JSON object only" in calls[1], "and says what went wrong"
    assert out["tool"] == "write_page_code" and out["args"]["brief"] == "show the area"


def test_a_good_reply_is_not_asked_twice():
    calls = []

    def provider(prompt):
        calls.append(prompt)
        return GOOD

    next_step(ASK, "ctx", [], [], provider=provider)
    assert len(calls) == 1


def test_prose_is_not_retried_and_the_turn_asks_in_the_persons_words():
    """Not every unparseable reply is truncation; prose means the model
    answered the wrong way. The turn ends asking — never as a silent `done`."""
    calls = []

    def provider(prompt):
        calls.append(prompt)
        return "I think she means the home page."

    out = next_step(ASK, "ctx", [], [], provider=provider)
    assert len(calls) == 1
    assert out["tool"] == "ask_user"
    said = out["args"]["question"]
    assert "good visuals and images" in said, "her words, so she can see what landed"
    assert "one" in said and "screen" in said, "and one thing at a time"


def test_only_an_unclosed_object_counts_as_cut_off():
    assert _looks_cut_off('{"tool": "answer", "args": {"text": "')
    assert not _looks_cut_off('{"tool": "done", "args": {}}')
    assert not _looks_cut_off("I did not understand the request.")
    assert not _looks_cut_off("")

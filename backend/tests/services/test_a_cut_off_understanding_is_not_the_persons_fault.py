"""When the understanding reply is cut off, ask the model again — not the user.

UAT, 2026-09-18: a person described what she wanted in her own words twice
("good visuals and images of the tools ... place name and description"), and
twice got "I did not follow that. Which screen should I change, and what on
it?" — the sentence `understand_ask` returns when the model's REPLY cannot be
parsed. The call was capped at 1200 tokens, a long ask makes a long object,
and a truncated one looks exactly like nonsense from the user.
"""
from services.smith.understand_ask import understand_ask, _looks_cut_off

CUT_OFF = '{"ops": [{"verb": "add_field", "entity": "ToolListing", "field": "ar'
GOOD = '{"ops": [{"verb": "add_field", "entity": "ToolListing", "field": "area"}]}'
ASK = ("I want the application to have good visuals and images of the tools "
       "also there should not be latitute or longititude it should have place name")


def test_a_cut_off_reply_is_asked_again():
    calls = []

    def provider(prompt):
        calls.append(prompt)
        return CUT_OFF if len(calls) == 1 else GOOD

    out = understand_ask(ASK, "ctx", provider=provider)
    assert len(calls) == 2, "the second ask costs one call and saves the turn"
    assert "JSON object only" in calls[1], "and says what went wrong"
    assert not out.get("clarification_needed"), out


def test_a_good_reply_is_not_asked_twice():
    calls = []

    def provider(prompt):
        calls.append(prompt)
        return GOOD

    understand_ask(ASK, "ctx", provider=provider)
    assert len(calls) == 1


def test_prose_is_not_retried_but_quotes_the_person():
    """Not every unparseable reply is truncation; prose means the model
    answered the wrong way, and asking again the same way rarely helps."""
    calls = []

    def provider(prompt):
        calls.append(prompt)
        return "I think she means the home page."

    out = understand_ask(ASK, "ctx", provider=provider)
    assert len(calls) == 1
    said = out["clarification_needed"]
    assert "good visuals and images" in said, "her words, so she can see what landed"
    assert "one" in said and "screen" in said, "and one thing at a time"


def test_only_an_unclosed_object_counts_as_cut_off():
    assert _looks_cut_off('{"ops": [{"verb": "add_field"')
    assert not _looks_cut_off('{"ops": []}')
    assert not _looks_cut_off("I did not understand the request.")
    assert not _looks_cut_off("")

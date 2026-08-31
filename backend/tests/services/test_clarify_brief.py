"""§16 before the first definition — ask once, or not at all."""

import pytest

from services.smith.clarify_brief import clarify_brief


def _says(payload: str):
    return lambda prompt: payload


def test_questions_come_back_whole():
    out = clarify_brief("a tool for my team", provider=_says(
        '{"questions":[{"question":"Shared or private?",'
        '"options":["Shared","Private"]}]}'))
    assert out[0]["question"] == "Shared or private?"
    assert out[0]["options"] == ["Shared", "Private"]


def test_several_questions_are_kept_in_order_and_capped():
    """Language and palette are both worth asking, and a fourth question is
    an interview."""
    qs = ",".join(f'{{"question":"q{i}","options":[]}}' for i in range(5))
    out = clarify_brief("x", provider=_says('{"questions":[' + qs + ']}'))
    assert [q["question"] for q in out] == ["q0", "q1", "q2"]


def test_no_question_is_the_common_case():
    """A brief that stands on its own must not be interrogated — asking anyway
    reads as not having listened."""
    assert clarify_brief("x", provider=_says('{"questions":[]}')) == []


@pytest.mark.parametrize("reply", [
    "not json at all",
    "",
    '{"questions":[]}',
    '{"questions":[{"options":["a"]}]}',
    '{"questions":[{"question":"   "}]}',
])
def test_anything_unusable_asks_nothing(reply):
    """A question is a courtesy, never a gate: every failure lets the
    definition proceed."""
    assert clarify_brief("a brief", provider=_says(reply)) == []


def test_a_provider_that_fails_asks_nothing():
    def boom(prompt):
        raise RuntimeError("provider down")

    assert clarify_brief("a brief", provider=boom) == []


def test_an_empty_brief_is_not_worth_a_question():
    assert clarify_brief("  ", provider=_says('{"questions":[{"question":"?"}]}')) == []


def test_options_are_capped():
    """Offering answers stops a question being homework; offering eight starts
    a different kind of homework."""
    out = clarify_brief("x", provider=_says(
        '{"questions":[{"question":"Which?",'
        '"options":["a","b","c","d","e","f"]}]}'))
    assert len(out[0]["options"]) == 4


def test_json_wrapped_in_prose_is_still_read():
    out = clarify_brief("x", provider=_says(
        'Sure! ```json\n{"questions":[{"question":"Who uses it?","options":[]}]}'
        '\n``` hope that helps'))
    assert out[0]["question"] == "Who uses it?"

"""A reply that was all reasoning is retried with less effort and more room.

0l133sp2: /rentals/[id] spent its whole 48,000-token budget reasoning and
wrote no page; the retry asked again at the same effort and budget, which on
UAT had produced the same nothing twice.
"""
from services.blueprint.executors import AnthropicModel, NO_ANSWER_RETRY_TOKENS, after_no_answer


def test_the_retry_lowers_effort_and_raises_the_budget():
    base = AnthropicModel(effort="high", max_tokens=48000)
    retry = after_no_answer(base, "NoAnswer: the model spent all 48,000 output tokens reasoning")
    assert (retry.effort, retry.max_tokens) == ("medium", NO_ANSWER_RETRY_TOKENS)
    assert (base.effort, base.max_tokens) == ("high", 48000), "the shared client is not changed"


def test_any_other_retry_is_asked_as_before():
    base = AnthropicModel(effort="high", max_tokens=48000)
    assert after_no_answer(base, "InvalidPageContent: ...") is base
    assert after_no_answer(base, "") is base


def test_a_client_with_no_effort_is_left_alone():
    fake = lambda **kw: "{}"  # noqa: E731
    assert after_no_answer(fake, "NoAnswer: ...") is fake

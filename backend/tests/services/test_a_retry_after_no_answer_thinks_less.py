"""A reply that was all reasoning is retried with the least effort and more room.

0l133sp2: /rentals/[id] spent its whole 48,000-token budget reasoning and
wrote no page; the retry asked again at the same effort and budget, which on
UAT had produced the same nothing twice.

ONE NOTCH WAS NOT ENOUGH, AND THAT IS MEASURED TOO. A Calculator's single
page (forge-v3, 2026-09-20) burned all 64,000 tokens reasoning at `high`,
and the retry — at `medium` — burned all 64,000 again: 25 minutes, no page.
A reply that never starts is not improved by thinking slightly less.
"""
from services.blueprint.executors import AnthropicModel, NO_ANSWER_RETRY_TOKENS, after_no_answer


def test_the_retry_drops_to_the_least_effort_and_raises_the_budget():
    base = AnthropicModel(effort="high", max_tokens=48000)
    retry = after_no_answer(base, "NoAnswer: the model spent all 48,000 output tokens reasoning")
    assert (retry.effort, retry.max_tokens) == ("low", NO_ANSWER_RETRY_TOKENS)
    assert (base.effort, base.max_tokens) == ("high", 48000), "the shared client is not changed"


def test_a_notch_is_not_enough_from_any_height():
    """`medium` spent the whole budget the same way `high` did."""
    for effort in ("max", "xhigh", "high", "medium", "low"):
        assert after_no_answer(AnthropicModel(effort=effort), "NoAnswer: ...").effort == "low"


def test_any_other_retry_is_asked_as_before():
    base = AnthropicModel(effort="high", max_tokens=48000)
    assert after_no_answer(base, "InvalidPageContent: ...") is base
    assert after_no_answer(base, "") is base


def test_a_client_with_no_effort_is_left_alone():
    fake = lambda **kw: "{}"  # noqa: E731
    assert after_no_answer(fake, "NoAnswer: ...") is fake

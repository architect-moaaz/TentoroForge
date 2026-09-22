"""A model call that returns no answer fails with a reason a person can act on.

MEASURED ON UAT. LabConnect, a 23-entity laboratory application, failed its
build at `page_contracts` with the reason

    StopIteration:

— an empty message, twice, and every node after it skipped. The page-set call
was offered 24 slots in a 19,570-character question, reasoned through its
entire 32,000-token output budget, and returned a message holding thinking and
no text. `next(b.text for b in response.content if b.type == "text")` raised on
the empty generator, and nothing between there and the run report could say
what had happened. The node-level retry asked the same question with the same
budget and got the same nothing.
"""
from types import SimpleNamespace

import pytest

from services.blueprint import executors
from services.blueprint.executors import MAX_TOKENS_BY_NODE, NoAnswer


def _response(content, stop_reason="max_tokens", output_tokens=32000):
    return SimpleNamespace(
        content=content, stop_reason=stop_reason, stop_details=None,
        usage=SimpleNamespace(input_tokens=9000, output_tokens=output_tokens,
                              cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


class _Stream:
    """What `messages.stream(...)` hands back: no events, then the message.
    Every call streams now (2026-09-22), including these short ones."""

    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self.response


def _model(response, max_tokens=4000):
    """An AnthropicModel whose client streams `response` with no events."""
    model = executors.AnthropicModel(model="claude-sonnet-5", max_tokens=max_tokens)
    fake = SimpleNamespace(messages=SimpleNamespace(stream=lambda **_: _Stream(response)))
    model._anthropic = lambda: fake
    return model


THINKING_ONLY = [SimpleNamespace(type="thinking", thinking="...")]


def test_a_reply_of_only_thinking_is_named_not_a_stopiteration():
    model = _model(_response(THINKING_ONLY))
    with pytest.raises(NoAnswer) as caught:
        model(system="s", user="u", schema={})
    message = str(caught.value)
    assert message, "the failure must say something"
    assert "reasoning" in message and "no answer" in message
    assert "32,000" in message


def test_the_spend_travels_with_the_failure():
    """The call that wrote nothing is the one that spent the most."""
    model = _model(_response(THINKING_ONLY))
    with pytest.raises(NoAnswer) as caught:
        model(system="s", user="u", schema={})
    assert caught.value.usage is not None
    assert caught.value.usage.output_tokens == 32000
    assert caught.value.stop_reason == "max_tokens"


def test_an_empty_reply_for_another_reason_says_that_reason():
    model = _model(_response([], stop_reason="end_turn", output_tokens=3))
    with pytest.raises(NoAnswer) as caught:
        model(system="s", user="u", schema={})
    assert "end_turn" in str(caught.value)


def test_a_reply_with_text_is_unchanged():
    text = SimpleNamespace(type="text", text='{"proposals": []}')
    reply = _model(_response(THINKING_ONLY + [text], stop_reason="end_turn",
                             output_tokens=900))(system="s", user="u", schema={})
    assert reply.text == '{"proposals": []}'
    assert reply.stop_reason == "end_turn"


def test_the_page_set_call_has_room_for_a_large_application():
    """24 slots for 23 entities spent 32,000 tokens reasoning and wrote
    nothing. 64,000 is the headroom this file already uses elsewhere."""
    assert MAX_TOKENS_BY_NODE["page_contracts"] >= 64000

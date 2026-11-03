"""`temperature` is not a parameter of the API version we are pinned to, and
sending one is a 400 the person reads as "I could not reach my reasoning
service just now, so I stopped here and nothing was changed."

Measured on forge-v3 2026-11-02. anthropic 2.3.0 sends `anthropic-version:
2026-10-21`, where `Messages.create` does not accept `temperature` at all;
langchain-anthropic 1.7.7 still offers it and smuggles it through `extra_body`,
so it arrives as an unknown field: `temperature: Extra inputs are not
permitted`. Both of Forge's thinking paths hardcoded 1.0, so every Smith turn
that streamed its reasoning died on its first call.

The assertion is at the boundary that matters — what ChatAnthropic is built
with — because that is what becomes the request body.
"""

import pytest

import services.llm_client as lc


@pytest.fixture
def built(monkeypatch):
    """What `_chat_model` hands ChatAnthropic."""
    seen: dict = {}

    class FakeChat:
        def __init__(self, **kwargs):
            seen.clear()
            seen.update(kwargs)

    import langchain_anthropic
    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChat)
    return seen


@pytest.mark.parametrize("temperature", [1.0, 0.0, 0.2, None])
def test_no_temperature_reaches_the_model_whatever_the_caller_asks(built, temperature):
    lc._chat_model(None, model="claude-sonnet-4-6", max_tokens=100,
                   temperature=temperature, timeout=None)
    assert "temperature" not in built, (
        "a temperature in the constructor becomes one in extra_body, which is a 400")


def test_a_caller_may_still_name_one_without_an_error(built):
    """Dropped, not refused: a dozen services name a temperature and none of
    them should have to learn that the transport stopped taking it."""
    lc._chat_model(None, model="claude-sonnet-4-6", max_tokens=100,
                   temperature=0.3, timeout=None)
    assert built["model"] == "claude-sonnet-4-6" and built["max_tokens"] == 100


def test_the_thinking_block_still_goes_through(built):
    """The fix must not have cost us extended thinking."""
    lc._chat_model(None, model="claude-sonnet-4-6", max_tokens=100,
                   temperature=1.0, timeout=None, thinking={"type": "adaptive"})
    assert built["thinking"] == {"type": "adaptive"}
    assert "temperature" not in built


def test_both_thinking_paths_are_covered(monkeypatch):
    """`complete()` reasons two ways — streamed and not — and neither may send one."""
    calls: list[dict] = []

    class FakeChat:
        def invoke(self, _m):
            from types import SimpleNamespace
            return SimpleNamespace(content=[{"type": "text", "text": "ok"}])

        def stream(self, _m):
            from types import SimpleNamespace
            yield SimpleNamespace(content=[{"type": "text", "text": "ok"}])

    def fake_chat_model(_key, **kwargs):
        calls.append(kwargs)
        return FakeChat()

    monkeypatch.setattr(lc, "_chat_model", fake_chat_model)
    lc.complete(content="hi", temperature=0.4)                          # no thinking
    lc.complete(content="hi", reasoning_callback=lambda _t: None)        # streamed thinking
    assert len(calls) == 2
    assert all(c.get("temperature") is None for c in calls[1:]), \
        "the streamed path used to hardcode 1.0"

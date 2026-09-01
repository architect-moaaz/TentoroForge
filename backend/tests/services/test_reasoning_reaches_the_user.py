"""Smith's reasoning gets from the model call to the panel.

The chain is four hops — router -> handle_chat_v2 -> SmithSession ->
understand_ask -> llm_client.complete — and any one of them dropping the sink
gives the same symptom: the model reasons, nobody sees it, and the panel shows
a spinner for a turn that takes a minute.

That symptom is why this is tested per hop rather than end to end. The
machinery for showing Smith's thinking has now been built twice and shipped
inert twice, both times because a caller three layers up did not pass it.
"""
from __future__ import annotations

from types import SimpleNamespace

import services.llm_client as lc
import pytest

from services.smith.understand_ask import understand_ask


@pytest.fixture()
def transport(monkeypatch):
    """Both paths faked: `create` for an unwatched call, `stream` for a watched
    one. They are different code paths in `complete` — a watched call streams
    so the reasoning arrives while it is produced rather than after."""
    seen: dict = {}

    class _Msgs:
        def create(self, **kw):
            seen.update(kw, path="create")
            return lc.Message(content=[
                lc.ThinkingBlock(thinking="/ has a page but no layout."),
                lc.TextBlock(text='{"verb":"compose_route","route":"/"}'),
            ])

    class _Chat:
        def __init__(self, **kw):
            seen.update(kw, path="stream")

        def stream(self, _msgs):
            yield SimpleNamespace(content=[
                {"type": "thinking", "thinking": "/ has a page but no layout."}])
            yield SimpleNamespace(content=[
                {"type": "text",
                 "text": '{"verb":"compose_route","route":"/"}'}])

    monkeypatch.setattr(lc, "_SyncMessages", lambda _k: _Msgs())
    monkeypatch.setattr(lc, "_chat_model", lambda _k, **kw: _Chat(**kw))
    return seen


def test_complete_asks_for_thinking_only_when_someone_is_listening(transport):
    lc.complete(content="hi")
    assert transport["path"] == "create" and transport.get("thinking") is None

    lc.complete(content="hi", reasoning_callback=lambda _t: None)
    assert transport["path"] == "stream"
    assert transport["thinking"] == {"type": "adaptive"}
    # Extended thinking requires temperature=1.0; the API rejects other values
    # when the block is present.
    assert transport["temperature"] == 1.0


def test_the_answer_gets_its_own_room(transport):
    """On the adaptive path max_tokens caps thinking AND output together, so
    asking for reasoning without raising it buys the reasoning at the answer's
    expense — and a truncated reply parses as a failed one."""
    lc.complete(content="hi", max_tokens=1200)
    without = transport["max_tokens"]
    lc.complete(content="hi", max_tokens=1200, reasoning_callback=lambda _t: None)
    assert transport["max_tokens"] == without + lc.THINKING_HEADROOM_TOKENS


def test_understand_ask_forwards_the_reasoning_and_still_answers(transport):
    thoughts: list[str] = []
    u = understand_ask("the page at / is empty", "PAGE-002 route /",
                       reasoning=thoughts.append)
    assert thoughts == ["/ has a page but no layout."]
    assert u["verb"] == "compose_route" and u["route"] == "/"


def test_an_injected_provider_keeps_its_one_argument_seam(transport):
    """Every test in the suite supplies `lambda prompt: "..."`. None of them
    should have to grow a parameter to say it does no thinking."""
    u = understand_ask("x", "ctx", reasoning=lambda _t: None,
                       provider=lambda _prompt: '{"verb":"rename"}')
    assert u["verb"] == "rename"


def test_a_session_without_a_sink_calls_the_seam_exactly_as_before():
    """Every caller predating this passes no reasoning_fn, and their seams
    take no such argument — passing one anyway would TypeError the turn."""
    from services.smith_session import SmithSession

    seen: dict = {}

    def _seam(message, ctx, **kw):
        seen.update(kw)
        return {"answer": "it does", "clarification_needed": ""}

    s = SmithSession(project_id="p", output_dir=".",
                     understand_ask_fn=_seam, iteration_move_fn=lambda *_a: None)
    s.run_iteration("does it store data?")
    assert set(seen) == {"history"}, "an unwatched turn grew an argument"


def test_a_session_with_a_sink_hands_it_to_the_seam():
    from services.smith_session import SmithSession

    seen: dict = {}

    def _seam(message, ctx, **kw):
        seen.update(kw)
        return {"answer": "it does", "clarification_needed": ""}

    sink = lambda _t: None  # noqa: E731
    s = SmithSession(project_id="p", output_dir=".", reasoning_fn=sink,
                     understand_ask_fn=_seam, iteration_move_fn=lambda *_a: None)
    s.run_iteration("does it store data?")
    assert seen.get("reasoning") is sink


def test_the_router_gives_chat_v2_a_sink_that_emits():
    """The hop that was missing on the other endpoint for the whole session."""
    import inspect

    import routers.blueprint_generate as bg

    src = inspect.getsource(bg.smith_chat)
    assert 'reasoning_fn=lambda text: emit("thought"' in src


def test_chat_v2_passes_the_sink_into_the_session():
    import inspect

    from services import smith_chat_v2

    assert "reasoning_fn=req.reasoning_fn" in inspect.getsource(
        smith_chat_v2._build_session)

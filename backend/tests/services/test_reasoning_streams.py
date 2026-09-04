"""Reasoning arrives while it is being had, and covers the slow part too.

Two gaps this closes. `complete()` used `create`, which returns once the whole
reply exists — so the reasoning landed in one burst AFTER the wait it was meant
to fill. And the composition, which is the minute-long half of a compose turn,
had no sink at all: `understand_ask` explained why it was composing and then
the panel went quiet for the part that actually takes the time.
"""
from __future__ import annotations

from types import SimpleNamespace

import services.llm_client as lc


# ── the sink ────────────────────────────────────────────────────────────

def test_deltas_become_whole_sentences_not_fragments():
    """One event per delta is a stuttering column of half-words: motion
    without meaning."""
    out: list[str] = []
    sink = lc.ReasoningSink(out.append)
    for d in ["The route ", "/ has a page ", "but no layout, so this is a ",
              "composition. ", "Next I run page_layouts."]:
        sink.feed(d)
    assert out == ["The route / has a page but no layout, so this is a composition."]
    sink.close()
    assert out[-1] == "Next I run page_layouts."


def test_a_short_sentence_waits_for_company():
    """Below the floor a full stop is usually an abbreviation or a list
    marker, not the end of a thought."""
    out: list[str] = []
    sink = lc.ReasoningSink(out.append)
    sink.feed("No. Yes. Maybe. ")
    assert out == []


def test_the_tail_is_never_dropped():
    """Reasoning rarely ends on a full stop, and the last sentence is usually
    the conclusion — the one worth reading."""
    out: list[str] = []
    sink = lc.ReasoningSink(out.append)
    sink.feed("I am still deciding which pattern fits")
    sink.close()
    assert out == ["I am still deciding which pattern fits"]


def test_a_sink_that_raises_cannot_fail_the_turn():
    sink = lc.ReasoningSink(lambda _t: (_ for _ in ()).throw(RuntimeError("ui")))
    sink.feed("x" * 80 + ". ")
    sink.close()  # no raise


# ── the one-shot call ───────────────────────────────────────────────────

def test_complete_streams_when_someone_is_watching(monkeypatch):
    """`create` returns once the whole reply exists. Reasoning delivered then
    is a transcript of thinking already done."""
    used: dict = {}

    class _Chat:
        def stream(self, _msgs):
            used["streamed"] = True
            yield SimpleNamespace(content=[
                {"type": "thinking",
                 "thinking": "The page at / has no layout at all, so this is "
                             "a composition rather than a rename. "},
            ])
            yield SimpleNamespace(content=[{"type": "text", "text": '{"verb":'}])
            yield SimpleNamespace(content=[{"type": "text", "text": '"compose_route"}'}])

        def invoke(self, _msgs):  # pragma: no cover - must not be reached
            used["invoked"] = True
            raise AssertionError("streamed path expected")

    monkeypatch.setattr(lc, "_chat_model", lambda *_a, **_kw: _Chat())
    out: list[str] = []
    text = lc.complete(content="hi", reasoning_callback=out.append)

    assert used.get("streamed") and "invoked" not in used
    assert text == '{"verb":"compose_route"}'
    assert out and out[0].startswith("The page at / has no layout")


def test_an_unwatched_call_does_not_stream(monkeypatch):
    """Every batch caller: no sink, no thinking request, no streaming."""
    seen: dict = {}

    class _Msgs:
        def create(self, **kw):
            seen.update(kw)
            return lc.Message(content=[lc.TextBlock(text="ok")])

    monkeypatch.setattr(lc, "_SyncMessages", lambda _k: _Msgs())
    assert lc.complete(content="hi") == "ok"
    assert seen.get("thinking") is None


# ── the composition ─────────────────────────────────────────────────────

def test_the_executor_forwards_thinking_from_the_stream_it_already_opens():
    """`max_tokens` is above STREAM_ABOVE for every tuned node, so this call
    was always a live event stream — the events were simply discarded."""
    from services.blueprint.executors import AnthropicModel

    out: list[str] = []
    model = AnthropicModel(reasoning=out.append)

    final = object()

    first = ("The dashboard contract names five primary tasks, so the layout "
             "needs one section for each of them. ")

    class _Stream:
        def __iter__(self):
            for t in (first, "Quorum Status is a stat, not a list."):
                yield SimpleNamespace(
                    delta=SimpleNamespace(type="thinking_delta", thinking=t))
            # Text deltas must not be mistaken for reasoning.
            yield SimpleNamespace(
                delta=SimpleNamespace(type="text_delta", text='{"body":'))

        def get_final_message(self):
            return final

    assert model._stream_reasoning(_Stream()) is final
    # The first sentence went out DURING the stream, not at the end — which is
    # the whole difference between watching it think and reading the transcript.
    assert out == [first.strip(), "Quorum Status is a stat, not a list."]


def test_the_router_hands_the_sink_to_every_model():
    """A node without it is a silent stretch in the middle of a turn."""
    from services.blueprint.executors import tiered_router

    r = tiered_router(reasoning=print)
    assert r.default.reasoning is print
    assert all(m.reasoning is print for m in r.by_node.values())
    assert tiered_router().default.reasoning is None


def test_compose_hands_the_session_sink_down_to_the_router():
    import inspect

    from services.smith import compose
    from services.smith_session import SmithSession

    assert "tiered_router(reasoning=reasoning)" in inspect.getsource(
        compose.compose_route)
    assert "reasoning=self._reasoning" in inspect.getsource(
        SmithSession._compose)

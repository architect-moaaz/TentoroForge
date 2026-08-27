"""Regression tests for stream_with_idle_timeout.

These cover the hang previously observed in the generation pipeline: a wedged
``claude_agent_sdk.query()`` subprocess that stops emitting messages would let
the surrounding pipeline block forever. ``stream_with_idle_timeout`` enforces
a per-event idle timeout so a stalled producer surfaces as ``AgentTimeoutError``
instead.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest

from services.parallel_runner import (
    AgentTimeoutError,
    stream_with_idle_timeout,
)


class _FakeMessage:
    """Stand-in for claude_agent_sdk.types.Message — never actually inspected
    here because we monkeypatch ``stream_agent_messages`` to bypass parsing."""


async def _yield_then_hang() -> AsyncIterator[dict]:
    """First yields an event, then blocks forever — simulates a wedged SDK."""
    yield {"event": "log", "data": "{\"text\": \"started\"}"}
    await asyncio.Event().wait()  # never set


async def _yield_three() -> AsyncIterator[dict]:
    """Yields three quick events and returns cleanly."""
    for i in range(3):
        yield {"event": "log", "data": f"{{\"text\": \"evt-{i}\"}}"}


async def _raise_runtime_error() -> AsyncIterator[dict]:
    """Yields one event then raises a real exception."""
    yield {"event": "log", "data": "{\"text\": \"about-to-fail\"}"}
    raise RuntimeError("simulated SDK failure")


@pytest.fixture
def patch_stream(monkeypatch):
    """Replace stream_agent_messages so we can inject deterministic iterators.

    The real implementation walks Message objects produced by the Claude SDK;
    here we just pipe pre-baked SSE dicts through so tests don't need the SDK.
    """
    def _factory(target: AsyncIterator[dict]):
        async def _stream_agent_messages(messages, output_dir, event_prefix="", as_messages=False):
            async for evt in target:
                yield evt
        monkeypatch.setattr(
            "services.parallel_runner.stream_agent_messages",
            _stream_agent_messages,
        )
    return _factory


@pytest.mark.asyncio
async def test_planner_retry_succeeds_after_a_wedge(monkeypatch):
    from services.parallel_runner import stream_planner_with_retry, AgentTimeoutError

    calls = {"n": 0}

    async def fake_stream(name, output_dir, messages, as_messages=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AgentTimeoutError("planner", 600)  # first attempt wedges
        yield {"event": "message", "data": "{\"text\": \"the plan\"}"}

    monkeypatch.setattr("services.parallel_runner.stream_with_idle_timeout", fake_stream)
    collected: list = ["stale-from-failed-attempt"]
    out = []
    async for evt in stream_planner_with_retry("planner", "/tmp", lambda: iter([]), collected, max_attempts=3):
        if evt.get("event") == "message":
            collected.append("the plan")
        out.append(evt)

    assert calls["n"] == 2  # retried once
    assert any(e["event"] == "message" for e in out)  # success event delivered
    assert "stale-from-failed-attempt" not in collected  # cleared on retry


@pytest.mark.asyncio
async def test_planner_retry_reraises_after_exhausting_attempts(monkeypatch):
    from services.parallel_runner import stream_planner_with_retry, AgentTimeoutError

    async def always_wedge(name, output_dir, messages, as_messages=False):
        raise AgentTimeoutError("planner", 600)
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr("services.parallel_runner.stream_with_idle_timeout", always_wedge)
    collected: list = []
    with pytest.raises(AgentTimeoutError):
        async for _ in stream_planner_with_retry("planner", "/tmp", lambda: iter([]), collected, max_attempts=2):
            pass


@pytest.mark.asyncio
async def test_forwards_as_messages_kwarg(monkeypatch):
    # The planner streams with as_messages=True (TextBlocks -> 'message' events).
    # Wrapping it in stream_with_idle_timeout must preserve that, else the planner's
    # chat output disappears. Verify the kwarg is forwarded to stream_agent_messages.
    captured: dict = {}

    async def _spy(messages, output_dir, event_prefix="", as_messages=False):
        captured["as_messages"] = as_messages
        yield {"event": "message", "data": "{\"text\": \"plan\"}"}

    monkeypatch.setattr("services.parallel_runner.stream_agent_messages", _spy)
    out: list[dict] = []
    async for evt in stream_with_idle_timeout(
        "Planner",
        output_dir="/tmp",
        messages=iter([]),
        as_messages=True,
        timeout_seconds=5,
    ):
        out.append(evt)
    assert captured["as_messages"] is True
    assert out and out[0]["event"] == "message"


@pytest.mark.asyncio
async def test_passes_through_events_when_producer_completes(patch_stream):
    patch_stream(_yield_three())
    out: list[dict] = []
    async for evt in stream_with_idle_timeout(
        "TestAgent",
        output_dir="/tmp",
        messages=iter([]),  # bypassed by the patched stream
        timeout_seconds=5,
    ):
        out.append(evt)
    assert len(out) == 3
    assert out[0]["event"] == "log"


@pytest.mark.asyncio
async def test_raises_agent_timeout_when_producer_wedges(patch_stream):
    patch_stream(_yield_then_hang())
    received: list[dict] = []
    start = asyncio.get_event_loop().time()
    with pytest.raises(AgentTimeoutError) as excinfo:
        async for evt in stream_with_idle_timeout(
            "WedgedAgent",
            output_dir="/tmp",
            messages=iter([]),
            timeout_seconds=1,
        ):
            received.append(evt)
    elapsed = asyncio.get_event_loop().time() - start
    # First event arrives immediately; timeout fires ~1s after that idle period.
    assert 0.9 <= elapsed <= 5.0, f"expected ~1s timeout, got {elapsed:.2f}s"
    assert excinfo.value.name == "WedgedAgent"
    assert excinfo.value.timeout_seconds == 1
    assert received == [{"event": "log", "data": "{\"text\": \"started\"}"}]


@pytest.mark.asyncio
async def test_re_raises_producer_exception(patch_stream):
    patch_stream(_raise_runtime_error())
    received: list[dict] = []
    with pytest.raises(RuntimeError, match="simulated SDK failure"):
        async for evt in stream_with_idle_timeout(
            "FailingAgent",
            output_dir="/tmp",
            messages=iter([]),
            timeout_seconds=5,
        ):
            received.append(evt)
    # The pre-error event must still have been delivered.
    assert received[-1]["data"] == "{\"text\": \"about-to-fail\"}"

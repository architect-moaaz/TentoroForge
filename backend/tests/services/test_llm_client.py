"""llm_client — ChatAnthropic-backed shim for the anthropic client surface."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from services import llm_client


class _FakeChat:
    """Stands in for ChatAnthropic; records the lc messages it received."""
    last_kwargs: dict = {}
    last_messages: list = []

    def __init__(self, **kwargs):
        _FakeChat.last_kwargs = kwargs

    async def ainvoke(self, msgs):
        _FakeChat.last_messages = msgs
        m = AIMessage(content="async-reply")
        m.usage_metadata = {"input_tokens": 10, "output_tokens": 3,
                            "input_token_details": {"cache_read": 4}}
        m.response_metadata = {"stop_reason": "end_turn"}
        return m

    def invoke(self, msgs):
        _FakeChat.last_messages = msgs
        return AIMessage(content=[{"type": "text", "text": "sync-reply"}])

    async def astream(self, msgs):
        _FakeChat.last_messages = msgs
        for part in ("chunk-a", "chunk-b"):
            yield AIMessage(content=part)


@pytest.fixture(autouse=True)
def _patch_chat(monkeypatch):
    import langchain_anthropic
    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", _FakeChat)


@pytest.mark.asyncio
async def test_async_create_matches_anthropic_shape():
    client = llm_client.AsyncAnthropic(api_key="k")
    resp = await client.messages.create(
        model="claude-sonnet-4-6", max_tokens=64, temperature=0.0,
        system="sys", messages=[{"role": "user", "content": "hi"}])
    assert resp.content[0].text == "async-reply"
    assert resp.content[0].type == "text"
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 10 and resp.usage.cache_read_input_tokens == 4
    assert _FakeChat.last_kwargs["model"] == "claude-sonnet-4-6"
    assert _FakeChat.last_kwargs["temperature"] == 0.0
    assert isinstance(_FakeChat.last_messages[0], SystemMessage)
    assert isinstance(_FakeChat.last_messages[1], HumanMessage)


def test_sync_create_joins_block_content():
    client = llm_client.Anthropic(api_key="k")
    resp = client.messages.create(
        model="m", max_tokens=8, messages=[{"role": "user", "content": "x"}])
    assert resp.content[0].text == "sync-reply"


@pytest.mark.asyncio
async def test_stream_context_manager_text_stream_and_final():
    client = llm_client.AsyncAnthropic(api_key="k")
    parts = []
    async with client.messages.stream(
            model="m", max_tokens=8, system="s",
            messages=[{"role": "user", "content": "x"}]) as s:
        async for chunk in s.text_stream:
            parts.append(chunk)
        final = await s.get_final_message()
    assert parts == ["chunk-a", "chunk-b"]
    assert final.content[0].text == "chunk-achunk-b"


def test_legacy_escape_hatch_returns_real_sdk(monkeypatch):
    monkeypatch.setenv("FORGE_LEGACY_ANTHROPIC", "1")
    import anthropic
    assert isinstance(llm_client.Anthropic(api_key="k"), anthropic.Anthropic)
    assert isinstance(llm_client.AsyncAnthropic(api_key="k"), anthropic.AsyncAnthropic)


@pytest.mark.asyncio
async def test_multimodal_content_passes_through():
    client = llm_client.AsyncAnthropic(api_key="k")
    blocks = [{"type": "image", "source": {"type": "base64", "data": "…"}},
              {"type": "text", "text": "what is this?"}]
    await client.messages.create(model="m", max_tokens=8,
                                 messages=[{"role": "user", "content": blocks}])
    assert _FakeChat.last_messages[0].content == blocks


def test_thinking_blocks_surface_with_anthropic_shape(monkeypatch):
    """Smith's CoT streaming iterates blocks via hasattr(b, "thinking") —
    the shim must preserve thinking blocks (in API order) when the caller
    requested extended thinking, and forward the config to the model."""
    class _ThinkChat(_FakeChat):
        def invoke(self, msgs):
            return AIMessage(content=[
                {"type": "thinking", "thinking": "pondering the schema…"},
                {"type": "text", "text": '{"tool":"answer","args":{}}'},
            ])
    import langchain_anthropic
    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", _ThinkChat)

    client = llm_client.Anthropic(api_key="k")
    resp = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=2000,
        messages=[{"role": "user", "content": "x"}],
        thinking={"type": "enabled", "budget_tokens": 1024}, temperature=1.0)
    assert _ThinkChat.last_kwargs["thinking"] == {"type": "enabled",
                                                 "budget_tokens": 1024}
    thinks = [b for b in resp.content if hasattr(b, "thinking")]
    texts = [b for b in resp.content if hasattr(b, "text")]
    assert thinks and thinks[0].thinking == "pondering the schema…"
    assert texts and texts[0].text == '{"tool":"answer","args":{}}'

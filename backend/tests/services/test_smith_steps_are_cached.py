"""Smith's steps are read from the cache (ToroCommerce, forge-v3, 2026-10-07).

Its repair turns read 5.0M tokens with no cache hit — $15.93 of a $24.91
build — because every step sent the rules, the tools and the application as
one fresh text. They lead now, each marked for the cache; what changes every
step follows. And the ledger prices what was cached as cached.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from services.smith import loop
from services.smith.loop import Observation


def test_a_step_sends_the_rules_and_the_app_as_cached_parts_and_the_turn_after(monkeypatch):
    sent = []

    def provider(prompt, reasoning=None, images=()):
        sent.append(prompt)
        return json.dumps({"tool": "done", "args": {}, "why": "x"})
    monkeypatch.setattr("services.smith.understand_ask._default_provider", provider)
    obs = [Observation(tool="read_rows", args={"entity": "Order"}, status="read", said="3 rows")]
    out = loop.next_step("rename the zebra crossing widget", "APP CONTEXT HERE", obs, [("user", "hi")])
    assert out["tool"] == "done"
    rules, app, turn = sent[0]
    assert rules["cache_control"] == {"type": "ephemeral"} and "THE TOOLS" in rules["text"]
    assert app["cache_control"] == {"type": "ephemeral"} and "APP CONTEXT HERE" in app["text"]
    assert "cache_control" not in turn and "rename the zebra crossing widget" in turn["text"] and "3 rows" in turn["text"]
    assert "rename the zebra crossing widget" not in rules["text"] + app["text"], "nothing that changes each step is cached"


def test_two_steps_of_a_turn_share_their_cached_parts(monkeypatch):
    sent = []
    monkeypatch.setattr("services.smith.understand_ask._default_provider",
                        lambda prompt, reasoning=None, images=(): sent.append(prompt) or '{"tool": "done", "args": {}}')
    loop.next_step("x", "APP", [], [])
    loop.next_step("x", "APP", [Observation(tool="grep", args={}, status="read", said="found")], [])
    assert sent[0][0] == sent[1][0] and sent[0][1] == sent[1][1] and sent[0][2] != sent[1][2]


def test_a_provider_that_takes_text_still_gets_the_whole_prompt():
    seen = []
    loop.next_step("add a tab", "APP", [], [], provider=lambda p: seen.append(p) or '{"tool": "done", "args": {}}')
    assert isinstance(seen[0], str) and "add a tab" in seen[0] and "THE TOOLS" in seen[0] and "APP" in seen[0]


def test_cached_tokens_are_priced_as_cached(monkeypatch):
    from services import llm_client as L
    monkeypatch.setattr("services.build_usage.spent", lambda *a, **k: None)
    msg = L._to_message(SimpleNamespace(content="OK", response_metadata={}, usage_metadata={
        "input_tokens": 7213, "output_tokens": 2, "input_token_details": {"cache_read": 7204}}), "m")
    assert (msg.usage.input_tokens, msg.usage.cache_read_input_tokens) == (9, 7204), \
        "LangChain's total includes the cached tokens; Anthropic's input_tokens does not"
    msg = L._to_message(SimpleNamespace(content="OK", response_metadata={}, usage_metadata={
        "input_tokens": 7213, "output_tokens": 2, "input_token_details": {"ephemeral_5m_input_tokens": 7204}}), "m")
    assert (msg.usage.input_tokens, msg.usage.cache_creation_input_tokens) == (9, 7204)

"""Tests for the LLM JSX→schema converter."""
from __future__ import annotations

import json

import pytest

from services import magic_jsx_to_schema as m


class TestExtractJSONObject:
    def test_bare_json(self):
        assert m._extract_json_object('{"type":"Card"}') == {"type": "Card"}

    def test_stripped_of_markdown_fence(self):
        raw = '```json\n{"type":"Card"}\n```'
        assert m._extract_json_object(raw) == {"type": "Card"}

    def test_finds_json_after_prose(self):
        raw = 'Sure! Here is the schema:\n\n{"type":"Card","props":{"title":"X"}}\n\nDone.'
        assert m._extract_json_object(raw) == {"type": "Card", "props": {"title": "X"}}

    def test_handles_nested_braces(self):
        raw = '{"type":"Stack","children":[{"type":"Text","props":{"content":"hi"}}]}'
        assert m._extract_json_object(raw) == json.loads(raw)

    def test_handles_string_with_braces(self):
        # Balance scan must not confuse `{` inside string with structural {.
        raw = '{"type":"Text","props":{"content":"format: {name}"}}'
        assert m._extract_json_object(raw) == json.loads(raw)

    def test_returns_none_on_no_object(self):
        assert m._extract_json_object("no braces here") is None

    def test_returns_none_on_empty(self):
        assert m._extract_json_object("") is None
        assert m._extract_json_object("   ") is None

    def test_returns_none_on_malformed(self):
        assert m._extract_json_object('{"type":"Card"') is None


class TestValidateNode:
    def test_accepts_bare_type(self):
        assert m._validate_node({"type": "Card"}) == {"type": "Card"}

    def test_accepts_type_with_props(self):
        node = {"type": "Button", "props": {"label": "Save"}}
        assert m._validate_node(node) == node

    def test_accepts_nested_children(self):
        node = {
            "type": "Stack",
            "children": [
                {"type": "Text", "props": {"content": "Hi"}},
                {"type": "Button", "props": {"label": "Go"}},
            ],
        }
        assert m._validate_node(node) == node

    def test_prunes_invalid_children(self):
        node = {
            "type": "Stack",
            "children": [
                {"type": "Text"},
                {"not_a_type": "wat"},  # should be dropped
                None,  # should be dropped
            ],
        }
        result = m._validate_node(node)
        assert result == {"type": "Stack", "children": [{"type": "Text"}]}

    def test_accepts_string_children(self):
        node = {"type": "Text", "children": ["hello"]}
        assert m._validate_node(node) == node

    def test_rejects_missing_type(self):
        assert m._validate_node({"props": {}}) is None

    def test_rejects_non_dict(self):
        assert m._validate_node("not a dict") is None
        assert m._validate_node(None) is None
        assert m._validate_node(42) is None

    def test_rejects_empty_type(self):
        assert m._validate_node({"type": ""}) is None

    def test_drops_unknown_top_level_fields(self):
        node = {"type": "Card", "extra": "should be gone"}
        assert m._validate_node(node) == {"type": "Card"}


class TestConvertJSXToSchema:
    @pytest.mark.asyncio
    async def test_returns_none_on_empty_jsx(self):
        assert await m.convert_jsx_to_schema("") is None
        assert await m.convert_jsx_to_schema("   ") is None

    @pytest.mark.asyncio
    async def test_uses_injected_query_fn(self):
        captured: dict = {}

        async def _fake(system: str, user: str) -> str:
            captured["system"] = system
            captured["user"] = user
            return '{"type":"Card","props":{"title":"Total Revenue"}}'

        result = await m.convert_jsx_to_schema(
            "<Card>Total Revenue</Card>",
            hint="wellness dashboard",
            query_fn=_fake,
        )
        assert result == {"type": "Card", "props": {"title": "Total Revenue"}}
        # System prompt names the allowed component set + rules.
        assert "schemaVersion" in captured["system"]
        assert "Card" in captured["system"]
        # Hint threaded into the user prompt.
        assert "wellness dashboard" in captured["user"]
        # JSX included verbatim.
        assert "<Card>Total Revenue</Card>" in captured["user"]

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_exception(self):
        async def _boom(system: str, user: str) -> str:
            raise RuntimeError("provider down")

        assert await m.convert_jsx_to_schema("<Card/>", query_fn=_boom) is None

    @pytest.mark.asyncio
    async def test_returns_none_on_non_json_response(self):
        async def _prose(system: str, user: str) -> str:
            return "Sorry, I can't do that."

        assert await m.convert_jsx_to_schema("<Card/>", query_fn=_prose) is None

    @pytest.mark.asyncio
    async def test_returns_none_on_shape_mismatch(self):
        async def _bad_shape(system: str, user: str) -> str:
            return '{"not_a_node": true}'

        assert await m.convert_jsx_to_schema("<Card/>", query_fn=_bad_shape) is None

    @pytest.mark.asyncio
    async def test_strips_markdown_fence_from_response(self):
        async def _fenced(system: str, user: str) -> str:
            return '```json\n{"type":"Text","props":{"content":"hi"}}\n```'

        result = await m.convert_jsx_to_schema("<p>hi</p>", query_fn=_fenced)
        assert result == {"type": "Text", "props": {"content": "hi"}}

    @pytest.mark.asyncio
    async def test_passes_hint_when_absent(self):
        captured: dict = {}

        async def _fake(system: str, user: str) -> str:
            captured["user"] = user
            return '{"type":"Card"}'

        await m.convert_jsx_to_schema("<Card/>", query_fn=_fake)
        # Absent hint = no "Context hint" line in user prompt.
        assert "Context hint" not in captured["user"]

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = await m.convert_jsx_to_schema("<Card/>")
        assert result is None


class TestSystemPromptGuardrails:
    def test_prompt_lists_allowed_types(self):
        prompt = m._build_system_prompt()
        for critical in ("Card", "Button", "Text", "Table", "MetricTile"):
            assert critical in prompt

    def test_prompt_forbids_prose_output(self):
        prompt = m._build_system_prompt()
        assert "no prose" in prompt.lower() or "no markdown fences" in prompt.lower()

    def test_prompt_says_drop_hooks(self):
        prompt = m._build_system_prompt()
        # Anti-regression for the JSX→schema translation rules the caller
        # depends on: no useState, no imports leaking into props, etc.
        assert "useState" in prompt or "hooks" in prompt

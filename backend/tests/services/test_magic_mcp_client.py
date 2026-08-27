"""Tests for the HTTP client to 21st.dev's MCP server."""
from __future__ import annotations

import pytest

from services import magic_mcp_client


class TestExtractText:
    def test_extracts_single_text_block(self):
        result = {"content": [{"type": "text", "text": "hello"}]}
        assert magic_mcp_client.extract_text(result) == "hello"

    def test_concats_multiple_text_blocks(self):
        result = {"content": [
            {"type": "text", "text": "one "},
            {"type": "text", "text": "two"},
        ]}
        assert magic_mcp_client.extract_text(result) == "one two"

    def test_skips_non_text_blocks(self):
        result = {"content": [
            {"type": "image", "url": "..."},
            {"type": "text", "text": "kept"},
        ]}
        assert magic_mcp_client.extract_text(result) == "kept"

    def test_fallback_to_result_text(self):
        # Some MCP responses put text under result.text directly.
        assert magic_mcp_client.extract_text({"text": "direct"}) == "direct"

    def test_returns_empty_on_empty(self):
        assert magic_mcp_client.extract_text({}) == ""
        assert magic_mcp_client.extract_text({"content": []}) == ""

    def test_returns_empty_on_non_dict(self):
        assert magic_mcp_client.extract_text(None) == ""  # type: ignore[arg-type]
        assert magic_mcp_client.extract_text("string") == ""  # type: ignore[arg-type]

    def test_caps_at_max_bytes(self):
        big = "x" * 500_000
        result = {"content": [{"type": "text", "text": big}]}
        out = magic_mcp_client.extract_text(result)
        assert len(out) == magic_mcp_client._MAX_TEXT_BYTES


class TestParseJSONFromText:
    def test_parses_bare_object(self):
        assert magic_mcp_client.parse_json_from_text('{"a":1}') == {"a": 1}

    def test_parses_bare_array(self):
        assert magic_mcp_client.parse_json_from_text('[1,2,3]') == [1, 2, 3]

    def test_strips_markdown_fence(self):
        assert magic_mcp_client.parse_json_from_text('```json\n{"a":1}\n```') == {"a": 1}

    def test_strips_generic_fence(self):
        assert magic_mcp_client.parse_json_from_text('```\n{"a":1}\n```') == {"a": 1}

    def test_finds_object_after_prose(self):
        raw = 'Here you go:\n{"a":1}\nDone.'
        assert magic_mcp_client.parse_json_from_text(raw) == {"a": 1}

    def test_returns_none_on_empty(self):
        assert magic_mcp_client.parse_json_from_text("") is None
        assert magic_mcp_client.parse_json_from_text("no JSON here") is None

    def test_returns_none_on_malformed(self):
        assert magic_mcp_client.parse_json_from_text('{"a":1') is None


class TestCallToolGating:
    @pytest.mark.asyncio
    async def test_returns_empty_when_flag_off(self, monkeypatch):
        monkeypatch.delenv("FORGE_21ST_MCP", raising=False)
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-x")
        assert await magic_mcp_client.call_tool("generate", {}) == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_key(self, monkeypatch):
        monkeypatch.setenv("FORGE_21ST_MCP", "on")
        monkeypatch.delenv("FORGE_21ST_API_KEY", raising=False)
        assert await magic_mcp_client.call_tool("generate", {}) == {}


class TestHighLevelHelpers:
    @pytest.mark.asyncio
    async def test_generate_component_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.delenv("FORGE_21ST_MCP", raising=False)
        assert await magic_mcp_client.generate_component("anything") == ""

    @pytest.mark.asyncio
    async def test_search_components_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.delenv("FORGE_21ST_MCP", raising=False)
        assert await magic_mcp_client.search_components("anything") == []

    @pytest.mark.asyncio
    async def test_get_component_code_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.delenv("FORGE_21ST_MCP", raising=False)
        assert await magic_mcp_client.get_component_code(123) == ""


class TestSearchParsing:
    """Verify the markdown-response parser survives the real 21st.dev format
    (captured from a live tools/call on 2026-08-12)."""

    _FIXTURE = (
        "3 result(s) across 21st.dev (metadata only).\n\n"
        "### [component] Dashboard Configuration  [id: 8693]\n"
        "by dgearsonu1\n"
        "Dashboard Configuration\n\n"
        "Toggle widget visibility and manage your dashboard layout settings.\n"
        "preview: https://cdn.21st.dev/x/preview.png\n"
        "install: npx shadcn@latest add ...\n"
        "→ get the code: get_component({ id: 8693 })\n\n"
        "### [component] Health Stat Card  [id: 8619]\n"
        "by ruhith369\n"
        "The HealthStatCard component is a beautifully designed card.\n"
        "preview: https://cdn.21st.dev/y/preview.png\n"
        "install: npx shadcn@latest add ...\n"
        "→ get the code: get_component({ id: 8619 })\n"
    )

    @pytest.mark.asyncio
    async def test_parses_real_response_shape(self, monkeypatch):
        # Stub call_tool to hand back the live-captured fixture wrapped in
        # the standard MCP content envelope.
        async def _fake_call(name, args):
            assert name == "search"
            return {"content": [{"type": "text", "text": self._FIXTURE}]}

        monkeypatch.setattr(magic_mcp_client, "call_tool", _fake_call)
        results = await magic_mcp_client.search_components("dashboard")
        assert len(results) == 2
        assert results[0]["id"] == 8693
        assert results[0]["name"] == "Dashboard Configuration"
        assert results[0]["author"] == "dgearsonu1"
        assert "widget visibility" in results[0]["description"]
        assert results[0]["preview"].startswith("https://cdn.21st.dev/")
        assert results[1]["id"] == 8619
        assert results[1]["name"] == "Health Stat Card"

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_results(self, monkeypatch):
        async def _fake_call(name, args):
            return {"content": [{"type": "text", "text": "0 result(s)."}]}
        monkeypatch.setattr(magic_mcp_client, "call_tool", _fake_call)
        assert await magic_mcp_client.search_components("nothing") == []

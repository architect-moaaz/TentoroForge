"""Tests for the 21st.dev Magic MCP wiring.

Covers the two-gate flag+key contract, config shape, and the merge_into
helper that composes with an existing ClaudeAgentOptions config.
"""
from __future__ import annotations

import pytest

from services import magic_mcp


class TestGate:
    def test_off_when_no_flag(self, monkeypatch):
        monkeypatch.delenv("FORGE_21ST_MCP", raising=False)
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-something")
        assert magic_mcp.is_enabled() is False

    def test_off_when_no_key(self, monkeypatch):
        monkeypatch.setenv("FORGE_21ST_MCP", "on")
        monkeypatch.delenv("FORGE_21ST_API_KEY", raising=False)
        assert magic_mcp.is_enabled() is False

    def test_off_when_key_is_blank(self, monkeypatch):
        monkeypatch.setenv("FORGE_21ST_MCP", "on")
        monkeypatch.setenv("FORGE_21ST_API_KEY", "   ")
        assert magic_mcp.is_enabled() is False

    def test_on_when_both_present(self, monkeypatch):
        monkeypatch.setenv("FORGE_21ST_MCP", "on")
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-abc")
        assert magic_mcp.is_enabled() is True

    @pytest.mark.parametrize("val", ["1", "true", "on", "yes", "warn", "strict"])
    def test_truthy_flag_values(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_21ST_MCP", val)
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-abc")
        assert magic_mcp.is_enabled() is True

    @pytest.mark.parametrize("val", ["", "0", "off", "false", "no", "asdf"])
    def test_falsy_flag_values(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_21ST_MCP", val)
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-abc")
        assert magic_mcp.is_enabled() is False


class TestGetMcpConfig:
    def test_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv("FORGE_21ST_MCP", raising=False)
        assert magic_mcp.get_mcp_config() is None

    def test_shape_when_enabled(self, monkeypatch):
        monkeypatch.setenv("FORGE_21ST_MCP", "on")
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-live-42")
        cfg = magic_mcp.get_mcp_config()
        assert cfg is not None
        assert cfg["type"] == "stdio"
        assert cfg["command"] == "npx"
        assert cfg["args"] == ["-y", "@21st-dev/magic@latest"]
        # Key MUST be in env, not argv — argv leaks in `ps`.
        assert "sk-live-42" not in " ".join(cfg["args"])
        assert cfg["env"]["TWENTY_FIRST_API_KEY"] == "sk-live-42"
        assert cfg["env"]["API_KEY_21ST"] == "sk-live-42"


class TestMergeInto:
    def test_no_op_when_disabled(self, monkeypatch):
        monkeypatch.delenv("FORGE_21ST_MCP", raising=False)
        servers, tools = magic_mcp.merge_into({}, ["Read", "Write"])
        assert servers == {}
        assert tools == ["Read", "Write"]

    def test_adds_server_and_tools_when_enabled(self, monkeypatch):
        monkeypatch.setenv("FORGE_21ST_MCP", "on")
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-x")
        servers, tools = magic_mcp.merge_into({}, ["Read", "Write"])
        assert "magic-mcp" in servers
        assert servers["magic-mcp"]["type"] == "stdio"
        for expected in magic_mcp.ALLOWED_TOOLS:
            assert expected in tools
        assert "Read" in tools and "Write" in tools

    def test_preserves_existing_servers(self, monkeypatch):
        monkeypatch.setenv("FORGE_21ST_MCP", "on")
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-x")
        prior = {"illustrations": {"type": "stdio", "command": "python"}}
        servers, _ = magic_mcp.merge_into(prior, [])
        assert "illustrations" in servers
        assert "magic-mcp" in servers
        # Input should not have been mutated.
        assert "magic-mcp" not in prior

    def test_no_duplicate_tools(self, monkeypatch):
        monkeypatch.setenv("FORGE_21ST_MCP", "on")
        monkeypatch.setenv("FORGE_21ST_API_KEY", "sk-x")
        # Pre-seed with one of the magic tools; result should not double it.
        seed = list(magic_mcp.ALLOWED_TOOLS[:1])
        _, tools = magic_mcp.merge_into({}, seed)
        for t in magic_mcp.ALLOWED_TOOLS:
            assert tools.count(t) == 1


class TestPromptBlock:
    def test_block_forbids_shipping_jsx(self):
        # The whole point: the design agent must extract tokens, not JSX.
        # Anti-regression guard for the intent of the block.
        assert "SHIP SCHEMA JSON" in magic_mcp.PROMPT_BLOCK
        assert "NEVER paste raw JSX" in magic_mcp.PROMPT_BLOCK
        assert "INSPIRATION ONLY" in magic_mcp.PROMPT_BLOCK

    def test_block_names_tools(self):
        # Must reference at least the two we use in the search→get_component
        # flow. If either is missing, the design agent doesn't know how to
        # invoke inspiration mode.
        assert "mcp__magic-mcp__search" in magic_mcp.PROMPT_BLOCK
        assert "mcp__magic-mcp__get_component" in magic_mcp.PROMPT_BLOCK

    def test_block_flags_paid_tools(self):
        # Anti-regression: users can't afford runaway paid calls. The prompt
        # must mark get_component as PAID and cap the budget.
        assert "PAID" in magic_mcp.PROMPT_BLOCK
        assert "get_component" in magic_mcp.PROMPT_BLOCK

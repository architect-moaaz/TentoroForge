"""Smoke tests for the page schema agent's MCP server registration.

These tests exercise the option-construction path that registers the
illustrations MCP server without actually hitting the LLM. They verify
the agent module still imports, still runs end-to-end (with the real
LLM call mocked out), and that the wrapper exposes the illustrations
MCP server + allowed tools to claude_agent_sdk via ClaudeAgentOptions.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from agents.page_schema_agent import (
    run_page_schema_agent,
    _get_illustrations_mcp_config,
    _ILLUSTRATIONS_ALLOWED_TOOLS,
    _ILLUSTRATIONS_SERVER_NAME,
)


@pytest.mark.asyncio
async def test_schema_agent_constructs_options_with_mcp_registration(tmp_path):
    """Smoke test — exercises the agent's option-construction path without
    actually hitting the LLM. If MCP wiring crashes at construction, this
    test fails."""
    fake_schema = {
        "schemaVersion": "2", "id": "x", "route": "/x", "layout": "main",
        "root": {"type": "Stack", "id": "r", "children": []},
    }
    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(return_value=fake_schema),
    ):
        await run_page_schema_agent(
            str(tmp_path),
            {"entities": {}},
            {"route": "/x", "entity": None, "type": "list", "name": "X"},
        )
    # No assertions beyond reaching this point — the patch ensures no real
    # LLM call. Module-level imports + run_page_schema_agent must still work
    # after the MCP registration changes.


def test_illustrations_mcp_config_uses_stdio_subprocess():
    """The config we pass to ClaudeAgentOptions.mcp_servers must conform to
    McpStdioServerConfig: type='stdio', command+args that launch the
    illustrations server as a subprocess, and env with PYTHONPATH so the
    child can locate the `illustrations_mcp` package.

    In-process registration (McpSdkServerConfig) is incompatible with the
    bundled claude CLI's subprocess transport — see _get_illustrations_mcp_config
    for context."""
    import sys
    cfg = _get_illustrations_mcp_config()
    assert cfg["type"] == "stdio"
    assert cfg["command"] == sys.executable
    assert cfg["args"] == ["-m", "illustrations_mcp.illustrations_server"]
    # PYTHONPATH must include backend/ so the subprocess can import our package.
    pythonpath = cfg["env"]["PYTHONPATH"]
    assert "backend" in pythonpath
    # No `instance` key — we no longer pass an in-process server object.
    assert "instance" not in cfg
    assert "name" not in cfg  # stdio configs are keyed by dict key, not a 'name' field


def test_illustrations_allowed_tools_follow_sdk_naming():
    """claude_agent_sdk surfaces SDK-MCP tools to the LLM as
    `mcp__<server>__<tool>`. The agent must whitelist them in this exact
    form — otherwise the LLM is forbidden from calling them."""
    assert _ILLUSTRATIONS_ALLOWED_TOOLS == [
        f"mcp__{_ILLUSTRATIONS_SERVER_NAME}__list_illustrations",
        f"mcp__{_ILLUSTRATIONS_SERVER_NAME}__get_illustration_svg",
    ]


@pytest.mark.asyncio
async def test_collect_llm_text_uses_anthropic_sdk_when_api_key(monkeypatch):
    """With ANTHROPIC_API_KEY set, page generation runs on the Anthropic SDK
    (reliable transport), NOT the bundled-CLI shared path."""
    from unittest.mock import MagicMock
    from agents import page_schema_agent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    block = MagicMock(); block.text = "{}"
    msg = MagicMock(); msg.content = [block]
    client = MagicMock(); client.messages.create = AsyncMock(return_value=msg)
    from services import llm_client
    monkeypatch.setattr(llm_client, "AsyncAnthropic", MagicMock(return_value=client))

    out = await page_schema_agent._collect_llm_text("hello")
    assert out == "{}"
    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_collect_llm_text_falls_back_to_mcp_without_api_key(monkeypatch):
    """No API key → fall back to the bundled-CLI shared path WITH the illustrations
    MCP server + tools registered."""
    from agents import page_schema_agent

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    captured: dict = {}

    async def fake_shared(prompt, mcp_servers=None, allowed_tools=None, max_turns=1):
        captured["mcp_servers"] = mcp_servers
        captured["allowed_tools"] = allowed_tools
        return "{}"

    monkeypatch.setattr("agents.feature_slice_schema_agent._collect_llm_text", fake_shared)
    await page_schema_agent._collect_llm_text("hello")
    assert _ILLUSTRATIONS_SERVER_NAME in captured["mcp_servers"]
    assert captured["allowed_tools"] == _ILLUSTRATIONS_ALLOWED_TOOLS

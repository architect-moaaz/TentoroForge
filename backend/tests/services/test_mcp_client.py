"""Tests for services.mcp_client — the platform-side MCP wrapper.

We do NOT hit the network. Everything is mocked at the boundary:

  * `_open_session` is patched to yield a fake session that produces
    canned `list_tools` / `call_tool` results, so the domain-level
    behaviour (cache, error mapping, header assembly) is exercised
    without spinning up a real MCP server.
  * Auth-header helpers and secret decoding are tested directly
    against the real crypto module (round-trip via a test-only master
    secret set in the autouse fixture).
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def _master_secret(monkeypatch):
    monkeypatch.setenv(
        "FORGE_INTEGRATIONS_SECRET",
        "test-master-secret-that-is-long-enough-1234567890",
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    """The tools cache is module-level; reset between tests."""
    from services.mcp_client import _cache_clear
    _cache_clear()
    yield
    _cache_clear()


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

def _server(
    *,
    auth_kind: str = "none",
    transport: str = "http",
    secret: str | None = None,
    auth_header_name: str | None = None,
):
    """Build a fake PlatformMcpServer-shaped object. Encrypts `secret`
    with the real crypto module so `_decode_secret` round-trips correctly."""
    from services.platform_integrations_crypto import encrypt
    ct = iv = None
    if secret is not None:
        ct, iv = encrypt("mcp", secret)
    return SimpleNamespace(
        id=uuid.uuid4(),
        server_url="https://example.com/mcp",
        transport=transport,
        auth_kind=auth_kind,
        auth_secret_ct=ct,
        auth_secret_iv=iv,
        auth_header_name=auth_header_name,
    )


class _FakeTool:
    def __init__(self, name, description="", input_schema=None):
        self.name = name
        self.description = description
        self.inputSchema = input_schema or {"type": "object"}


class _FakeToolsResult:
    def __init__(self, tools):
        self.tools = tools


class _FakeCallResult:
    def __init__(self, content, is_error=False):
        self.content = content
        self.isError = is_error


class _FakeSession:
    """Just the two methods mcp_client uses."""

    def __init__(self, tools=None, call_result=None, raise_on_call=None):
        self._tools = tools or []
        self._call_result = call_result
        self._raise = raise_on_call

    async def list_tools(self):
        return _FakeToolsResult(self._tools)

    async def call_tool(self, name, arguments):
        if self._raise:
            raise self._raise
        return self._call_result or _FakeCallResult([])


def _mock_open_session(session):
    @asynccontextmanager
    async def _cm(server):
        yield session
    return _cm


# --------------------------------------------------------------------------- #
# Auth header assembly
# --------------------------------------------------------------------------- #

def test_build_headers_none_returns_empty():
    from services.mcp_client import _build_headers
    srv = _server(auth_kind="none")
    assert _build_headers(srv, None) == {}


def test_build_headers_bearer():
    from services.mcp_client import _build_headers
    srv = _server(auth_kind="bearer", secret="tok_abc")
    assert _build_headers(srv, "tok_abc") == {"Authorization": "Bearer tok_abc"}


def test_build_headers_apikey():
    from services.mcp_client import _build_headers
    srv = _server(auth_kind="apikey_header", secret="s", auth_header_name="X-Api-Key")
    assert _build_headers(srv, "s") == {"X-Api-Key": "s"}


def test_build_headers_apikey_missing_header_raises_config():
    from services.mcp_client import _build_headers, McpClientError
    srv = _server(auth_kind="apikey_header", secret="s", auth_header_name=None)
    with pytest.raises(McpClientError) as ei:
        _build_headers(srv, "s")
    assert ei.value.kind == "config"


def test_build_headers_bearer_without_secret_raises_auth():
    from services.mcp_client import _build_headers, McpClientError
    srv = _server(auth_kind="bearer")
    with pytest.raises(McpClientError) as ei:
        _build_headers(srv, None)
    assert ei.value.kind == "auth"


# --------------------------------------------------------------------------- #
# Secret decoding
# --------------------------------------------------------------------------- #

def test_decode_secret_none_returns_none():
    from services.mcp_client import _decode_secret
    assert _decode_secret(_server(auth_kind="none")) is None


def test_decode_secret_round_trips():
    from services.mcp_client import _decode_secret
    srv = _server(auth_kind="bearer", secret="tok_xyz")
    assert _decode_secret(srv) == "tok_xyz"


# --------------------------------------------------------------------------- #
# list_tools
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_list_tools_returns_typed_tools():
    from services import mcp_client
    session = _FakeSession(tools=[
        _FakeTool("search", "Search the web", {"type": "object", "properties": {"q": {}}}),
        _FakeTool("scrape", "Scrape a URL"),
    ])
    srv = _server()
    with patch.object(mcp_client, "_open_session", _mock_open_session(session)):
        tools = await mcp_client.list_tools(srv)
    assert [t.name for t in tools] == ["search", "scrape"]
    assert tools[0].description == "Search the web"
    assert "properties" in tools[0].input_schema


@pytest.mark.asyncio
async def test_list_tools_uses_cache_on_second_call():
    from services import mcp_client
    calls = {"n": 0}
    session = _FakeSession(tools=[_FakeTool("x")])

    @asynccontextmanager
    async def _cm(server):
        calls["n"] += 1
        yield session

    srv = _server(auth_kind="bearer", secret="s")
    with patch.object(mcp_client, "_open_session", _cm):
        await mcp_client.list_tools(srv)
        await mcp_client.list_tools(srv)  # served from cache
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_list_tools_bypasses_cache_when_use_cache_false():
    from services import mcp_client
    calls = {"n": 0}
    session = _FakeSession(tools=[])

    @asynccontextmanager
    async def _cm(server):
        calls["n"] += 1
        yield session

    srv = _server()
    with patch.object(mcp_client, "_open_session", _cm):
        await mcp_client.list_tools(srv, use_cache=False)
        await mcp_client.list_tools(srv, use_cache=False)
    assert calls["n"] == 2


# --------------------------------------------------------------------------- #
# call_tool
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_call_tool_returns_content_and_flag():
    from services import mcp_client
    block = SimpleNamespace(model_dump=lambda: {"type": "text", "text": "hi"})
    session = _FakeSession(call_result=_FakeCallResult([block]))
    srv = _server()
    with patch.object(mcp_client, "_open_session", _mock_open_session(session)):
        result = await mcp_client.call_tool(srv, "search", {"q": "cats"})
    assert result == {"content": [{"type": "text", "text": "hi"}], "isError": False}


# --------------------------------------------------------------------------- #
# probe (never raises)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_probe_ok_returns_tool_count():
    from services import mcp_client
    session = _FakeSession(tools=[_FakeTool("a"), _FakeTool("b"), _FakeTool("c")])
    srv = _server()
    with patch.object(mcp_client, "_open_session", _mock_open_session(session)):
        r = await mcp_client.probe(srv)
    assert r == {"ok": True, "tool_count": 3}


@pytest.mark.asyncio
async def test_probe_maps_client_error_to_payload():
    from services import mcp_client

    @asynccontextmanager
    async def _cm(server):
        raise mcp_client.McpClientError("unreachable", "connection refused")
        yield  # pragma: no cover

    srv = _server()
    with patch.object(mcp_client, "_open_session", _cm):
        r = await mcp_client.probe(srv)
    assert r["ok"] is False
    assert r["tool_count"] == 0
    assert r["kind"] == "unreachable"
    assert "connection refused" in r["error"]


@pytest.mark.asyncio
async def test_probe_swallows_unexpected_exceptions():
    from services import mcp_client

    @asynccontextmanager
    async def _cm(server):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    srv = _server()
    with patch.object(mcp_client, "_open_session", _cm):
        r = await mcp_client.probe(srv)
    assert r["ok"] is False
    assert r["kind"] == "protocol"


# --------------------------------------------------------------------------- #
# Domain error mapping (checked by injecting exceptions through _open_session
# by mocking the underlying SDK clients).
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_open_session_maps_httpx_connect_error():
    """Bypass the SDK entirely: patch streamablehttp_client to raise, then
    verify _open_session re-raises as McpClientError(unreachable)."""
    from services import mcp_client

    @asynccontextmanager
    async def _boom(**kw):
        raise httpx.ConnectError("nope")
        yield  # pragma: no cover

    srv = _server()
    with patch.object(mcp_client, "streamablehttp_client", _boom):
        with pytest.raises(mcp_client.McpClientError) as ei:
            async with mcp_client._open_session(srv):
                pass
    assert ei.value.kind == "unreachable"

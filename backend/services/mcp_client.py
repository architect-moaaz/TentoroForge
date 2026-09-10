"""Platform-side MCP client wrapper.

Used by:
  - `POST /api/orgs/{org_id}/mcp-servers/{id}/test` — probes a registered
    server, returns tool count so the admin UI can render Set/OK/error.
  - `GET  /api/orgs/{org_id}/mcp-servers/{id}/tools` — fetches the server's
    `tools/list` output (cached, 5-min TTL) for the Agent Builder tool
    node picker.

Generated apps do NOT go through this module — they invoke MCP tools at
runtime via the standalone-app template's `mcpClientPool.ts` (TypeScript
SDK). This module is platform-only.

Errors are mapped to a domain-specific `McpClientError(kind, detail)` so
callers can render a clear status without stringifying stack traces from
several underlying libraries.

Spec: docs/superpowers/specs/2026-08-01-visual-product-search-mcp-agent.md
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal

import httpx

from models.platform_mcp_server import PlatformMcpServer
from services.platform_integrations_crypto import CryptoError, decrypt


log = logging.getLogger(__name__)


def tool_result_is_error(result: Any) -> bool:
    """Did this `CallToolResult` report a tool error?

    `isError` ON THE WIRE, `is_error` ON THE OBJECT. mcp 2.0 renamed the field
    and kept camelCase only as a pydantic serialisation alias, so the attribute
    does not exist — and `getattr(result, "isError", False)` does not raise, it
    quietly returns the default. Every call site that read it that way declared
    every failed tool call a success and handed the caller the server's error
    text in `content`, to be parsed as if it were a result: a Figma import that
    failed server-side was consumed as design data, and the platform MCP
    test/call UI reported OK on a broken tool.

    Both spellings are read so this keeps working if a server or an older SDK
    hands back an object carrying only the alias. Same guard as
    `a2ui_authority.py:733`, which is where this was first diagnosed.
    """
    return bool(getattr(result, "is_error", None) or getattr(result, "isError", False))

# MCP SDK imports are guarded so that this module still imports cleanly
# in environments where the SDK is not yet installed (e.g. lint-only
# tooling). The functions themselves raise a clear error at call-time.
try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    try:
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        # mcp 2.0 renamed this `streamablehttp_client` -> `streamable_http_client`.
        # It is the FIRST name in this try block, so the rename took the whole
        # guarded import down with it: `_MCP_AVAILABLE` was False, and every
        # entry point here (`probe`, `list_tools`, `call_tool`) raised
        # "MCP SDK not installed" on a machine where mcp 2.0.0 is installed and
        # working. The platform MCP surface — server test, the Agent Builder
        # tool picker — was dark, and the SDK-missing message named the wrong
        # cause. Aliased rather than renamed so a 1.x install still resolves.
        from mcp.client.streamable_http import (  # type: ignore[attr-defined]
            streamable_http_client as streamablehttp_client,
        )
    try:
        from mcp.shared.exceptions import McpError as _SdkMcpError
    except ImportError:
        # Same mcp 2.0 rename story as streamablehttp_client above:
        # `McpError` -> `MCPError`. Two renamed symbols in one guarded import
        # is why the whole module reported "mcp SDK is not installed" on a
        # machine running mcp 2.0.0.
        from mcp.shared.exceptions import (  # type: ignore[attr-defined]
            MCPError as _SdkMcpError,
        )
    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover - only on stripped installs
    _MCP_AVAILABLE = False
    _SdkMcpError = Exception  # type: ignore[assignment,misc]


# --------------------------------------------------------------------------- #
# Public types
# --------------------------------------------------------------------------- #

McpErrorKind = Literal["unreachable", "auth", "protocol", "tool_error", "timeout", "config"]


class McpClientError(RuntimeError):
    """Domain-specific error, so the router can return {ok, error, kind}
    without leaking transport internals."""

    def __init__(self, kind: McpErrorKind, detail: str):
        super().__init__(f"[{kind}] {detail}")
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]


# --------------------------------------------------------------------------- #
# Tiny TTL cache for list_tools (5 min). Keyed by (url, transport,
# hash-of-auth-secret) so a token rotation invalidates the entry cleanly.
# --------------------------------------------------------------------------- #

_TOOLS_CACHE_TTL_SEC = 5 * 60
_tools_cache: dict[str, tuple[float, list[McpTool]]] = {}


def _cache_key(server: PlatformMcpServer, decoded_secret: str | None) -> str:
    secret_hash = ""
    if decoded_secret:
        secret_hash = hashlib.sha256(decoded_secret.encode("utf-8")).hexdigest()[:16]
    return f"{server.server_url}|{server.transport}|{server.auth_kind}|{secret_hash}"


def _cache_get(key: str) -> list[McpTool] | None:
    entry = _tools_cache.get(key)
    if not entry:
        return None
    expires_at, tools = entry
    if expires_at < time.monotonic():
        _tools_cache.pop(key, None)
        return None
    return tools


def _cache_set(key: str, tools: list[McpTool]) -> None:
    _tools_cache[key] = (time.monotonic() + _TOOLS_CACHE_TTL_SEC, tools)


def _cache_clear() -> None:
    """Testing hook — reset the module-level TTL cache."""
    _tools_cache.clear()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _decode_secret(server: PlatformMcpServer) -> str | None:
    """Decrypt the row's auth_secret (if any). Returns None for auth_kind=none
    or when no secret is stored."""
    if server.auth_kind == "none":
        return None
    if not server.auth_secret_ct or not server.auth_secret_iv:
        return None
    try:
        return decrypt("mcp", server.auth_secret_ct, server.auth_secret_iv)
    except CryptoError as e:
        raise McpClientError("config", f"decrypt failed: {e}") from e


def _build_headers(server: PlatformMcpServer, secret: str | None) -> dict[str, str]:
    """Assemble transport-level auth headers per auth_kind."""
    if server.auth_kind == "none":
        return {}
    if not secret:
        raise McpClientError("auth", f"auth_kind={server.auth_kind} but no secret stored")
    if server.auth_kind == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if server.auth_kind == "apikey_header":
        header = (server.auth_header_name or "").strip()
        if not header:
            raise McpClientError("config", "apikey_header auth requires auth_header_name")
        return {header: secret}
    raise McpClientError("config", f"unknown auth_kind: {server.auth_kind}")


@asynccontextmanager
async def _open_session(server: PlatformMcpServer) -> AsyncIterator["ClientSession"]:
    """Open + initialize an MCP ClientSession for `server`. Handles both http
    (streamable_http) and sse transports. Cleans up cleanly on exit."""
    if not _MCP_AVAILABLE:
        raise McpClientError("config", "mcp SDK is not installed (pip install mcp)")

    secret = _decode_secret(server)
    headers = _build_headers(server, secret)

    try:
        if server.transport == "http":
            async with streamablehttp_client(
                url=server.server_url,
                headers=headers or None,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        elif server.transport == "sse":
            async with sse_client(
                url=server.server_url,
                headers=headers or None,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        else:
            raise McpClientError("config", f"unknown transport: {server.transport}")
    except McpClientError:
        raise
    except asyncio.TimeoutError as e:
        raise McpClientError("timeout", f"connection timed out: {e}") from e
    except (httpx.ConnectError, httpx.HTTPError) as e:
        # httpx.HTTPError is the base for many transport errors including
        # ConnectError, ReadError, WriteError, and status-code errors.
        # 401/403 responses surface as httpx.HTTPStatusError.
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403):
            raise McpClientError("auth", f"server rejected credentials: {e}") from e
        raise McpClientError("unreachable", f"transport error: {e}") from e
    except _SdkMcpError as e:  # type: ignore[misc]
        raise McpClientError("protocol", f"mcp error: {e}") from e
    except Exception as e:  # noqa: BLE001 — narrowly re-raised as protocol
        raise McpClientError("protocol", f"unexpected error: {e}") from e


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

async def list_tools(server: PlatformMcpServer, *, use_cache: bool = True) -> list[McpTool]:
    """Return the server's declared tools. Cached per (url, transport,
    auth-hash) for `_TOOLS_CACHE_TTL_SEC` (5 min)."""
    secret = _decode_secret(server) if use_cache else None
    cache_key = _cache_key(server, secret) if use_cache else ""

    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    async with _open_session(server) as session:
        result = await session.list_tools()
        tools = [
            McpTool(
                name=t.name,
                description=(t.description or ""),
                input_schema=dict(t.inputSchema or {}),
            )
            for t in (result.tools or [])
        ]

    if use_cache:
        _cache_set(cache_key, tools)
    return tools


async def call_tool(
    server: PlatformMcpServer,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke `tool_name` on `server` with `arguments`. Returns a dict of
    the result shape: {content: [...], isError: bool}. Raises McpClientError."""
    async with _open_session(server) as session:
        try:
            result = await session.call_tool(tool_name, arguments or {})
        except _SdkMcpError as e:  # type: ignore[misc]
            raise McpClientError("tool_error", f"tool call failed: {e}") from e

    # `result.content` is a list of typed content blocks (TextContent,
    # ImageContent, etc.). Serialise each to a plain dict for JSON output.
    content_out: list[dict[str, Any]] = []
    for block in (result.content or []):
        if hasattr(block, "model_dump"):
            content_out.append(block.model_dump())
        else:
            content_out.append({"type": "text", "text": str(block)})
    return {
        "content": content_out,
        "isError": tool_result_is_error(result),
    }


async def probe(server: PlatformMcpServer) -> dict[str, Any]:
    """Test-connection endpoint helper. Never raises: returns
    {ok, tool_count, error?, kind?}. UI renders this directly."""
    try:
        tools = await list_tools(server, use_cache=False)
    except McpClientError as e:
        return {"ok": False, "tool_count": 0, "error": e.detail, "kind": e.kind}
    except Exception as e:  # noqa: BLE001 — probe must never crash the request
        log.exception("[mcp_client.probe] unexpected error")
        return {"ok": False, "tool_count": 0, "error": str(e), "kind": "protocol"}
    return {"ok": True, "tool_count": len(tools)}

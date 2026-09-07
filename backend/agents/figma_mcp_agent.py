"""Figma MCP client — calls the local Figma Dev Mode MCP server's
get_design_context tool directly (no LLM router) and returns the JSX.

Historical note: an earlier version of this module spawned a Claude Haiku
"tool router" and asked it to call the MCP tool and echo the result. The
router would routinely summarize the JSX (especially on large frames),
so what came back was a text paraphrase — every text descendant of the
frame concatenated into one Text node. Every downstream stage (parser,
schema writer, renderer) then received garbage input. That whole class
of failure disappears when you talk to MCP directly.

This module now uses the official ``mcp`` Python client to open a
streamable-HTTP session against the Figma Dev Mode MCP endpoint at
``http://127.0.0.1:3845/mcp`` and calls ``get_design_context`` with the
exact ``fileKey`` / ``nodeId`` derived from the Figma URL. The tool's
structured content is inspected for the JSX code field, which is
returned verbatim to the caller.

Public interface (unchanged): ``async fetch_jsx_via_mcp(figma_url) -> str | None``.
Returns None on any parse / connection / tool failure. Never raises.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

FIGMA_MCP_SERVER_NAME = "figma-dev-mode-mcp-server"
FIGMA_MCP_TOOL_NAME = "get_design_context"
# Default: Figma's hosted MCP endpoint (works over the network, no desktop
# required). Override with FIGMA_MCP_URL to point at the local Dev Mode MCP
# (``http://127.0.0.1:3845/mcp``) or a proxy.
FIGMA_MCP_URL = os.environ.get("FIGMA_MCP_URL", "https://mcp.figma.com/mcp")
# Bearer token for the hosted endpoint. Not required for localhost; strongly
# required for figma.com. Empty string means "no Authorization header".
FIGMA_MCP_TOKEN = os.environ.get("FIGMA_MCP_TOKEN", "")


def _figma_mcp_headers() -> dict[str, str] | None:
    """Auth header for the hosted MCP; None for local Dev Mode."""
    if FIGMA_MCP_TOKEN and "figma.com" in FIGMA_MCP_URL:
        return {"Authorization": f"Bearer {FIGMA_MCP_TOKEN}"}
    return None


def _figma_mcp_config() -> dict[str, Any]:
    """Kept for backwards compatibility — any caller still passing this
    dict into the Claude Agent SDK gets the same shape as before. The
    direct client below reads FIGMA_MCP_URL directly and doesn't use it."""
    return {
        "type": "http",
        "url": FIGMA_MCP_URL,
    }


def _parse_figma_url(url: str) -> tuple[str, str] | None:
    """Parse Figma design URL → (fileKey, nodeId).

    Supports: figma.com/design/<fileKey>/<name>?node-id=<nodeId>
    The node-id query uses '-' which the API needs as ':' — convert.
    """
    m = re.search(r"/(?:design|file)/([A-Za-z0-9]+)", url)
    if not m:
        return None
    file_key = m.group(1)
    nm = re.search(r"node-id=([0-9\-:]+)", url)
    if not nm:
        return None
    node_id = nm.group(1).replace("-", ":")
    return file_key, node_id


def _extract_jsx_from_tool_result(result: Any) -> str | None:
    """Pull the JSX code out of a mcp.CallToolResult payload.

    Figma's get_design_context returns a list of content items; the JSX
    lives in the first TextContent item. We look for text that opens
    with a JSX-looking token (``<`` after an optional const/import
    preamble). Prose-only items are skipped so the trailing
    ``SUPER CRITICAL: ...`` instructions block doesn't get through.
    """
    if result is None:
        return None
    # mcp CallToolResult exposes `.content` — a list of Content items.
    # Fall back to dict access when structural typing differs by version.
    items = getattr(result, "content", None)
    if items is None and isinstance(result, dict):
        items = result.get("content")
    if not items:
        return None

    def _text_of(item: Any) -> str:
        # TextContent: `.text`. Dict fallbacks: `text` / `code`.
        t = getattr(item, "text", None)
        if isinstance(t, str) and t:
            return t
        if isinstance(item, dict):
            for k in ("text", "code"):
                v = item.get(k)
                if isinstance(v, str) and v:
                    return v
        return ""

    # Score each item and pick the highest — MCP typically returns the JSX
    # AND a trailing "SUPER CRITICAL: ..." prose block that mentions <img>
    # in an inline example. A naive `<tag> found → return` would pick the
    # prose. Score:
    #   3 = has `const foo = "..."` / import / export preamble (unambiguous source)
    #   2 = has 3+ JSX-tag matches (real nested JSX tree)
    #   1 = has 1-2 JSX-tag matches (could be a prose example, still preferred over 0)
    #   0 = no source markers at all
    # Ties broken by length (real source is thousands of chars; prose is short).
    _JSX_TAG_RE = re.compile(r"<[A-Za-z][A-Za-z0-9]*")
    _CONST_RE = re.compile(r"^\s*(?:const\s+\w+\s*=|import\s|export\s)", re.MULTILINE)

    def _score(text: str) -> int:
        if _CONST_RE.search(text):
            return 3
        tags = len(_JSX_TAG_RE.findall(text))
        if tags >= 3:
            return 2
        if tags >= 1:
            return 1
        return 0

    best_text: str | None = None
    best_score = -1
    best_len = -1
    for it in items:
        text = _text_of(it)
        if not text:
            continue
        s = _score(text)
        if s > best_score or (s == best_score and len(text) > best_len):
            best_score = s
            best_len = len(text)
            best_text = text
    return best_text


async def fetch_jsx_via_mcp(figma_url: str) -> str | None:
    """Call the Figma Dev Mode MCP directly and return the JSX code.

    Returns None on parse failure, connection failure, tool error, or
    when the MCP is unreachable at ``http://127.0.0.1:3845/mcp``.
    Never raises — this is called from best-effort pipeline branches.
    """
    parsed = _parse_figma_url(figma_url)
    if not parsed:
        logger.warning("[figma_mcp] could not parse URL: %s", figma_url)
        return None
    file_key, node_id = parsed

    try:
        # Local imports — mcp is optional at runtime for callers that don't
        # touch the Figma pipeline. Any ImportError here becomes None.
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as exc:
        logger.warning("[figma_mcp] mcp client not installed: %s", exc)
        return None

    try:
        async with streamablehttp_client(FIGMA_MCP_URL, headers=_figma_mcp_headers()) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    FIGMA_MCP_TOOL_NAME,
                    arguments={"fileKey": file_key, "nodeId": node_id},
                )
        # `is_error` on the object, `isError` only as a wire alias under
        # mcp 2.0 — reading the camelCase name returned the `False` default
        # for every real failure, so this fallback (and the warning below)
        # was unreachable. See `mcp_client.tool_result_is_error`.
        from services.mcp_client import tool_result_is_error

        if tool_result_is_error(result):
            logger.warning(
                "[figma_mcp] tool returned isError for %s/%s", file_key, node_id,
            )
            return None
        jsx = _extract_jsx_from_tool_result(result)
        if not jsx:
            logger.warning(
                "[figma_mcp] no JSX in tool result for %s/%s", file_key, node_id,
            )
        return jsx
    except Exception as exc:  # noqa: BLE001 — best-effort pipeline branch
        logger.warning("[figma_mcp] call failed: %s", exc)
        return None

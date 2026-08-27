"""Tests for the direct-MCP-client Figma agent.

Historical note: this module previously spawned a Claude Haiku LLM as a
tool router that would summarize the JSX before returning it, collapsing
whole Figma frames into a single Text node. The replacement calls the
Figma MCP directly. These tests pin both the extraction contract and
the specific regression that broke pages in the earlier design.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.figma_mcp_agent import (
    FIGMA_MCP_SERVER_NAME,
    FIGMA_MCP_TOOL_NAME,
    FIGMA_MCP_URL,
    _extract_jsx_from_tool_result,
    _figma_mcp_config,
    _parse_figma_url,
    fetch_jsx_via_mcp,
)


# --------------------------------------------------------------------------- #
# URL parsing — unchanged from the old agent, preserved verbatim
# --------------------------------------------------------------------------- #

def test_parse_figma_url_design():
    assert _parse_figma_url("https://figma.com/design/abc123/Login?node-id=1-2") == ("abc123", "1:2")


def test_parse_figma_url_with_branch():
    out = _parse_figma_url("https://www.figma.com/design/AbC/My-File?node-id=10-5")
    assert out is not None
    assert out[1] == "10:5"


def test_parse_figma_url_no_node_id():
    assert _parse_figma_url("https://figma.com/design/abc/File") is None


def test_parse_figma_url_invalid():
    assert _parse_figma_url("https://example.com/design") is None


def test_parse_figma_url_file_type():
    assert _parse_figma_url(
        "https://www.figma.com/file/XYZ123/Title?node-id=5-10"
    ) == ("XYZ123", "5:10")


def test_parse_figma_url_multi_digit_node():
    assert _parse_figma_url(
        "https://figma.com/design/abc/Name?node-id=123-456"
    ) == ("abc", "123:456")


def test_parse_figma_url_already_colon():
    result = _parse_figma_url("https://figma.com/design/abc/Name?node-id=1:2")
    assert result is not None
    assert result[1] == "1:2"


# --------------------------------------------------------------------------- #
# Constants & config surface — kept stable for callers that still read them
# --------------------------------------------------------------------------- #

def test_mcp_config_shape():
    cfg = _figma_mcp_config()
    assert cfg == {"type": "http", "url": FIGMA_MCP_URL}


def test_tool_name_is_bare_get_design_context():
    """No more `mcp__<server>__` prefix — the direct client passes the
    tool name unwrapped to session.call_tool()."""
    assert FIGMA_MCP_TOOL_NAME == "get_design_context"
    assert FIGMA_MCP_SERVER_NAME == "figma-dev-mode-mcp-server"


# --------------------------------------------------------------------------- #
# Tool-result extraction — the exact behavior the LLM-router version got wrong
# --------------------------------------------------------------------------- #

def _mk_result(items):
    """Build a CallToolResult-lookalike with a `.content` list."""
    return SimpleNamespace(content=items, isError=False)


def _mk_text(text: str):
    """Build a TextContent-lookalike with `.text`."""
    return SimpleNamespace(text=text)


def test_extract_from_pristine_jsx_item():
    """The primary path — MCP returns one item with `.text = "<jsx>"`."""
    jsx = 'export default function X() { return <div className="a">Hi</div>; }'
    result = _mk_result([_mk_text(jsx)])
    assert _extract_jsx_from_tool_result(result) == jsx


def test_extract_prefers_jsx_over_prose_item():
    """MCP sometimes returns two items: the JSX + a trailing instructions
    block ('SUPER CRITICAL: The generated React+Tailwind code MUST be...').
    Extract MUST prefer the JSX item, not the prose that happens to
    contain '<img>' in its inline example."""
    prose = (
        "SUPER CRITICAL: The generated React+Tailwind code MUST be converted "
        "to match the target project's technology stack. Example: <img src={x} />."
    )
    jsx = 'const imgIcon = "https://foo.svg";\nexport default function X() { return <div>a</div>; }'
    # Prose comes FIRST — the extractor must skip it and pick jsx.
    result = _mk_result([_mk_text(prose), _mk_text(jsx)])
    assert _extract_jsx_from_tool_result(result) == jsx


def test_extract_recognizes_const_preamble_as_jsx():
    """MCP JSX often begins with asset const declarations before the
    export. The extractor must recognize those as source (not prose)."""
    src = 'const imgFoo = "https://f.svg";\nconst imgBar = "https://b.svg";\nexport default function X() {}'
    result = _mk_result([_mk_text(src)])
    assert _extract_jsx_from_tool_result(result) == src


def test_extract_dict_content_item_fallback():
    """Older MCP wire formats emitted dict items with `text` keys."""
    jsx = 'export default function X() { return <p>hi</p>; }'
    result = _mk_result([{"text": jsx, "type": "text"}])
    assert _extract_jsx_from_tool_result(result) == jsx


def test_extract_dict_content_item_code_key_fallback():
    jsx = "<Button>x</Button>"
    # No `text` key, but `code` present — extractor should find it.
    result = _mk_result([{"code": jsx}])
    assert _extract_jsx_from_tool_result(result) == jsx


def test_extract_returns_first_nonempty_when_nothing_looks_like_jsx():
    """Fail-informative: if none of the items look like source, return
    the first non-empty text so the caller can log what MCP actually said
    (avoids returning None on a legit-but-unrecognized shape)."""
    result = _mk_result([_mk_text(""), _mk_text("plain text no source markers")])
    assert _extract_jsx_from_tool_result(result) == "plain text no source markers"


def test_extract_returns_none_on_empty_result():
    assert _extract_jsx_from_tool_result(None) is None
    assert _extract_jsx_from_tool_result(_mk_result([])) is None
    assert _extract_jsx_from_tool_result(_mk_result(None)) is None


def test_extract_handles_dict_shaped_result():
    """CallToolResult may be dict-shaped depending on mcp package version."""
    jsx = "<div>ok</div>"
    result = {"content": [{"text": jsx}]}
    assert _extract_jsx_from_tool_result(result) == jsx


# --------------------------------------------------------------------------- #
# fetch_jsx_via_mcp — end-to-end (mocked MCP client)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_fetch_returns_none_on_unparseable_url():
    assert await fetch_jsx_via_mcp("https://not.figma.com/whatever") is None


@pytest.mark.asyncio
async def test_fetch_never_raises_on_mcp_connect_failure():
    """MCP server unreachable → return None, not an exception. This is
    called from best-effort branches that must not crash the pipeline."""
    # No mock — call against the real (missing) MCP server. Should be None.
    result = await fetch_jsx_via_mcp(
        "https://figma.com/design/abc/Name?node-id=1-2"
    )
    # Either None (mcp unavailable / server down / whatever) — never an exception.
    assert result is None or isinstance(result, str)

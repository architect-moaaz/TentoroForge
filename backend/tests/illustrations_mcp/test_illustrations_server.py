import pytest
from unittest.mock import patch, MagicMock
from illustrations_mcp.illustrations_server import (
    list_illustrations_tool, get_illustration_tool, build_server
)


def test_list_illustrations_tool_returns_compact_list():
    fake_meta = [
        MagicMock(slug="running-athlete", title="Running athlete", tags=["sport"]),
        MagicMock(slug="happy-news", title="Happy news", tags=["celebration"]),
    ]
    with patch("illustrations_mcp.illustrations_server._get_client") as get_client:
        get_client.return_value.list_illustrations.return_value = fake_meta
        result = list_illustrations_tool(tags=["sport"], limit=5)
    assert isinstance(result, list)
    assert all("slug" in item and "title" in item and "tags" in item for item in result)
    assert result[0]["slug"] == "running-athlete"


def test_get_illustration_tool_returns_svg_string():
    fake_svg = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    with patch("illustrations_mcp.illustrations_server._get_client") as get_client:
        get_client.return_value.get_illustration_svg.return_value = fake_svg
        result = get_illustration_tool(slug="running-athlete", color="6b7280")
    assert isinstance(result, str)
    assert result.startswith("<svg")


def test_get_illustration_tool_missing_returns_error_marker():
    with patch("illustrations_mcp.illustrations_server._get_client") as get_client:
        get_client.return_value.get_illustration_svg.return_value = None
        result = get_illustration_tool(slug="bogus", color="6b7280")
    assert isinstance(result, str)
    assert "not found" in result.lower() or "error" in result.lower()


def test_build_server_returns_a_server_instance():
    server = build_server()
    assert server is not None

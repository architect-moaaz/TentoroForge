"""Codegen snapshot: `_build_agent_instruction` handles mcp tool nodes.

Given a fixture agent JSON with one http tool + one mcp tool, verify:
  * the mcp node emits its `Tool type: MCP server call` header,
  * the mcp_server_id, mcp_tool_name, and args_mapping are printed,
  * the authoritative implementation exemplar (callMcpTool) is appended
    to the requirements block so the code_editor gets a consistent
    template to copy.

Kept lightweight — asserts on line presence, not the whole formatted
document, so the surrounding format can evolve without churning this
test.
"""
from __future__ import annotations


AGENT_DEF = {
    "name": "ProductSearchAgent",
    "description": "Search products via MCP + call an http endpoint",
    "nodes": [
        {
            "id": "sp1",
            "data": {
                "nodeType": "system_prompt",
                "label": "System",
                "config": {"prompt": "You help users find products.", "model": "claude-sonnet"},
            },
        },
        {
            "id": "tool_http",
            "data": {
                "nodeType": "tool",
                "label": "Local API",
                "config": {
                    "tool_name": "list_orders",
                    "tool_type": "http",
                    "endpoint": "/api/orders",
                    "method": "GET",
                    "parameters": {"limit": 10},
                },
            },
        },
        {
            "id": "tool_mcp",
            "data": {
                "nodeType": "tool",
                "label": "Firecrawl search",
                "config": {
                    "tool_name": "search_web",
                    "tool_type": "mcp",
                    "mcp_server_id": "11111111-2222-3333-4444-555555555555",
                    "mcp_tool_name": "search",
                    "args_mapping": {"query": "$input.query", "limit": 5},
                },
            },
        },
    ],
    "edges": [
        {"source": "sp1", "target": "tool_http"},
        {"source": "sp1", "target": "tool_mcp"},
    ],
}


def test_mcp_tool_branch_emits_all_authoritative_lines():
    from routers.agent_builder import _build_agent_instruction

    out = _build_agent_instruction(AGENT_DEF)

    # MCP-specific per-node lines.
    assert "Tool type: MCP server call" in out
    assert "MCP server id: 11111111-2222-3333-4444-555555555555" in out
    assert "MCP tool name: search" in out
    assert '"query": "$input.query"' in out or '"query":"$input.query"' in out

    # HTTP branch is unaffected.
    assert "Endpoint: GET /api/orders" in out

    # Authoritative exemplar in requirements block.
    assert "MCP tool node wiring (authoritative)" in out
    assert "callMcpTool" in out
    assert "@/lib/integrations/mcpClientPool" in out
    # Env-var naming convention documented so code_editor knows how to
    # look up credentials.
    assert "MCP_SERVER_" in out


def test_http_only_tool_still_works():
    """Regression: adding the mcp branch didn't break existing http tools."""
    from routers.agent_builder import _build_agent_instruction

    http_only = {
        "name": "N",
        "nodes": [
            {
                "id": "t1",
                "data": {
                    "nodeType": "tool",
                    "label": "H",
                    "config": {"tool_name": "hit", "tool_type": "http", "endpoint": "/a", "method": "POST"},
                },
            }
        ],
        "edges": [],
    }
    out = _build_agent_instruction(http_only)
    assert "Endpoint: POST /a" in out
    assert "MCP server call" not in out

"""Unit tests for services.agent_from_plan.build_agent_definition_from_plan.

Covers the AgentDefinition shape returned to callers — every node in the
right position, config carrying the right fields, edges wired
deterministically, and MCP-server-by-name resolution against the DB.
"""
from __future__ import annotations

import logging

import pytest

# Ensure every model is registered on Base.metadata before test_db.create_all
# (platform_mcp_servers, organizations, platform_users).
import models  # noqa: F401  (side-effect import)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def _seed_mcp_server(db, org_id, name="Firecrawl"):
    """Insert a minimum-viable PlatformMcpServer row and return it."""
    from models.platform_mcp_server import PlatformMcpServer

    row = PlatformMcpServer(
        org_id=org_id,
        name=name,
        server_url="https://mcp.example.test/v1",
        transport="http",
        auth_kind="none",
        enabled=True,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def _make_org(db):
    """Create a bare organization, return the org id."""
    import uuid as _uuid
    from models.org import Organization

    org = Organization(
        id=_uuid.uuid4(),
        name="TestOrg",
        slug=f"t-{_uuid.uuid4().hex[:8]}",
    )
    db.add(org)
    await db.flush()
    return org.id


# --------------------------------------------------------------------------- #
# 1. No agent_graph → None
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_returns_none_when_plan_has_no_agent_graph(test_db):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session
    import uuid as _uuid

    async with async_session() as db:
        result = await build_agent_definition_from_plan(
            plan={"name": "MyApp", "entities": []},
            org_id=_uuid.uuid4(),
            db=db,
        )
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_agent_graph_is_not_a_dict(test_db):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session
    import uuid as _uuid

    async with async_session() as db:
        assert await build_agent_definition_from_plan(
            plan={"agent_graph": "nope"}, org_id=_uuid.uuid4(), db=db,
        ) is None
        assert await build_agent_definition_from_plan(
            plan={"agent_graph": None}, org_id=_uuid.uuid4(), db=db,
        ) is None


# --------------------------------------------------------------------------- #
# 2. Single-function-tool → correct nodes/edges
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_single_function_tool_shape(test_db):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session

    plan = {
        "name": "SoloApp",
        "agent_graph": {
            "name": "Solo",
            "description": "one-tool agent",
            "system_prompt": {"prompt": "hi", "model": "claude-sonnet-4-5"},
            "tools": [
                {"name": "hello", "tool_type": "function",
                 "description": "say hi", "code": "// noop"},
            ],
        },
    }
    async with async_session() as db:
        org_id = await _make_org(db)
        result = await build_agent_definition_from_plan(plan, org_id, db)

    assert result is not None
    assert result["name"] == "Solo"
    assert result["description"] == "one-tool agent"
    assert isinstance(result["id"], str) and len(result["id"]) >= 32

    node_types = [n["data"]["nodeType"] for n in result["nodes"]]
    assert node_types == ["system_prompt", "tool"]

    sp = result["nodes"][0]
    assert sp["data"]["config"]["prompt"] == "hi"
    assert sp["data"]["config"]["model"] == "claude-sonnet-4-5"
    assert sp["data"]["config"]["is_entry_point"] is True

    tool = result["nodes"][1]
    assert tool["data"]["config"]["tool_name"] == "hello"
    assert tool["data"]["config"]["tool_type"] == "function"
    assert tool["data"]["config"]["code"] == "// noop"
    assert tool["data"]["config"]["description"] == "say hi"

    # Deterministic edge: sp → tool
    assert len(result["edges"]) == 1
    assert result["edges"][0]["source"] == sp["id"]
    assert result["edges"][0]["target"] == tool["id"]
    assert result["edges"][0]["data"]["edgeType"] == "default"


# --------------------------------------------------------------------------- #
# 3. Idempotency — same plan → same agent id
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_agent_id_is_deterministic_across_runs(test_db):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session

    plan = {
        "name": "SoloApp",
        "agent_graph": {
            "name": "Solo",
            "system_prompt": {"prompt": "hi"},
            "tools": [{"name": "hello", "tool_type": "function"}],
        },
    }
    async with async_session() as db:
        org_id = await _make_org(db)
        a = await build_agent_definition_from_plan(plan, org_id, db)
        b = await build_agent_definition_from_plan(plan, org_id, db)
    assert a["id"] == b["id"]


# --------------------------------------------------------------------------- #
# 4. MCP tool: server registered → node carries mcp_server_id (uuid string)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcp_tool_resolves_server_name_to_id(test_db):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session

    async with async_session() as db:
        org_id = await _make_org(db)
        row = await _seed_mcp_server(db, org_id, name="Firecrawl")

        plan = {
            "name": "P",
            "agent_graph": {
                "name": "PriceScan",
                "system_prompt": {"prompt": "..."},
                "tools": [
                    {"name": "identify", "tool_type": "function"},
                    {
                        "name": "search_prices",
                        "tool_type": "mcp",
                        "mcp_server_name": "Firecrawl",
                        "mcp_tool_name": "firecrawl_search",
                        "args_mapping": {"query": "{{identify.brand}}"},
                    },
                ],
            },
        }
        result = await build_agent_definition_from_plan(plan, org_id, db)

    assert result is not None
    tools = [n for n in result["nodes"] if n["data"]["nodeType"] == "tool"]
    assert len(tools) == 2
    mcp = next(n for n in tools if n["data"]["config"]["tool_type"] == "mcp")
    assert mcp["data"]["config"]["mcp_server_id"] == str(row.id)
    assert mcp["data"]["config"]["mcp_tool_name"] == "firecrawl_search"
    assert mcp["data"]["config"]["args_mapping"] == {"query": "{{identify.brand}}"}


# --------------------------------------------------------------------------- #
# 5. MCP tool: server NOT registered → dropped + warned
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_unresolved_mcp_tool_is_dropped_with_warning(test_db, caplog):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session

    async with async_session() as db:
        org_id = await _make_org(db)  # no MCP servers registered

        plan = {
            "name": "P",
            "agent_graph": {
                "name": "A",
                "system_prompt": {"prompt": "..."},
                "tools": [
                    {"name": "keep_me", "tool_type": "function"},
                    {
                        "name": "drop_me",
                        "tool_type": "mcp",
                        "mcp_server_name": "NeverRegistered",
                        "mcp_tool_name": "search",
                    },
                ],
            },
        }
        with caplog.at_level(logging.WARNING, logger="services.agent_from_plan"):
            result = await build_agent_definition_from_plan(plan, org_id, db)

    assert result is not None
    tool_names = [
        n["data"]["config"]["tool_name"]
        for n in result["nodes"] if n["data"]["nodeType"] == "tool"
    ]
    assert tool_names == ["keep_me"]  # drop_me was excluded
    assert any("NeverRegistered" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_all_mcp_tools_unresolved_skips_whole_agent(test_db, caplog):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session

    async with async_session() as db:
        org_id = await _make_org(db)  # no MCP servers registered

        plan = {
            "name": "P",
            "agent_graph": {
                "name": "OnlyMcp",
                "system_prompt": {"prompt": "..."},
                "tools": [
                    {"name": "a", "tool_type": "mcp", "mcp_server_name": "X"},
                    {"name": "b", "tool_type": "mcp", "mcp_server_name": "Y"},
                ],
            },
        }
        with caplog.at_level(logging.WARNING, logger="services.agent_from_plan"):
            result = await build_agent_definition_from_plan(plan, org_id, db)

    assert result is None
    assert any(
        "every tool" in rec.message.lower() or "unresolved" in rec.message.lower()
        for rec in caplog.records
    )


# --------------------------------------------------------------------------- #
# 6. Multi-tool: serial edges + fan-out to guardrail
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_multi_tool_with_guardrail_wires_correct_edges(test_db):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session

    plan = {
        "name": "M",
        "agent_graph": {
            "name": "Multi",
            "system_prompt": {"prompt": "..."},
            "tools": [
                {"name": "t1", "tool_type": "function"},
                {"name": "t2", "tool_type": "function"},
                {"name": "t3", "tool_type": "function"},
            ],
            "guardrails": [
                {
                    "name": "gate",
                    "guardrail_type": "output_filter",
                    "rules": [
                        {"name": "min_conf", "type": "custom", "expr": "x >= 0.5"},
                    ],
                },
            ],
        },
    }
    async with async_session() as db:
        org_id = await _make_org(db)
        result = await build_agent_definition_from_plan(plan, org_id, db)

    node_ids_by_type: dict[str, list[str]] = {}
    for n in result["nodes"]:
        node_ids_by_type.setdefault(n["data"]["nodeType"], []).append(n["id"])

    assert len(node_ids_by_type["tool"]) == 3
    assert len(node_ids_by_type["guardrail"]) == 1

    # Serial: sp → t1 → t2 → t3, then t3 → guard
    edges = [(e["source"], e["target"]) for e in result["edges"]]
    sp_id = node_ids_by_type["system_prompt"][0]
    tool_ids = node_ids_by_type["tool"]
    guard_id = node_ids_by_type["guardrail"][0]

    assert (sp_id, tool_ids[0]) in edges
    assert (tool_ids[0], tool_ids[1]) in edges
    assert (tool_ids[1], tool_ids[2]) in edges
    assert (tool_ids[2], guard_id) in edges

    # Guardrail rule normalisation preserved the expr under `expression`.
    guard_node = next(n for n in result["nodes"] if n["id"] == guard_id)
    assert guard_node["data"]["config"]["guardrail_type"] == "output_filter"
    assert guard_node["data"]["config"]["rules"][0]["expression"] == "x >= 0.5"


# --------------------------------------------------------------------------- #
# 7. Memory + human_handoff terminal wiring
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_memory_and_human_handoff_terminal(test_db):
    from services.agent_from_plan import build_agent_definition_from_plan
    from database import async_session

    plan = {
        "name": "H",
        "agent_graph": {
            "name": "Handoff",
            "system_prompt": {"prompt": "..."},
            "tools": [{"name": "t1", "tool_type": "function"}],
            "memory": {"memory_type": "conversation", "capacity": 20},
            "human_handoff": {
                "conditions": {"explicit_request": True,
                               "keyword_triggers": ["human"]},
                "target": {"type": "queue", "value": "support"},
            },
        },
    }
    async with async_session() as db:
        org_id = await _make_org(db)
        result = await build_agent_definition_from_plan(plan, org_id, db)

    edges = [(e["source"], e["target"]) for e in result["edges"]]
    types = {n["id"]: n["data"]["nodeType"] for n in result["nodes"]}
    memory_id = next(nid for nid, t in types.items() if t == "memory")
    handoff_id = next(nid for nid, t in types.items() if t == "human_handoff")

    # tool → memory  AND  memory → handoff (memory is one of the tails)
    assert any(src == memory_id and tgt == handoff_id for src, tgt in edges)


# --------------------------------------------------------------------------- #
# 8. Snapshot: plan-derived AgentDefinition → same _build_agent_instruction
#    text the Builder would produce for a hand-built agent.
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_plan_derived_agent_definition_produces_same_instruction(test_db):
    from services.agent_from_plan import build_agent_definition_from_plan
    from routers.agent_builder import _build_agent_instruction
    from database import async_session

    async with async_session() as db:
        org_id = await _make_org(db)
        row = await _seed_mcp_server(db, org_id, name="Firecrawl")

        plan = {
            "name": "PriceScan",
            "agent_graph": {
                "name": "PriceScanAgent",
                "description": "Identifies products and gets prices.",
                "system_prompt": {"prompt": "You identify products.",
                                  "model": "claude-sonnet-4-5",
                                  "temperature": 0.2},
                "tools": [
                    {"name": "identify_product", "tool_type": "function",
                     "description": "Vision-identify."},
                    {"name": "search_prices", "tool_type": "mcp",
                     "mcp_server_name": "Firecrawl",
                     "mcp_tool_name": "firecrawl_search",
                     "args_mapping": {"query": "{{identify_product.brand}}"}},
                ],
            },
        }
        agent_data = await build_agent_definition_from_plan(plan, org_id, db)

    out = _build_agent_instruction(agent_data)

    # The MCP branch of _build_agent_instruction fires — meaning the
    # plan-derived shape is identical (from _build_agent_instruction's
    # perspective) to a hand-built Agent Builder definition.
    assert "PriceScanAgent" in out
    assert "Tool type: MCP server call" in out
    assert f"MCP server id: {row.id}" in out
    assert "MCP tool name: firecrawl_search" in out
    assert "callMcpTool" in out          # the authoritative exemplar block
    assert "@/lib/integrations/mcpClientPool" in out

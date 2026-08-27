"""Auto-create an agent from ``plan['agent_graph']`` during generation.

When the planner produces a plan whose archetype has ``has_agent: true``
(e.g. ``visual-product-search``), it emits an ``agent_graph`` block that
declares the runtime app-agent's shape (system_prompt, tools, guardrails,
memory, router, human_handoff).

This service reads that block and produces an :class:`AgentDefinition`
JSON in the exact shape the Agent Builder frontend saves — the same
shape ``routers.agent_builder`` accepts via ``POST
/api/projects/.../agent-definitions``. The materialised JSON is written
to ``<output>/agent-definitions/<id>.json`` and immediately handed to
``run_code_editor`` so the generated app ends up with a working
``src/agents/agent-service.ts`` + ``POST /api/agent/chat`` before the
pipeline finishes.

The pipeline hook (``routers.generate``) calls
:func:`install_agent_from_plan` after seed/validator/indexer, wrapped in
a broad try/except: a failure here must NEVER fail the whole app
generation. The user can always re-run from the Agent Builder UI.

Spec: docs/superpowers/specs/2026-08-01-visual-product-search-mcp-agent.md §5.5
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


AGENT_DEFS_DIR = "agent-definitions"  # matches routers.agent_builder


# ---------------------------------------------------------------------------
# Deterministic layout constants — kept trivial on purpose. The Agent
# Builder canvas lets a human rearrange nodes; the auto-built agent just
# needs coordinates that don't collapse on top of each other.
# ---------------------------------------------------------------------------

_LAYOUT = {
    "system_prompt": (0, 0),
    "tool_col_x": 250,       # tools cascade vertically at this x
    "tool_row_step": 150,
    "guardrail_col_x": 550,  # guardrails to the right of tools
    "guardrail_row_step": 150,
    "memory": (0, 500),      # bottom-left
    "router": (550, 500),    # bottom-right (shares column with human_handoff)
    "human_handoff": (800, 500),
}


# ---------------------------------------------------------------------------
# build_agent_definition_from_plan
# ---------------------------------------------------------------------------

async def build_agent_definition_from_plan(
    plan: dict,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[dict]:
    """Read ``plan['agent_graph']`` and return an AgentDefinition dict.

    Shape of the returned dict matches what the Agent Builder frontend
    saves — see :mod:`schemas.agent_builder.AgentDefinitionSave`::

        {id, name, description, nodes: [Node], edges: [Edge]}

    - Returns ``None`` when the plan has no ``agent_graph`` block.
    - MCP tools are resolved by ``mcp_server_name`` against
      :class:`PlatformMcpServer` (scoped to ``org_id``); unresolved MCP
      tools are dropped with a warning. If every MCP tool is unresolved
      AND there are no non-MCP tools, the whole build is aborted (return
      ``None``) because the agent would have no way to act — clearer to
      let the user register the server and re-run than to ship an
      agent-service that can only think, never act.
    """
    if not isinstance(plan, dict):
        return None
    graph = plan.get("agent_graph")
    if not isinstance(graph, dict):
        return None

    name = str(graph.get("name") or "App Agent").strip() or "App Agent"
    description = graph.get("description")
    if description is not None:
        description = str(description)

    # ── MCP server lookup (one query, then in-memory match) ────────────
    from models.platform_mcp_server import PlatformMcpServer

    row_by_name: dict[str, PlatformMcpServer] = {}
    result = await db.execute(
        select(PlatformMcpServer).where(PlatformMcpServer.org_id == org_id)
    )
    for row in result.scalars().all():
        row_by_name[row.name] = row

    # ── Build nodes ────────────────────────────────────────────────────
    nodes: list[dict] = []
    edges: list[dict] = []

    # 1. system_prompt (always present — synthesise a minimal one if the
    #    planner omitted it, so the graph is at least well-formed)
    sp_cfg_in = graph.get("system_prompt") or {}
    sp_id = "sp_1"
    sp_config = {
        "prompt": sp_cfg_in.get("prompt") or "",
        "is_entry_point": True,
    }
    if sp_cfg_in.get("model"):
        sp_config["model"] = sp_cfg_in["model"]
    if sp_cfg_in.get("temperature") is not None:
        sp_config["temperature"] = sp_cfg_in["temperature"]
    if sp_cfg_in.get("max_tokens") is not None:
        sp_config["max_tokens"] = sp_cfg_in["max_tokens"]

    nodes.append({
        "id": sp_id,
        "type": "system_prompt",
        "position": {"x": _LAYOUT["system_prompt"][0], "y": _LAYOUT["system_prompt"][1]},
        "data": {
            "label": sp_cfg_in.get("label") or "System Prompt",
            "nodeType": "system_prompt",
            "config": sp_config,
        },
    })

    # 2. tools — sequence in a vertical column
    tool_ids: list[str] = []
    dropped_mcp_names: list[str] = []
    for idx, tool_in in enumerate(graph.get("tools") or []):
        if not isinstance(tool_in, dict):
            continue
        tool_type = str(tool_in.get("tool_type") or "function")
        tool_name = str(tool_in.get("name") or f"tool_{idx + 1}")

        config: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_type": tool_type,
        }
        if tool_in.get("description"):
            config["description"] = str(tool_in["description"])

        if tool_type == "mcp":
            server_name = tool_in.get("mcp_server_name")
            if not server_name or server_name not in row_by_name:
                logger.warning(
                    "[agent_from_plan] mcp tool %r references unknown server %r "
                    "for org=%s — skipping tool node (register the server under "
                    "/settings/mcp-servers and re-run to include it).",
                    tool_name, server_name, org_id,
                )
                dropped_mcp_names.append(str(server_name or "<unnamed>"))
                continue
            server_row = row_by_name[server_name]
            config["mcp_server_id"] = str(server_row.id)
            config["mcp_tool_name"] = str(tool_in.get("mcp_tool_name") or tool_name)
            if isinstance(tool_in.get("args_mapping"), dict):
                config["args_mapping"] = tool_in["args_mapping"]
        else:
            # Free-form tool config — pass through the fields the frontend
            # ToolConfig understands so the builder can round-trip it.
            for k in ("code", "endpoint", "method", "query", "parameters",
                      "response_schema", "workflow_id", "entity", "operation"):
                if k in tool_in and tool_in[k] is not None:
                    config[k] = tool_in[k]

        node_id = f"tool_{idx + 1}"
        nodes.append({
            "id": node_id,
            "type": "tool",
            "position": {
                "x": _LAYOUT["tool_col_x"],
                "y": idx * _LAYOUT["tool_row_step"],
            },
            "data": {
                "label": tool_name,
                "nodeType": "tool",
                "config": config,
            },
        })
        tool_ids.append(node_id)

    # If every tool the plan asked for was an unresolved MCP tool, the
    # agent has no way to act — skip the whole build so we don't ship a
    # thinking-only shell. The pipeline logs this at WARN level.
    plan_tool_count = len([t for t in (graph.get("tools") or []) if isinstance(t, dict)])
    if plan_tool_count > 0 and not tool_ids:
        logger.warning(
            "[agent_from_plan] every tool in plan.agent_graph is an unresolved "
            "MCP server (%s) — skipping agent install for org=%s. Register the "
            "MCP server(s) under /settings/mcp-servers and re-generate.",
            ", ".join(dropped_mcp_names), org_id,
        )
        return None

    # 3. guardrails
    guardrail_ids: list[str] = []
    for idx, g_in in enumerate(graph.get("guardrails") or []):
        if not isinstance(g_in, dict):
            continue
        node_id = f"guard_{idx + 1}"
        config: dict[str, Any] = {}
        if g_in.get("guardrail_type"):
            config["guardrail_type"] = g_in["guardrail_type"]
        if isinstance(g_in.get("rules"), list):
            # Normalise rules to the frontend shape (adds an id if missing).
            rules_out = []
            for j, r in enumerate(g_in["rules"]):
                if not isinstance(r, dict):
                    continue
                rules_out.append({
                    "id": str(r.get("id") or f"r{idx + 1}_{j + 1}"),
                    "name": str(r.get("name") or f"rule_{j + 1}"),
                    "type": str(r.get("type") or "custom"),
                    **({"expression": r["expr"]} if r.get("expr") else {}),
                    **({"expression": r["expression"]} if r.get("expression") else {}),
                })
            config["rules"] = rules_out
        if g_in.get("custom_expression"):
            config["custom_expression"] = g_in["custom_expression"]

        nodes.append({
            "id": node_id,
            "type": "guardrail",
            "position": {
                "x": _LAYOUT["guardrail_col_x"],
                "y": idx * _LAYOUT["guardrail_row_step"],
            },
            "data": {
                "label": g_in.get("name") or f"Guardrail {idx + 1}",
                "nodeType": "guardrail",
                "config": config,
            },
        })
        guardrail_ids.append(node_id)

    # 4. memory (single node — planner shape allows one)
    memory_id: Optional[str] = None
    mem_in = graph.get("memory")
    if isinstance(mem_in, dict) and mem_in:
        memory_id = "memory_1"
        config: dict[str, Any] = {}
        for k in ("memory_type", "capacity", "ttl_seconds",
                  "embedding_model", "similarity_threshold"):
            if k in mem_in and mem_in[k] is not None:
                config[k] = mem_in[k]
        nodes.append({
            "id": memory_id,
            "type": "memory",
            "position": {"x": _LAYOUT["memory"][0], "y": _LAYOUT["memory"][1]},
            "data": {
                "label": mem_in.get("label") or "Memory",
                "nodeType": "memory",
                "config": config,
            },
        })

    # 5. router (single node)
    router_id: Optional[str] = None
    router_in = graph.get("router")
    if isinstance(router_in, dict) and router_in:
        router_id = "router_1"
        config: dict[str, Any] = {}
        if router_in.get("strategy"):
            config["strategy"] = router_in["strategy"]
        if isinstance(router_in.get("routes"), list):
            config["routes"] = router_in["routes"]
        if router_in.get("default_route"):
            config["default_route"] = router_in["default_route"]
        nodes.append({
            "id": router_id,
            "type": "router",
            "position": {"x": _LAYOUT["router"][0], "y": _LAYOUT["router"][1]},
            "data": {
                "label": router_in.get("label") or "Router",
                "nodeType": "router",
                "config": config,
            },
        })

    # 6. human_handoff (single node)
    handoff_id: Optional[str] = None
    ho_in = graph.get("human_handoff")
    if isinstance(ho_in, dict) and ho_in:
        handoff_id = "handoff_1"
        config: dict[str, Any] = {}
        if isinstance(ho_in.get("conditions"), dict):
            config["conditions"] = ho_in["conditions"]
        if isinstance(ho_in.get("target"), dict):
            config["target"] = ho_in["target"]
        if isinstance(ho_in.get("context_fields"), list):
            config["context_fields"] = ho_in["context_fields"]
        nodes.append({
            "id": handoff_id,
            "type": "human_handoff",
            "position": {"x": _LAYOUT["human_handoff"][0], "y": _LAYOUT["human_handoff"][1]},
            "data": {
                "label": ho_in.get("label") or "Human Handoff",
                "nodeType": "human_handoff",
                "config": config,
            },
        })

    # ── Wire edges deterministically ──────────────────────────────────
    # system_prompt → tool_1 → tool_2 → ... → tool_N
    #   → (fan out to each guardrail)
    #   → memory (if any)
    #   → router (if any)
    #   → human_handoff (terminal)
    edge_counter = 0

    def _add_edge(src: str, tgt: str) -> None:
        nonlocal edge_counter
        edge_counter += 1
        edges.append({
            "id": f"e{edge_counter}",
            "source": src,
            "target": tgt,
            "data": {"edgeType": "default"},
        })

    prev = sp_id
    for tid in tool_ids:
        _add_edge(prev, tid)
        prev = tid

    # After the last tool, fan out to guardrails and memory in parallel
    # (both are "aggregators" that run on the final output).
    tail_terminals: list[str] = []
    for gid in guardrail_ids:
        _add_edge(prev, gid)
        tail_terminals.append(gid)
    if memory_id:
        _add_edge(prev, memory_id)
        tail_terminals.append(memory_id)
    if router_id:
        _add_edge(prev, router_id)
        tail_terminals.append(router_id)

    # human_handoff is terminal: any tail terminal chains into it. If no
    # tail nodes exist (no guardrails/memory/router), wire prev → handoff.
    if handoff_id:
        if tail_terminals:
            for t in tail_terminals:
                _add_edge(t, handoff_id)
        else:
            _add_edge(prev, handoff_id)

    # ── Compose AgentDefinition envelope ──────────────────────────────
    agent_id = str(graph.get("id") or _stable_agent_id(plan, name))
    return {
        "id": agent_id,
        "name": name,
        "description": description,
        "nodes": nodes,
        "edges": edges,
    }


def _stable_agent_id(plan: dict, name: str) -> str:
    """Deterministic id derived from plan+name so re-runs are idempotent.

    We use a UUIDv5 in the URL namespace so the same plan + agent name
    always produces the same agent id — critical for the idempotency
    guarantee: re-generating the same app updates the existing JSON file
    instead of leaving orphan copies keyed by fresh uuid4s.
    """
    seed = f"{plan.get('name') or ''}|{name}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


# ---------------------------------------------------------------------------
# install_agent_from_plan — full end-to-end path
# ---------------------------------------------------------------------------

async def install_agent_from_plan(
    output_dir: str,
    plan: dict,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[dict]:
    """Materialise the plan's agent_graph as source in the generated app.

    Steps:
      1. Build an AgentDefinition from ``plan['agent_graph']``.
      2. If the plan has no agent_graph (or every MCP tool was
         unresolved), return ``None`` — nothing to do.
      3. Write ``<output>/agent-definitions/<agent_id>.json``.
      4. Run ``routers.agent_builder._build_agent_instruction`` on the
         same JSON to produce the natural-language instruction for the
         code_editor (identical to what the Builder's Apply button
         sends).
      5. Drain ``run_code_editor(...)`` so it writes
         ``src/agents/agent-service.ts`` + ``POST /api/agent/chat``.
         (We do NOT run the validator/indexer here — the outer pipeline
         already runs them after this hook.)

    Returns a small summary dict for logging::

        {"agent_id", "name", "node_count", "tool_count"}

    or ``None`` when nothing was installed.
    """
    agent_data = await build_agent_definition_from_plan(plan, org_id, db)
    if not agent_data:
        return None

    defs_dir = Path(output_dir) / AGENT_DEFS_DIR
    defs_dir.mkdir(parents=True, exist_ok=True)
    agent_file = defs_dir / f"{agent_data['id']}.json"
    agent_file.write_text(json.dumps(agent_data, indent=2), encoding="utf-8")

    # Build the same instruction the Builder's "Apply" button sends.
    from routers.agent_builder import _build_agent_instruction

    instruction = _build_agent_instruction(agent_data)

    # Drain the code_editor stream. We intentionally don't propagate
    # streaming events out of this service — the caller (pipeline) wraps
    # us in a small status/log envelope and doesn't need per-tool-call
    # traces.
    from agents.code_editor import run_code_editor

    async for _msg in run_code_editor(
        output_dir=output_dir,
        instruction=instruction,
    ):
        # Drain — we don't forward these events. The outer pipeline
        # already emits a "status" event before/after this call.
        pass

    tool_count = sum(
        1 for n in agent_data.get("nodes", [])
        if (n.get("data") or {}).get("nodeType") == "tool"
    )
    return {
        "agent_id": agent_data["id"],
        "name": agent_data["name"],
        "node_count": len(agent_data.get("nodes", [])),
        "tool_count": tool_count,
    }

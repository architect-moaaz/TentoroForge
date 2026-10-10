"""Agent Builder endpoints — CRUD for agent definitions, apply pipeline, and test."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import (
    AgentJob,
    AgentJobStatus,
    AgentType,
    Version,
)
from schemas.agent_builder import (
    AgentDefinitionSave, AgentListItem, AgentScenarioRun, AgentScenarioSave, AgentTestRequest,
)
from services.project_service import get_project_with_auth
from services.git_service import git_commit
from sse_helpers import sse_event, stream_agent_messages

router = APIRouter(tags=["agent-builder"])

AGENT_DEFS_DIR = "agent-definitions"  # relative to project output_dir


def _agent_defs_path(output_dir: str, *, create: bool = False) -> Path:
    """The project's agent-definitions directory.

    Only a WRITE creates it, and with its parents: a project row can outlive its
    folder (a draft whose output directory was removed, a restore from a database
    alone), and creating one level of a missing path raised FileNotFoundError out
    of Save. Reads must not create anything — listing the agents of a project that
    has none is not a reason to put a directory on disk.
    """
    p = Path(output_dir) / AGENT_DEFS_DIR
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Agent definitions (stored as JSON files in the project)
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/agent-definitions", response_model=list[AgentListItem])
async def list_agent_definitions(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all agent definitions for a project."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return []

    defs_dir = _agent_defs_path(project.output_dir)
    items = []
    for f in sorted(defs_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            items.append(AgentListItem(
                id=data.get("id", f.stem),
                name=data.get("name", f.stem),
                description=data.get("description"),
                node_count=len(data.get("nodes", [])),
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return items


@router.get("/api/projects/{project_id}/agent-definitions/handoff-options")
async def get_handoff_options(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The roles and people the human-handoff box can name, from this app. Declared BEFORE the `{agent_id}` route,
    which would otherwise read "handoff-options" as an agent's id."""
    import asyncio

    from services.agent_handoff_options import handoff_options

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return {"roles": [], "people": [], "peopleNote": "No output directory."}
    return await asyncio.to_thread(handoff_options, project.output_dir)


@router.get("/api/projects/{project_id}/agent-definitions/{agent_id}")
async def get_agent_definition(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single agent definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if not agent_file.exists():
        raise HTTPException(status_code=404, detail="Agent definition not found")

    return json.loads(agent_file.read_text())


@router.post("/api/projects/{project_id}/agent-definitions/suggest")
async def suggest_agent_definition(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """An agent drawn from this app's own Blueprint (its tables, workflows, rules and who may do
    what). Nothing is saved: the builder loads it onto the canvas to edit, save and Apply."""
    from services.agent_suggest import suggest_agent

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    path = Path(project.output_dir) / ".forge" / "blueprint" / "current.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(
            status_code=409,
            detail="This project has no Blueprint yet — build the app first, then suggest an agent for it.",
        )
    return suggest_agent(doc)


@router.post("/api/projects/{project_id}/agent-definitions/check")
async def check_agent_definition(
    project_id: uuid.UUID,
    req: AgentDefinitionSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What is wrong with this agent, before Apply: the compiler's notes and the app's own rules, each pinned
    to the box it is about. Nothing is saved or installed."""
    from services.agent_check import check_agent
    from services.agent_runtime_install import resolve_roots

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    _, app_root = resolve_roots(project.output_dir)
    return check_agent(req.model_dump(), app_root)


@router.post("/api/projects/{project_id}/agent-definitions/suggest-scenarios")
async def suggest_agent_scenarios(
    project_id: uuid.UUID,
    req: AgentDefinitionSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A starting set of test conversations drawn from what this agent can do. Nothing is saved."""
    from services.agent_scenarios import suggest_scenarios

    await get_project_with_auth(project_id, user, db)
    return {"scenarios": suggest_scenarios(req.model_dump())}


@router.get("/api/projects/{project_id}/agent-definitions/{agent_id}/tests")
async def get_agent_scenarios(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The agent's saved test conversations."""
    from services.agent_scenarios import load_scenarios

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return {"scenarios": []}
    return {"scenarios": load_scenarios(project.output_dir, agent_id)}


@router.put("/api/projects/{project_id}/agent-definitions/{agent_id}/tests")
async def save_agent_scenarios(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentScenarioSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the agent's test conversations (cleaned: only fields that mean something are kept)."""
    from services.agent_scenarios import save_scenarios

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    return {"scenarios": save_scenarios(project.output_dir, agent_id, req.scenarios)}


@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/tests/run")
async def run_agent_scenarios(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentScenarioRun,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run test conversations against the agent as drawn: a real model call each, tools reported and
    never executed. Pass/fail per scenario, with the reason in plain words."""
    from services.agent_scenarios import load_scenarios, run_scenarios

    project = await get_project_with_auth(project_id, user, db)
    scenarios = req.scenarios if req.scenarios is not None else (
        load_scenarios(project.output_dir, agent_id) if project.output_dir else [])
    results = await run_scenarios(req.graph.model_dump(), scenarios)
    return {"results": results,
            "passed": sum(1 for r in results if r["status"] == "passed"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "errors": sum(1 for r in results if r["status"] == "error")}


@router.post("/api/projects/{project_id}/agent-definitions", status_code=201)
async def save_agent_definition(
    project_id: uuid.UUID,
    req: AgentDefinitionSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update an agent definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir, create=True) / f"{req.id}.json"
    agent_file.write_text(json.dumps(req.model_dump(), indent=2))
    return {"id": req.id, "saved": True}


@router.put("/api/projects/{project_id}/agent-definitions/{agent_id}")
async def update_agent_definition(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentDefinitionSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing agent definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if not agent_file.exists():
        raise HTTPException(status_code=404, detail="Agent definition not found")

    data = req.model_dump()
    data["id"] = agent_id
    agent_file.write_text(json.dumps(data, indent=2))
    return {"id": agent_id, "saved": True}


@router.delete("/api/projects/{project_id}/agent-definitions/{agent_id}", status_code=204)
async def delete_agent_definition(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an agent definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if agent_file.exists():
        agent_file.unlink()


# ---------------------------------------------------------------------------
# Apply agent definition to generated app code
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/apply")
async def apply_agent_definition(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Install an agent into the generated app: compile its definition, lay down the runtime, validate, index (SSE streaming)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if not agent_file.exists():
        raise HTTPException(status_code=404, detail="Agent definition not found")

    agent_data = json.loads(agent_file.read_text())
    # What is recorded against the version: the definition, in the builder's words.
    instruction = _build_agent_instruction(agent_data)

    async def event_stream():
        yield sse_event("status", {"message": f"Applying agent: {agent_data.get('name', agent_id)}..."})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            # The runtime is fixed code and the definition is data, so installing an
            # agent is a compile + copy — no model writes it, and applying twice gives
            # the same files.
            import asyncio

            from services.agent_runtime_install import install_agent_runtime

            yield sse_event("status", {"message": "Installing agent runtime..."})
            install = await asyncio.to_thread(install_agent_runtime, project.output_dir)
            if not install.get("installed"):
                # Saved is saved: the definition is on disk and is installed by the
                # build. Say that, rather than a bare failure — there is nothing
                # wrong with the agent, there is just no app to put it in yet.
                if install.get("no_app"):
                    yield sse_event("error", {"message": (
                        "This project has no generated app yet. Your agent is saved and will be "
                        "installed when the app is built.")})
                else:
                    yield sse_event("error", {"message": "Nothing to install — the project has no agent definition."})
                return
            for w in install.get("warnings", []):
                yield sse_event("log", {"text": f"[Agent] ⚠ {w}"})
            yield sse_event("log", {"text": (
                f"[Agent] installed {len(install['agents'])} agent(s), "
                f"{len(install['written'])} file(s) written"
                + ("" if install.get("widget_mounted") else "; the floating widget was not mounted (see /assistant)")
            )})

            from agents.validator import run_validator
            yield sse_event("status", {"message": "Validating build..."})

            async for evt in stream_agent_messages(
                run_validator(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Validator] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            from agents.indexer import run_indexer
            yield sse_event("status", {"message": "Indexing application..."})

            async for evt in stream_agent_messages(
                run_indexer(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Indexer] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            commit_hash = await git_commit(
                project.output_dir,
                f"agent: apply '{agent_data.get('name', agent_id)}'",
                actor="editor",   # S24-9: an unattributed HEAD can no longer be reverted
            )

            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=instruction[:500],
                    result={
                        "intent": "AGENT_APPLY",
                        "agent_id": agent_id,
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message=f"agent: apply '{agent_data.get('name', agent_id)}'",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "agent_id": agent_id,
                "num_turns": total_turns,
                "cost_usd": total_cost,
                "duration_ms": total_duration,
                "commit_hash": commit_hash,
                "warnings": install.get("warnings", []),
                "widget_mounted": install.get("widget_mounted", False),
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


# ---------------------------------------------------------------------------
# Test agent
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/test")
async def test_agent(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentTestRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test an agent with a message: a real model call against its compiled definition.

    Tools are shown, not executed (see services/agent_test_run.py)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if not agent_file.exists():
        raise HTTPException(status_code=404, detail="Agent definition not found")

    from services.agent_test_run import run_agent_test

    agent_data = json.loads(agent_file.read_text())
    return await run_agent_test(agent_data, req.message, req.conversation_history)


# ---------------------------------------------------------------------------
# Instruction builder (server-side fallback, mirrors frontend builder)
# ---------------------------------------------------------------------------

def _build_agent_instruction(agent_data: dict) -> str:
    """Convert an agent definition JSON to a natural language instruction."""
    name = agent_data.get("name", "Untitled Agent")
    desc = agent_data.get("description", "")
    nodes = agent_data.get("nodes", [])
    edges = agent_data.get("edges", [])

    parts = [
        f'Implement AI agent "{name}" in the generated application.',
        "",
    ]

    if desc:
        parts.append(f"Description: {desc}")
        parts.append("")

    # Nodes
    if nodes:
        parts.append("## Agent Nodes")
        for node in nodes:
            node_data = node.get("data", {})
            node_type = node_data.get("nodeType", "unknown")
            label = node_data.get("label", node.get("id", ""))
            config = node_data.get("config", {})
            parts.append(f"\n### [{node_type}] {label} (id: {node.get('id', '')})")

            if node_type == "system_prompt":
                if config.get("prompt"):
                    parts.append(f"  Prompt: {config['prompt'][:200]}")
                if config.get("model"):
                    parts.append(f"  Model: {config['model']}")
                if config.get("temperature") is not None:
                    parts.append(f"  Temperature: {config['temperature']}")
            elif node_type == "tool":
                if config.get("tool_name"):
                    parts.append(f"  Tool name: {config['tool_name']}")
                if config.get("tool_type"):
                    parts.append(f"  Type: {config['tool_type']}")
                if config.get("tool_type") == "mcp":
                    # MCP tool node — invocation goes through the
                    # standalone-app template's mcpClientPool at runtime.
                    parts.append("  Tool type: MCP server call")
                    parts.append(f"  MCP server id: {config.get('mcp_server_id', '')}")
                    parts.append(f"  MCP tool name: {config.get('mcp_tool_name', '')}")
                    if config.get("args_mapping"):
                        parts.append(f"  Args mapping: {json.dumps(config['args_mapping'])}")
                else:
                    if config.get("endpoint"):
                        parts.append(f"  Endpoint: {config.get('method', 'GET')} {config['endpoint']}")
                    if config.get("parameters"):
                        parts.append(f"  Parameters: {json.dumps(config['parameters'])}")
            elif node_type == "guardrail":
                if config.get("guardrail_type"):
                    parts.append(f"  Filter type: {config['guardrail_type']}")
                if config.get("rules"):
                    for rule in config["rules"]:
                        parts.append(f"  Rule: {rule.get('name', '')} ({rule.get('type', '')})")
            elif node_type == "memory":
                if config.get("memory_type"):
                    parts.append(f"  Memory type: {config['memory_type']}")
                if config.get("capacity"):
                    parts.append(f"  Capacity: {config['capacity']}")
            elif node_type == "human_handoff":
                conditions = config.get("conditions", {})
                if conditions.get("keyword_triggers"):
                    parts.append(f"  Keywords: {', '.join(conditions['keyword_triggers'])}")
                target = config.get("target", {})
                if target.get("type"):
                    parts.append(f"  Handoff to: {target['type']} ({target.get('value', '')})")
            elif node_type == "router":
                if config.get("strategy"):
                    parts.append(f"  Strategy: {config['strategy']}")
                if config.get("routes"):
                    for route in config["routes"]:
                        parts.append(f"  Route: {route.get('label', '')} → {route.get('condition', 'default')}")
        parts.append("")

    # Edges
    if edges:
        parts.append("## Connections")
        for edge in edges:
            edge_type = edge.get("data", {}).get("edgeType", "default")
            src = edge.get("source", "?")
            tgt = edge.get("target", "?")
            src_node = next((n for n in nodes if n.get("id") == src), None)
            tgt_node = next((n for n in nodes if n.get("id") == tgt), None)
            src_name = src_node.get("data", {}).get("label", src) if src_node else src
            tgt_name = tgt_node.get("data", {}).get("label", tgt) if tgt_node else tgt
            parts.append(f"- {src_name} → {tgt_name} ({edge_type})")
        parts.append("")

    # Requirements
    parts.extend([
        "## Implementation Requirements",
        "1. Create an agent service class (src/agents/agent-service.ts) that orchestrates the node graph",
        "2. For SystemPrompt nodes: use the prompt as the system message when calling the LLM",
        "3. For Tool nodes: implement the tool function (API call, DB query, or custom function)",
        "4. For Guardrail nodes: implement input/output filtering middleware",
        "5. For Memory nodes: implement conversation/vector/key-value storage",
        "6. For Router nodes: implement intent classification or conditional routing",
        "7. For HumanHandoff nodes: implement escalation logic (queue, email, or webhook)",
        "8. Create an API route POST /api/agent/chat for interacting with the agent",
        "9. Store agent configuration in src/agents/config.ts",
        "10. Ensure all tool calls are type-safe and error-handled",
        "",
        "### MCP tool node wiring (authoritative)",
        "For any Tool node with `tool_type: mcp`, import `{ callMcpTool }` from",
        "`@/lib/integrations/mcpClientPool` and invoke it with (server_id, tool_name, args).",
        "The pool is auto-imported at runtime by the standalone-app template; do NOT",
        "instantiate a new MCP client per invocation. Example:",
        "```ts",
        "import { callMcpTool } from '@/lib/integrations/mcpClientPool';",
        "",
        "// tool_type='mcp', mcp_server_id='<uuid>', mcp_tool_name='search'",
        "async function runMcpTool(args: Record<string, unknown>) {",
        "  const result = await callMcpTool(",
        "    '<mcp_server_id>',",
        "    '<mcp_tool_name>',",
        "    args, // shape comes from args_mapping in the node config",
        "  );",
        "  return result; // { content: [...], isError: boolean }",
        "}",
        "```",
        "Credentials live in .env.local as `MCP_SERVER_<id_hex12>_SECRET` / `_URL` /",
        "`_TRANSPORT` / `_AUTH_KIND` / `_AUTH_HEADER` — the pool reads them by",
        "server id and handles connect/reconnect/auth.",
    ])

    return "\n".join(parts)

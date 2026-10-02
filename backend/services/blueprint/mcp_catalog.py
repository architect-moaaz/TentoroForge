"""The MCP servers an application can call, and the tools each one offers.

SnapIT's Firecrawl steps failed with "mcp_tool_call: no server matched"
(forge-v3, 2026-09-28): the workflow author was told only that an MCP step
needs `mcp_tool_name`, so it named no server, invented a tool Firecrawl does
not have (`firecrawl_search_and_extract`) and put the inputs beside the step
rather than under `args`, which is all the engine forwards. And nothing wrote
the organisation's servers into a Blueprint app, so there was nothing to
match anyway.

The organisation's servers are platform state, not definition. They are read
once per turn into `.forge/mcp-servers.json` — names and each tool's inputs,
never a URL or a key — so the author is shown what exists and the contract
can refuse a step that names anything else.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where the catalogue is kept, relative to the project directory.
PATH = ".forge/mcp-servers.json"
#: The step action that calls a tool.
ACTION = "mcp_tool_call"


def load(output_dir: str | Path | None) -> list[dict] | None:
    """The servers as last read, or None when they have never been read here
    (a project the platform has not refreshed — nothing to hold a step to)."""
    if not output_dir:
        return None
    path = Path(output_dir) / PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return [s for s in data.get("servers") or [] if isinstance(s, dict)] if isinstance(data, dict) else None


def tool_entry(name: str, description: str, schema: dict[str, Any]) -> dict:
    """A tool as the author needs it: its name, what it does, its inputs."""
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    return {"name": name, "description": " ".join(str(description or "").split())[:240],
            "required": [str(r) for r in schema.get("required") or []],
            "inputs": sorted(str(k) for k in props)[:30]}


def write(output_dir: str | Path, servers: list[dict]) -> None:
    path = Path(output_dir) / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"servers": servers}, indent=1, sort_keys=True), "utf-8")


async def refresh(output_dir: str | Path, org_id: Any, db: Any) -> list[dict]:
    """Read the organisation's enabled MCP servers and their tools into
    `.forge/mcp-servers.json`. A server that does not answer is kept with
    `tools: null`, so a step can still name it and the author is told why."""
    from sqlalchemy import select

    from models.platform_mcp_server import PlatformMcpServer
    from services.mcp_client import list_tools

    rows = (await db.execute(select(PlatformMcpServer).where(
        PlatformMcpServer.org_id == org_id, PlatformMcpServer.enabled.is_(True)))).scalars().all()
    servers: list[dict] = []
    for row in rows:
        entry: dict[str, Any] = {"name": row.name, "tools": None}
        try:
            entry["tools"] = [tool_entry(t.name, t.description, t.input_schema)
                              for t in await list_tools(row)]
        except Exception as exc:  # noqa: BLE001 — an unreachable server is reported, not fatal
            entry["unreachable"] = str(exc)[:200]
            logger.warning("[mcp_catalog] %s did not list its tools: %s", row.name, exc)
        servers.append(entry)
    write(output_dir, servers)
    return servers


def _server(servers: list[dict], name: str) -> dict | None:
    want = str(name or "").strip().lower()
    return next((s for s in servers if str(s.get("name") or "").strip().lower() == want), None)


def step_errors(step: dict, servers: list[dict] | None) -> list[str]:
    """What is wrong with one MCP step, in words the author can act on."""
    config = step.get("config") if isinstance(step.get("config"), dict) else {}
    if config.get("actionType") != ACTION:
        return []
    key = step.get("key") or step.get("name") or "step"
    errors: list[str] = []
    args = config.get("args")
    if not isinstance(args, dict):
        stray = sorted(k for k in config if k not in ("actionType", "nodeType", "mcp_server_name",
                                                      "mcp_server_id", "mcp_tool_name", "timeoutMs"))
        errors.append(f"{key}: the tool's inputs go in `config.args` (an object) — the engine forwards "
                      "nothing else" + (f"; {', '.join(stray)} beside it reach no tool" if stray else ""))
        args = {}
    if servers is None:
        if not str(config.get("mcp_server_name") or config.get("mcp_server_id") or "").strip():
            errors.append(f"{key}: name the server in `config.mcp_server_name`")
        return errors
    if not servers:
        return [f"{key}: this application's organisation has no MCP server connected, so "
                f"`{ACTION}` cannot run — do the work another way, or leave the step out"]
    names = ", ".join(str(s.get("name")) for s in servers)
    server = _server(servers, str(config.get("mcp_server_name") or ""))
    if server is None:
        errors.append(f"{key}: `config.mcp_server_name` is {config.get('mcp_server_name')!r}; "
                      f"the servers this application can call are: {names}")
        return errors
    tools = server.get("tools")
    if tools is None:
        return errors
    tool = next((t for t in tools if t.get("name") == config.get("mcp_tool_name")), None)
    if tool is None:
        errors.append(f"{key}: {server['name']} has no tool {config.get('mcp_tool_name')!r}; its tools "
                      f"are: {', '.join(str(t.get('name')) for t in tools)}")
        return errors
    missing = [r for r in tool.get("required") or [] if r not in args]
    if missing:
        errors.append(f"{key}: {tool['name']} requires {', '.join(missing)} in `config.args` "
                      f"(its inputs: {', '.join(tool.get('inputs') or [])})")
    unknown = [a for a in args if tool.get("inputs") and a not in tool["inputs"]]
    if unknown:
        errors.append(f"{key}: {tool['name']} takes no {', '.join(unknown)} (its inputs: "
                      f"{', '.join(tool.get('inputs') or [])})")
    return errors


def workflow_errors(body: dict, servers: list[dict] | None) -> list[str]:
    name = body.get("name") or "workflow"
    return [f"{name}/{e}" for s in body.get("steps") or [] if isinstance(s, dict)
            for e in step_errors(s, servers)]


def prompt_block(servers: list[dict] | None) -> str:
    """What the step author is told about calling a tool."""
    if servers is None:
        return ""
    if not servers:
        return ("\n\nMCP TOOLS: this application's organisation has no MCP server connected, so "
                f"`{ACTION}` cannot run here. Do the work with the other nodes, or leave it out.")
    lines = ["", "", f"MCP TOOLS — a `{ACTION}` step names the server in `mcp_server_name`, a tool it "
             "lists in `mcp_tool_name`, and passes the tool's inputs in `args` (values may be "
             "`{{template}}`s); a required input is always given. Nothing else reaches the tool. "
             "The servers this application can call:"]
    for s in servers:
        tools = s.get("tools")
        if tools is None:
            lines.append(f"- {s.get('name')}: did not list its tools just now")
            continue
        lines.append(f"- {s.get('name')}:")
        for t in tools:
            req = ", ".join(t.get("required") or []) or "none"
            lines.append(f"    {t['name']} — {t.get('description') or ''} (required: {req}; "
                         f"inputs: {', '.join(t.get('inputs') or [])})")
    return "\n".join(lines)

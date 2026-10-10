"""Compile an Agent Builder node graph into the runtime's ``AgentRuntimeConfig``.

The builder (and the planner's ``agent_graph``) describe an agent as nodes and
edges — what a person edits on a canvas. The runtime that ships in every
generated app (``templates/runtime/agents/``) does not walk that graph; it reads
a flat, validated config. This module is the deterministic step between the two,
so applying an agent never needs a model to write code: the same graph always
compiles to the same config.

What it cannot express, it says so — the returned ``warnings`` name every tool or
rule that was dropped or degraded, instead of shipping an agent that silently
cannot do what its definition promised.

The shape it produces is declared in ``templates/runtime/agents/types.ts``;
keep the two in step.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

# The agent's own door — a tool that reaches it would call the agent from the agent.
_SELF_ROUTE = re.compile(r"^/api/agent(/|$)")

_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_MAX_TURNS = 8
_MAX_TURNS_CEILING = 12
_DEFAULT_MEMORY_MESSAGES = 20

_DEFAULT_INPUT_BLOCK = [r"ignore (all )?(previous|prior) instructions", r"reveal (your )?system prompt"]

_PII_OUTPUT_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",                      # SSN
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # card number
]

# A function tool that was only described, never given code, but plainly means one
# of the AI presets the runtime already ships.
_AI_PRESET_BY_NAME = [
    (re.compile(r"^identify_(product|item|thing|object|image)"), "identify_product"),
]

_JSON_TYPES = {"string", "number", "integer", "boolean", "object", "array"}


@dataclass
class CompiledAgent:
    """One agent, ready to write into an app."""

    id: str
    config: dict[str, Any]
    #: handler stem -> TypeScript source, for function tools that came with code.
    tool_files: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def safe_id(raw: Any) -> str:
    """A file- and URL-safe form of an agent id."""
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", str(raw or "").strip()).strip("-")
    return s[:80] or "agent"


def tool_name(raw: Any, taken: set[str], fallback: str) -> str:
    """The Anthropic tool-name alphabet (``[A-Za-z0-9_-]{1,64}``), made unique."""
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", str(raw or "").strip()).strip("_")[:60] or fallback
    name, n = base, 2
    while name in taken:
        name = f"{base}_{n}"
        n += 1
    taken.add(name)
    return name


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None,
         *, open_: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": props or {}}
    if required:
        out["required"] = required
    if open_:
        out["additionalProperties"] = True
    return out


def _from_parameters(params: Any) -> dict[str, Any] | None:
    """The builder's ``parameters: [{name, type, required, description}]``."""
    if not isinstance(params, list) or not params:
        return None
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in params:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        t = str(p.get("type") or "string").lower()
        prop: dict[str, Any] = {"type": t if t in _JSON_TYPES else "string"}
        if p.get("description"):
            prop["description"] = str(p["description"])
        props[str(p["name"])] = prop
        if p.get("required"):
            required.append(str(p["name"]))
    return _obj(props, required) if props else None


_DATA_SCHEMAS: dict[str, tuple[dict[str, Any], list[str]]] = {
    "list": ({
        "search": {"type": "string", "description": "Free-text search over the records."},
        "filters": {"type": "object", "description": "Exact-match filters, e.g. {\"status\": \"open\"}.",
                    "additionalProperties": True},
        "limit": {"type": "integer", "description": "How many records (default 50)."},
        "page": {"type": "integer"},
        "sort": {"type": "string", "description": "A field name to sort by."},
        "order": {"type": "string", "enum": ["asc", "desc"]},
    }, []),
    "get": ({"id": {"type": "string", "description": "The record's id."}}, ["id"]),
    "create": ({"data": {"type": "object", "description": "The new record's fields.",
                         "additionalProperties": True}}, ["data"]),
    "update": ({"id": {"type": "string", "description": "The record's id."},
                "data": {"type": "object", "description": "The fields to change.",
                         "additionalProperties": True}}, ["id", "data"]),
    "delete": ({"id": {"type": "string", "description": "The record's id."}}, ["id"]),
}

_PLACEHOLDER = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def _mapped_inputs(args_mapping: Any, tool_names: set[str]) -> list[str]:
    """The model-supplied inputs an MCP ``args_mapping`` reads: ``{{input.q}}`` or a
    bare ``{{q}}`` whose first segment is not another tool's name."""
    found: list[str] = []
    if not isinstance(args_mapping, dict):
        return found
    for v in args_mapping.values():
        for m in _PLACEHOLDER.finditer(str(v)):
            path = m.group(1)
            head = re.sub(r"^input\.", "", path).split(".")[0]
            if path.startswith("input.") or head not in tool_names:
                if head and head not in found:
                    found.append(head)
    return found


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

def _compile_tool(node_id: str, cfg: dict[str, Any], label: str, taken: set[str],
                  all_tool_names: set[str], warnings: list[str],
                  tool_files: dict[str, str]) -> dict[str, Any] | None:
    name = tool_name(cfg.get("tool_name") or label, taken, f"tool_{len(taken) + 1}")
    description = str(cfg.get("description") or label or name)
    ttype = str(cfg.get("tool_type") or "function").lower()
    code = cfg.get("code")
    base: dict[str, Any] = {"name": name, "description": description}
    if cfg.get("response_filter") or cfg.get("response_schema"):
        keys = cfg.get("response_filter")
        if isinstance(keys, list):
            base["responseFilter"] = [str(k) for k in keys]
    if cfg.get("rate_limit"):
        base["rateLimit"] = str(cfg["rate_limit"])
    if cfg.get("require_auth") is False:
        base["requireAuth"] = False

    if ttype == "data_engine":
        entity = cfg.get("entity")
        op = str(cfg.get("operation") or "list").lower()
        if not entity:
            warnings.append(f"tool '{name}' is a data tool with no entity — dropped")
            return None
        if op not in _DATA_SCHEMAS:
            warnings.append(f"tool '{name}': unknown operation '{op}' — treated as list")
            op = "list"
        props, required = _DATA_SCHEMAS[op]
        return {**base, "kind": "data", "entity": str(entity), "operation": op,
                "inputSchema": _obj(props, required)}

    if ttype == "workflow":
        wf = cfg.get("workflow_id")
        if not wf:
            warnings.append(f"tool '{name}' is a workflow tool with no workflow — dropped")
            return None
        schema = _from_parameters(cfg.get("parameters")) or _obj(open_=True)
        return {**base, "kind": "workflow", "workflowId": str(wf), "inputSchema": schema}

    if ttype in ("api_call", "external"):
        endpoint = str(cfg.get("endpoint") or "")
        if not endpoint.startswith("/") or _SELF_ROUTE.match(endpoint):
            warnings.append(
                f"tool '{name}' calls '{endpoint or '(no endpoint)'}' — only this app's own /api routes "
                "can be called; it was kept as unimplemented"
            )
            return {**base, "kind": "function", "inputSchema": _obj(open_=True)}
        path_params = re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", endpoint)
        schema = _from_parameters(cfg.get("parameters")) or _obj(
            {p: {"type": "string"} for p in path_params}, path_params, open_=True)
        return {**base, "kind": "api", "endpoint": endpoint,
                "method": str(cfg.get("method") or "GET").upper(), "inputSchema": schema}

    if ttype == "db_query":
        warnings.append(
            f"tool '{name}' is raw SQL — an agent does not get raw SQL; use a data tool "
            "(list/get/create/update) instead. Kept as unimplemented"
        )
        return {**base, "kind": "function", "inputSchema": _obj(open_=True)}

    if ttype == "mcp":
        server = cfg.get("mcp_server_id")
        mcp_tool = cfg.get("mcp_tool_name") or name
        if not server:
            warnings.append(f"tool '{name}' names no MCP server — dropped")
            return None
        from services.env_writer import _mcp_id_slug  # the slug the app's .env.local is keyed by
        try:
            slug = _mcp_id_slug(uuid.UUID(str(server)))
        except ValueError:
            slug = _mcp_id_slug(server)
        mapping = cfg.get("args_mapping") if isinstance(cfg.get("args_mapping"), dict) else {}
        inputs = _mapped_inputs(mapping, all_tool_names)
        spec: dict[str, Any] = {**base, "kind": "mcp", "mcpServerId": slug, "mcpToolName": str(mcp_tool),
                                "inputSchema": _obj({k: {"type": "string"} for k in inputs}, open_=True)}
        if mapping:
            spec["argsMapping"] = {str(k): str(v) for k, v in mapping.items()}
        return spec

    # function (and anything unrecognised)
    ai = cfg.get("ai_action")
    if not ai and not code:
        for rx, preset in _AI_PRESET_BY_NAME:
            if rx.match(name):
                ai = preset
                break
    if ai in ("identify_product", "classify", "extract", "generate"):
        if ai == "identify_product":
            schema = _obj({"image_file_id": {"type": "string",
                                             "description": "The id of the uploaded image (a forge_files id)."}},
                          ["image_file_id"])
        else:
            schema = _obj({"input": {"type": "string", "description": "The text to work on."}}, ["input"])
        return {**base, "kind": "ai_action", "aiAction": ai,
                "aiConfig": cfg.get("ai_config") if isinstance(cfg.get("ai_config"), dict) else {},
                "inputSchema": schema}
    schema = _from_parameters(cfg.get("parameters")) or _obj(open_=True)
    if code and str(code).strip():
        handler = name
        tool_files[handler] = render_tool_module(name, str(code))
        return {**base, "kind": "function", "handler": handler, "inputSchema": schema}
    warnings.append(
        f"tool '{name}' was described but has no code — it will report 'no implementation yet' when called"
    )
    return {**base, "kind": "function", "inputSchema": schema}


def render_tool_module(name: str, code: str) -> str:
    """A tool module: the planner's TypeScript body wrapped in the handler signature
    the runtime calls, or the module as written when it already exports one."""
    header = "// forge-agent-tool — generated from the agent definition; edit the agent, not this file.\n"
    if re.search(r"export\s+default", code):
        return header + code.rstrip() + "\n"
    return (
        header
        + 'import type { ToolContext } from "@/lib/agents/types";\n\n'
        + f"export default async function {re.sub(r'[^A-Za-z0-9_]', '_', name)}(\n"
        + "  input: Record<string, unknown>,\n"
        + '  ctx: Pick<ToolContext, "user" | "cookie" | "origin">,\n'
        + "): Promise<unknown> {\n"
        + "  void ctx;\n"
        + code.rstrip()
        + "\n}\n"
    )


# ---------------------------------------------------------------------------
# guardrails / memory / ui
# ---------------------------------------------------------------------------

def _topics_to_pattern(expression: str) -> str | None:
    topics = [t.strip() for t in re.split(r"[,;\n]", expression) if t.strip()]
    if not topics:
        return None
    return r"\b(" + "|".join(re.escape(t) for t in topics) + r")\b"


def _compile_guardrails(nodes: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    input_block = list(_DEFAULT_INPUT_BLOCK)
    output_block: list[str] = []
    content_filter = "standard"
    output_rules: list[dict[str, Any]] = []
    max_length = 2000

    for node in nodes:
        cfg = (node.get("data") or {}).get("config") or {}
        label = (node.get("data") or {}).get("label") or node.get("id")
        gtype = str(cfg.get("guardrail_type") or "both")
        rules = [r for r in (cfg.get("rules") or []) if isinstance(r, dict)]
        if cfg.get("custom_expression"):
            rules.append({"name": f"{label}", "type": "custom", "expression": cfg["custom_expression"]})
        for r in rules:
            rtype = str(r.get("type") or "custom")
            expr = str(r.get("expression") or r.get("expr") or "").strip()
            rname = str(r.get("name") or rtype)
            if rtype == "block_topics":
                pat = _topics_to_pattern(expr)
                if pat:
                    input_block.append(pat)
                    if gtype in ("output_filter", "both"):
                        output_block.append(pat)
                else:
                    warnings.append(f"guardrail rule '{rname}' blocks topics but lists none — ignored")
            elif rtype == "pii_redaction":
                output_block.extend(_PII_OUTPUT_PATTERNS)
                content_filter = "strict"
            elif rtype == "content_policy":
                content_filter = "strict"
            elif rtype == "custom":
                if not expr:
                    warnings.append(f"guardrail rule '{rname}' has no expression — ignored")
                elif gtype == "input_filter":
                    warnings.append(
                        f"guardrail rule '{rname}' is a custom input filter — expressions are checked "
                        "against tool results, which an input does not have; ignored"
                    )
                else:
                    output_rules.append({"name": rname, "expression": expr,
                                         "message": f"The answer did not pass the check \"{rname}\"."})
            else:
                warnings.append(f"guardrail rule '{rname}' has unknown type '{rtype}' — ignored")

    return {
        "input": {"maxLength": max_length, "blockPatterns": input_block, "requireAuth": True},
        "output": {"blockPatterns": output_block, "contentFilter": content_filter},
        "outputRules": output_rules,
    }


def _compile_memory(node: dict[str, Any] | None, warnings: list[str]) -> dict[str, Any]:
    cfg = ((node or {}).get("data") or {}).get("config") or {}
    mtype = str(cfg.get("memory_type") or "conversation")
    if mtype not in ("conversation", "key_value", "vector"):
        mtype = "conversation"
    if mtype != "conversation":
        warnings.append(
            f"memory type '{mtype}' is not supported yet — the agent remembers the conversation only"
        )
    cap = cfg.get("capacity")
    messages = int(cap) if mtype == "conversation" and isinstance(cap, (int, float)) and cap > 0 \
        else _DEFAULT_MEMORY_MESSAGES
    messages = max(2, min(messages, 200))
    return {"type": mtype, "maxMessages": messages, "summarizeAfter": max(messages + 10, int(messages * 1.5))}


def _compile_ui(name: str, description: str | None, config: dict[str, Any]) -> dict[str, Any]:
    ui_in = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    position = str(ui_in.get("position") or "bottom-right")
    if position not in ("bottom-right", "bottom-left", "full-page"):
        position = "bottom-right"
    ui: dict[str, Any] = {
        "title": str(ui_in.get("title") or name),
        "welcomeMessage": str(ui_in.get("welcome_message") or ui_in.get("welcomeMessage")
                              or f"Hi! I'm {name}. How can I help?"),
        "position": position,
    }
    sub = ui_in.get("subtitle") or description
    if sub:
        ui["subtitle"] = str(sub)
    qs = ui_in.get("suggested_questions") or ui_in.get("suggestedQuestions")
    if isinstance(qs, list) and qs:
        ui["suggestedQuestions"] = [str(q) for q in qs][:6]
    return ui


# ---------------------------------------------------------------------------
# the compiler
# ---------------------------------------------------------------------------

def _entry_prompt(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    sps = [n for n in nodes if (n.get("data") or {}).get("nodeType") == "system_prompt"
           or n.get("type") == "system_prompt"]
    for n in sps:
        if ((n.get("data") or {}).get("config") or {}).get("is_entry_point"):
            return n
    return sps[0] if sps else {}


def compile_agent(agent_data: dict[str, Any]) -> CompiledAgent:
    """Compile one builder definition. Never raises on a malformed node — it warns."""
    warnings: list[str] = []
    tool_files: dict[str, str] = {}
    name = str(agent_data.get("name") or "Assistant").strip() or "Assistant"
    description = agent_data.get("description")
    agent_id = safe_id(agent_data.get("id") or name)
    nodes = [n for n in (agent_data.get("nodes") or []) if isinstance(n, dict)]
    config_in = agent_data.get("config") if isinstance(agent_data.get("config"), dict) else {}

    def of(kind: str) -> list[dict[str, Any]]:
        return [n for n in nodes
                if (n.get("data") or {}).get("nodeType") == kind or n.get("type") == kind]

    sp = _entry_prompt(nodes)
    sp_cfg = (sp.get("data") or {}).get("config") or {}
    prompt = str(sp_cfg.get("prompt") or "").strip()
    if not prompt:
        prompt = (f"You are {name}, an assistant inside this application. Use your tools to look things up "
                  "and to act for the person you are talking to. If you cannot do something, say so plainly.")
        warnings.append("the agent has no system prompt — a default one was used")

    # Tool names are fixed first so a later tool's args_mapping can tell a reference to
    # an earlier tool's result from a reference to the model's own input.
    tool_nodes = of("tool")
    taken: set[str] = set()
    pre_names = {tool_name(((n.get("data") or {}).get("config") or {}).get("tool_name")
                           or (n.get("data") or {}).get("label"), set(), "tool")
                 for n in tool_nodes}
    tools: list[dict[str, Any]] = []
    for n in tool_nodes:
        d = n.get("data") or {}
        t = _compile_tool(str(n.get("id")), d.get("config") or {}, str(d.get("label") or ""),
                          taken, pre_names, warnings, tool_files)
        if t:
            tools.append(t)

    max_tokens = sp_cfg.get("max_tokens")
    model: dict[str, Any] = {"maxTokens": int(max_tokens) if isinstance(max_tokens, (int, float)) and max_tokens > 0
                             else _DEFAULT_MAX_TOKENS}
    if sp_cfg.get("model"):
        model["name"] = str(sp_cfg["model"])
    if isinstance(sp_cfg.get("temperature"), (int, float)):
        model["temperature"] = float(sp_cfg["temperature"])

    memory_nodes = of("memory")
    if len(memory_nodes) > 1:
        warnings.append("more than one memory node — the first is used")
    routers, handoffs = of("router"), of("human_handoff")
    if routers or handoffs:
        warnings.append("router and human-handoff nodes are carried in the definition but not executed yet")

    max_turns = config_in.get("max_turns")
    turns = int(max_turns) if isinstance(max_turns, (int, float)) and max_turns > 0 else _DEFAULT_MAX_TURNS

    config: dict[str, Any] = {
        "id": agent_id,
        "name": name,
        "enabled": agent_data.get("enabled", True) is not False,
        "model": model,
        "systemPrompt": prompt,
        "tools": tools,
        "memory": _compile_memory(memory_nodes[0] if memory_nodes else None, warnings),
        "guardrails": _compile_guardrails(of("guardrail"), warnings),
        "maxTurns": min(turns, _MAX_TURNS_CEILING),
        "ui": _compile_ui(name, str(description) if description else None, config_in),
    }
    if description:
        config["description"] = str(description)
    if routers:
        config["router"] = ((routers[0].get("data") or {}).get("config")) or {}
    if handoffs:
        config["handoff"] = ((handoffs[0].get("data") or {}).get("config")) or {}
        # A handoff node is drawn but nothing carries the person to anyone yet. An agent that
        # believes it can ("passing you to the support queue") tells a person help is coming
        # when it is not (Movie Review, 2026-10-10) — so until the runtime executes handoffs,
        # the prompt says the truth.
        config["systemPrompt"] = (str(config["systemPrompt"]).rstrip()
                                  + "\n\nYou cannot transfer anyone to a human or a support queue from here — "
                                    "nothing would receive them. If someone asks for a person, say so plainly, "
                                    "and suggest they contact the app's administrator.")

    return CompiledAgent(id=agent_id, config=config, tool_files=tool_files, warnings=warnings)


def render_registry(agent_ids: list[str], handlers: list[str]) -> str:
    """``src/agents/registry.ts`` — the one module the chat route imports."""
    lines = [
        "// Generated by the Forge platform from the agent definitions. Edit the agent in the",
        "// Agent Builder and apply it; changes made here are overwritten.",
        'import type { AgentRuntimeConfig } from "@/lib/agents/types";',
    ]
    for i, aid in enumerate(agent_ids):
        lines.append(f"import agent{i} from {json.dumps('./definitions/' + aid + '.json')};")
    lines.append("")
    items = ", ".join(f"agent{i}" for i in range(len(agent_ids)))
    lines.append(f"export const AGENTS = [{items}] as unknown as AgentRuntimeConfig[];")
    lines.append("")
    lines.append("export const TOOL_HANDLERS: Record<")
    lines.append("  string,")
    lines.append("  () => Promise<{ default: (input: Record<string, unknown>, ctx: any) => Promise<unknown> }>")
    lines.append("> = {")
    for h in handlers:
        lines.append(f"  {json.dumps(h)}: () => import({json.dumps('./tools/' + h)}),")
    lines.append("};")
    return "\n".join(lines) + "\n"

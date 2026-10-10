"""What is wrong with an agent, said before Apply.

Until now a problem with an agent showed up AFTER Apply (a line in the install log nobody read) or in
chat (a 403, a tool that "has no implementation yet"). The compiler already knows most of it and the
app on disk knows the rest, so the builder can say it while the person is still looking at the box.

Each finding is `{severity, nodeId, code, message}` and `nodeId` is the box on the canvas it is about,
so the screen can mark it. Severities:

* ``error``   — something the person drew will NOT work (a tool for a workflow the app does not have).
* ``warning`` — it will work differently from what was drawn, or only in part.
* ``info``    — worth knowing (a box that is saved but does nothing yet).

Plain language, no model. Checks against the app are skipped, and `appChecked` says so, when the
project has no built app yet.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from services.agent_access import read_entity_access, read_workflows, reconcile_agent
from services.agent_runtime_config import compile_agent, tool_name

#: More tools than this and a model starts to choose badly between them.
MANY_TOOLS = 25

_TOOL_IN_MESSAGE = re.compile(r"tool '([^']+)'")


def _finding(severity: str, code: str, message: str, node_id: str | None = None) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "nodeId": node_id}


def _kind(node: dict[str, Any]) -> str:
    return str((node.get("data") or {}).get("nodeType") or node.get("type") or "")


def _tool_nodes_by_name(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """The compiled tool name -> the node it came from, named exactly as the compiler names them."""
    taken: set[str] = set()
    out: dict[str, str] = {}
    for n in nodes:
        if _kind(n) != "tool":
            continue
        d = n.get("data") or {}
        cfg = d.get("config") or {}
        name = tool_name(cfg.get("tool_name") or d.get("label"), taken, f"tool_{len(taken) + 1}")
        out[name] = str(n.get("id"))
    return out


def _classify_compile_warning(text: str) -> tuple[str, str] | None:
    """(severity, code) for a compiler warning, or None when it is covered some other way."""
    t = text.lower()
    if "not executed yet" in t:
        return None  # said once per box below, in words that fit the box
    if "human-handoff box names no one" in t:
        return "warning", "handoff_no_handlers"
    if "handoff assignment" in t:
        return "warning", "handoff_assignment"
    if "more than one human-handoff box" in t:
        return "warning", "handoff_many"
    if "no system prompt" in t:
        return "warning", "no_system_prompt"
    if "dropped" in t:
        return "error", "tool_dropped"
    if "no implementation yet" in t or "kept as unimplemented" in t:
        return "warning", "tool_unimplemented"
    if "raw sql" in t:
        return "warning", "raw_sql"
    if "not supported yet" in t:
        return "warning", "memory_downgraded"
    if "custom input filter" in t:
        return "warning", "custom_filter"
    return "warning", "compile"


def _friendly(text: str) -> str:
    """The compiler's note, as a sentence for the person who drew the box."""
    text = text.replace("—", "-").replace("�", "-")
    return text[:1].upper() + text[1:]


def check_agent(graph: dict[str, Any], app_root: Path | None = None) -> dict[str, Any]:
    """``{"findings": [...], "appChecked": bool}`` for a builder graph."""
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    by_name = _tool_nodes_by_name(nodes)
    compiled = compile_agent(graph)
    findings: list[dict[str, Any]] = []

    sp = next((n for n in nodes if _kind(n) == "system_prompt"), None)
    sp_id = str(sp.get("id")) if sp else None

    # 1 — what the compiler already says, each pinned to its box
    for w in compiled.warnings:
        verdict = _classify_compile_warning(w)
        if verdict is None:
            continue
        severity, code = verdict
        m = _TOOL_IN_MESSAGE.search(w)
        node_id = by_name.get(m.group(1)) if m else None
        if code == "no_system_prompt":
            node_id = sp_id
        elif code == "memory_downgraded":
            node_id = next((str(n.get("id")) for n in nodes if _kind(n) == "memory"), None)
        elif code == "custom_filter":
            node_id = next((str(n.get("id")) for n in nodes if _kind(n) == "guardrail"), None)
        elif code.startswith("handoff_"):
            node_id = next((str(n.get("id")) for n in nodes if _kind(n) == "human_handoff"), None)
        findings.append(_finding(severity, code, _friendly(w), node_id))

    # 2 — boxes that are saved but do nothing yet (human handoff is real now; the router is not)
    for n in nodes:
        if _kind(n) == "router":
            findings.append(_finding(
                "info", "router_not_running",
                "The router is saved but does not run yet: one agent handles every message.", str(n.get("id"))))

    # 3 — the agent as a whole
    tools = compiled.config.get("tools") or []
    if not tools:
        findings.append(_finding("warning", "no_tools", "This agent has no tools, so it can only chat; it cannot look anything up or do anything.", sp_id))
    elif len(tools) > MANY_TOOLS:
        findings.append(_finding(
            "warning", "many_tools",
            f"This agent has {len(tools)} tools. Past about {MANY_TOOLS} a model starts picking the wrong one; "
            "consider keeping only what people will really ask for.", sp_id))

    # 4 — against the app, when there is one
    app_checked = bool(app_root and (Path(app_root) / "package.json").is_file())
    if app_checked:
        root = Path(app_root)  # type: ignore[arg-type]
        access = read_entity_access(root)
        workflows = {w["id"] for w in read_workflows(root)}
        has_workflow_dir = (root / "src" / "lib" / "workflows" / "definitions").is_dir()

        # a write the app refuses: say what Apply will do about it
        for note in reconcile_agent({**compiled.config, "tools": [dict(t) for t in tools],
                                     "systemPrompt": compiled.config.get("systemPrompt", "")}, root):
            m = _TOOL_IN_MESSAGE.search(note)
            node_id = by_name.get(m.group(1)) if m else None
            if "was removed" in note:
                findings.append(_finding("error", "write_refused_removed", _friendly(note) + ".", node_id))
            else:
                findings.append(_finding("warning", "write_refused_swapped", _friendly(note) + ".", node_id))

        for t in tools:
            node_id = by_name.get(str(t.get("name")))
            if t.get("kind") == "workflow" and has_workflow_dir and t.get("workflowId") not in workflows:
                findings.append(_finding(
                    "error", "unknown_workflow",
                    f"Tool '{t.get('name')}' runs a workflow called '{t.get('workflowId')}', and this app has no such workflow, "
                    "so the tool will fail every time.", node_id))
            if t.get("kind") == "data" and access:
                entity = str(t.get("entity") or "").lower()
                if entity and entity not in access and f"{entity}s" not in access and entity.rstrip("s") not in access:
                    findings.append(_finding(
                        "error", "unknown_table",
                        f"Tool '{t.get('name')}' reads or writes '{t.get('entity')}', and this app has no table with that name.",
                        node_id))

        # human handoff, against the app: the roles it names must exist; email is optional and never required
        handoff = compiled.config.get("handoff")
        handoff_id = next((str(n.get("id")) for n in nodes if _kind(n) == "human_handoff"), None)
        if handoff:
            known = {r.lower() for rules in access.values() for r in (rules.get("read", []) + rules.get("write", []))}
            for role in handoff["handlers"]["roles"]:
                if known and role.lower() not in known:
                    findings.append(_finding(
                        "error", "handoff_unknown_role",
                        f"The human-handoff box names the role '{role}', and this app has no such role, so nobody would "
                        "be notified or allowed to handle those handoffs.", handoff_id))

        env = ""
        for name in (".env.local", ".env"):
            try:
                env += (root / name).read_text(encoding="utf-8") + "\n"
            except OSError:
                pass
        if handoff and handoff["notify"]["email"] and not re.search(r"^(SMTP_HOST|RESEND_API_KEY)=\S+", env, re.M):
            findings.append(_finding(
                "warning", "handoff_email_not_set_up",
                "Email is turned on for handoffs, but this app has no email set up (no SMTP_HOST or RESEND_API_KEY). "
                "Handoffs still work: they are saved in the inbox and the bell notifies people; no email is sent.", handoff_id))
        if not re.search(r"^ANTHROPIC_API_KEY=\S+", env, re.M):
            findings.append(_finding(
                "warning", "no_ai_key",
                "This app's environment has no Anthropic key. Chat will answer with placeholder text until one is set "
                "(in the app's .env.local, or under Settings > Integrations if you keep it there).", sp_id))

    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: order[f["severity"]])
    return {"findings": findings, "appChecked": app_checked}

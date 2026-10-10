"""Install the AI-agent runtime into a generated app — deterministically.

The runtime itself is fixed code under ``templates/runtime/agents/`` (loop, tools,
memory, guardrails, store, chat route, widget). What differs per app is only the
agent *definitions*, and those are data: this module compiles every definition in
``<project>/agent-definitions/*.json`` (the Agent Builder's and the planner's
output) into ``src/agents/definitions/<id>.json`` and copies the runtime beside
them. No model is involved, so applying an agent twice yields the same files, and
the result is something a test can check.

Idempotent: re-running rewrites what it owns and removes definitions and tool
modules whose agent no longer exists. It touches nothing it did not write — the
widget mount is a marker-delimited patch to the dashboard layout, the schema
export a single barrel line.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from services.agent_access import reconcile_agent
from services.agent_runtime_config import CompiledAgent, compile_agent, render_registry, safe_id

logger = logging.getLogger(__name__)

AGENT_DEFS_DIR = "agent-definitions"  # the builder's graphs, at the project root
_TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "runtime"
_TOOL_MARKER = "// forge-agent-tool"
_LAYOUT_MARK = "forge-agent"
_NAV_MARK = "forge-handoffs-nav"

#: runtime template -> destination, relative to the app root
_CORE = ("types", "guardrails", "memory", "tools", "runtime", "io", "store", "handoff", "handoff-store", "handoff-nav",
         "confirm", "limits", "usage-store")


def resolve_roots(path: str | Path) -> tuple[Path, Path]:
    """``(project_root, app_root)`` for either one.

    A Blueprint project keeps its app in ``<project>/app`` and the builder's graphs
    beside it; the legacy relay output *is* the app. Callers hold one or the other.
    """
    p = Path(path)
    if (p / "app" / "package.json").is_file():
        return p, p / "app"
    if p.name == "app" and (p.parent / AGENT_DEFS_DIR).exists() and not (p / AGENT_DEFS_DIR).exists():
        return p.parent, p
    return p, p


def load_graphs(project_root: Path) -> list[dict[str, Any]]:
    d = project_root / AGENT_DEFS_DIR
    out: list[dict[str, Any]] = []
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("[agents] unreadable definition %s — skipped", f)
                continue
            if isinstance(data, dict):
                data.setdefault("id", f.stem)
                out.append(data)
    return out


def has_agents(path: str | Path) -> bool:
    """True when the project has at least one agent definition to install."""
    project_root, _ = resolve_roots(path)
    return bool(load_graphs(project_root))


def _copy(src: Path, dst: Path, written: list[str], app_root: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    written.append(dst.relative_to(app_root).as_posix())


def _barrel_export(schema_dir: Path, line: str, needle: str) -> None:
    barrel = schema_dir / "index.ts"
    if barrel.exists():
        txt = barrel.read_text(encoding="utf-8")
        if needle not in txt:
            barrel.write_text(txt.rstrip() + "\n" + line + "\n", encoding="utf-8")


def _patch_layout(app_root: Path) -> bool:
    """Mount the floating widget in the dashboard shell, and add the "Handoffs" menu link. Returns True when the
    widget is mounted (already or now); False when the layout has no place we recognise."""
    layout = app_root / "src" / "app" / "(dashboard)" / "layout.tsx"
    if not layout.is_file():
        return False
    txt = layout.read_text(encoding="utf-8")
    imp_anchor = 'import { schemas } from "@/schemas/registry";'
    el_anchor = "      {children}\n      {mobileTabs.length > 0 && ("
    mounted = "@/components/agents/ChatWidget" in txt
    if not mounted and imp_anchor in txt and el_anchor in txt:
        txt = txt.replace(
            imp_anchor,
            imp_anchor + f'\nimport {{ ChatWidget }} from "@/components/agents/ChatWidget"; // {_LAYOUT_MARK}',
            1,
        )
        txt = txt.replace(
            el_anchor,
            f"      {{children}}\n      <ChatWidget />{{/* {_LAYOUT_MARK} */}}\n      {{mobileTabs.length > 0 && (",
            1,
        )
        mounted = True
    # A "Handoffs" menu link for the people who work the inbox. Best-effort and separate from the widget: a layout
    # without the anchors keeps its menu as it is (the bell still opens the inbox).
    nav_anchor = "  navProps.groups = visibleTo(navProps.groups, role);"
    if _NAV_MARK not in txt and nav_anchor in txt and imp_anchor in txt:
        txt = txt.replace(
            imp_anchor,
            imp_anchor + f'\nimport {{ withHandoffsLink }} from "@/lib/agents/handoff-nav"; // {_NAV_MARK}',
            1,
        )
        txt = txt.replace(
            nav_anchor,
            nav_anchor + f"\n  navProps.groups = withHandoffsLink(navProps.groups, session.user); // {_NAV_MARK}",
            1,
        )
    layout.write_text(txt, encoding="utf-8")
    return mounted


def _refresh_bell(app_root: Path, written: list[str]) -> None:
    """Give an app generated before handoffs the bell that opens them. Only the stock bell is replaced: one the
    app changed is left alone."""
    bell = app_root / "src" / "app" / "(dashboard)" / "NotificationBell.tsx"
    source = _TEMPLATES.parent / "app-foundation" / "src" / "app" / "(dashboard)" / "NotificationBell.tsx"
    if not bell.is_file() or not source.is_file():
        return
    try:
        current = bell.read_text(encoding="utf-8")
        if "/handoffs" in current or "forge:workflow-done" not in current:
            return
        _copy(source, bell, written, app_root)
    except OSError:
        logger.warning("[agents] could not refresh the notification bell", exc_info=True)


def _merge_manifest(app_root: Path, paths: list[str]) -> None:
    """Add what this install wrote to the runtime-injection manifest, so the route prune
    treats the agent routes as infrastructure rather than redundant CRUD."""
    manifest = app_root / "contracts" / "runtime-injection-manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
    except (OSError, ValueError):
        data = {}
    existing = [p for p in (data.get("paths") or []) if isinstance(p, str)]
    merged = sorted(set(existing) | set(paths))
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"version": 1, "paths": merged}, indent=2) + "\n", encoding="utf-8")


def _ensure_deps(app_root: Path) -> None:
    from services.runtime_injector import _ensure_package_deps

    _ensure_package_deps(app_root, {
        "@anthropic-ai/sdk": "^0.32.0",
        "@modelcontextprotocol/sdk": "^1.30.0",
    })


def install_agent_runtime(path: str | Path, *, graphs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compile the project's agent definitions and install the runtime beside them.

    ``graphs`` adds definitions that are not on disk yet (they are also written to
    ``agent-definitions/`` so the project stays the source of truth).

    Returns ``{"installed": bool, "agents": [{id,name,tools,warnings}], "written": [...],
    "widget_mounted": bool, "warnings": [...]}``; ``installed`` is False when there is
    nothing to install.
    """
    project_root, app_root = resolve_roots(path)

    # The definitions are the project's own and are kept wherever the project is; the
    # runtime goes INTO an app. A project that was never built has no app — only a
    # folder, or not even that — and scaffolding src/ into it would make it look
    # built (the chat treats any src/ file as "this project has code"). So the
    # definitions are saved and the install waits for the build, which runs it.
    no_app = not (app_root / "package.json").is_file()
    if no_app:
        for g in graphs or []:
            gid = safe_id(g.get("id") or g.get("name"))
            d = project_root / AGENT_DEFS_DIR
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{gid}.json").write_text(json.dumps({**g, "id": gid}, indent=2), encoding="utf-8")
        return {"installed": False, "no_app": True, "agents": [], "written": [], "widget_mounted": False,
                "warnings": ["the project has no generated app yet — the agent definition is saved and "
                             "will be installed when the app is built"]}

    for g in graphs or []:
        gid = safe_id(g.get("id") or g.get("name"))
        g = {**g, "id": gid}
        d = project_root / AGENT_DEFS_DIR
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{gid}.json").write_text(json.dumps(g, indent=2), encoding="utf-8")

    all_graphs = load_graphs(project_root)
    if not all_graphs:
        return {"installed": False, "agents": [], "written": [], "widget_mounted": False, "warnings": []}

    compiled: list[CompiledAgent] = []
    seen: set[str] = set()
    for g in all_graphs:
        c = compile_agent(g)
        # The app is on disk: a tool that asks it for something it refuses is fixed or
        # dropped now, not discovered as a 403 in the chat (services/agent_access.py).
        c.warnings.extend(reconcile_agent(c.config, app_root))
        if c.id in seen:  # two definitions that safe_id to the same stem: the later wins
            compiled = [x for x in compiled if x.id != c.id]
        seen.add(c.id)
        compiled.append(c)

    written: list[str] = []
    warnings: list[str] = []

    # ── the fixed runtime ────────────────────────────────────────────────
    agents_lib = app_root / "src" / "lib" / "agents"
    for stem in _CORE:
        _copy(_TEMPLATES / "agents" / f"{stem}.ts", agents_lib / f"{stem}.ts", written, app_root)
    _copy(_TEMPLATES / "agents" / "ChatWidget.tsx",
          app_root / "src" / "components" / "agents" / "ChatWidget.tsx", written, app_root)
    _copy(_TEMPLATES / "api-agent" / "chat-route.ts",
          app_root / "src" / "app" / "api" / "agent" / "chat" / "route.ts", written, app_root)
    _copy(_TEMPLATES / "api-agent" / "conversations-route.ts",
          app_root / "src" / "app" / "api" / "agent" / "conversations" / "route.ts", written, app_root)
    dashboard = app_root / "src" / "app" / "(dashboard)"
    if dashboard.is_dir():
        _copy(_TEMPLATES / "agents" / "assistant-page.tsx", dashboard / "assistant" / "page.tsx", written, app_root)
    # The inbox for handoffs: only where an agent has a human-handoff box. (The store and the table go in
    # always, because io.ts loads the store on demand and the build must find it.)
    if any(c.config.get("handoff") for c in compiled):
        _copy(_TEMPLATES / "api-agent" / "handoffs-route.ts",
              app_root / "src" / "app" / "api" / "agent" / "handoffs" / "route.ts", written, app_root)
        if dashboard.is_dir():
            _copy(_TEMPLATES / "agents" / "handoffs-page.tsx", dashboard / "handoffs" / "page.tsx", written, app_root)

    # ── conversation tables ──────────────────────────────────────────────
    schema_dir = app_root / "src" / "db" / "schema"
    if schema_dir.is_dir():
        _copy(_TEMPLATES / "db" / "forge-agent.schema.ts", schema_dir / "_forge_agent.ts", written, app_root)
        _barrel_export(
            schema_dir,
            'export { forgeAgentConversations, forgeAgentMessages } from "./_forge_agent";',
            "_forge_agent",
        )
        _copy(_TEMPLATES / "db" / "forge-agent-usage.schema.ts", schema_dir / "_forge_agent_usage.ts", written, app_root)
        _barrel_export(
            schema_dir,
            'export { forgeAgentUsage } from "./_forge_agent_usage";',
            "_forge_agent_usage",
        )
        _copy(_TEMPLATES / "db" / "forge-agent-handoffs.schema.ts", schema_dir / "_forge_agent_handoffs.ts", written, app_root)
        _barrel_export(
            schema_dir,
            'export { forgeAgentHandoffs } from "./_forge_agent_handoffs";',
            "_forge_agent_handoffs",
        )
    else:
        warnings.append("the app has no src/db/schema — conversation tables were not added")

    # ── what the io layer imports, when injection did not already put it there ──
    integrations = app_root / "src" / "lib" / "integrations"
    for name in ("resolver.ts", "mcpClientPool.ts"):
        if not (integrations / name).exists() and (_TEMPLATES / "integrations" / name).exists():
            _copy(_TEMPLATES / "integrations" / name, integrations / name, written, app_root)

    # ── the definitions ──────────────────────────────────────────────────
    defs_dir = app_root / "src" / "agents" / "definitions"
    tools_dir = app_root / "src" / "agents" / "tools"
    defs_dir.mkdir(parents=True, exist_ok=True)
    keep_defs = {f"{c.id}.json" for c in compiled}
    for stale in defs_dir.glob("*.json"):
        if stale.name not in keep_defs:
            stale.unlink()
    handlers: list[str] = []
    for c in compiled:
        (defs_dir / f"{c.id}.json").write_text(json.dumps(c.config, indent=2) + "\n", encoding="utf-8")
        written.append(f"src/agents/definitions/{c.id}.json")
        for stem, source in c.tool_files.items():
            tools_dir.mkdir(parents=True, exist_ok=True)
            (tools_dir / f"{stem}.ts").write_text(source, encoding="utf-8")
            written.append(f"src/agents/tools/{stem}.ts")
            handlers.append(stem)
        warnings.extend(f"{c.config['name']}: {w}" for w in c.warnings)
    if tools_dir.is_dir():
        for stale in tools_dir.glob("*.ts"):
            if stale.stem not in handlers and _TOOL_MARKER in stale.read_text(encoding="utf-8")[:200]:
                stale.unlink()
    (app_root / "src" / "agents").mkdir(parents=True, exist_ok=True)
    (app_root / "src" / "agents" / "registry.ts").write_text(
        render_registry([c.id for c in compiled], sorted(set(handlers))), encoding="utf-8")
    written.append("src/agents/registry.ts")

    _ensure_deps(app_root)
    if any(c.config.get("handoff") for c in compiled):
        _refresh_bell(app_root, written)
    mounted = _patch_layout(app_root)
    if not mounted:
        warnings.append("the dashboard layout was not recognised — the floating widget is not mounted "
                        "(the agent is still reachable at /assistant)")
    _merge_manifest(app_root, written)

    for w in warnings:
        logger.warning("[agents] %s", w)
    return {
        "installed": True,
        "agents": [{"id": c.id, "name": c.config["name"], "tools": len(c.config["tools"]),
                    "warnings": c.warnings} for c in compiled],
        "written": sorted(set(written)),
        "widget_mounted": mounted,
        "warnings": warnings,
    }

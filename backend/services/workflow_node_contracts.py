"""Auto-extracted workflow-node contract — the single source of truth for the
node/action vocabulary the workflow generator + planner may use.

Mirrors what packages/registry/scripts/extract-contracts.ts does for UI
components, but for the workflow runtime: it parses the runtime's own
`types.ts` (the NodeType / ActionType / TriggerType unions) and the handler
registrations (`registerActionHandler(...)` in index.ts + ai.ts, plus the
inline `actionType === "..."` handlers in engine.ts) so the prompt vocabulary
can never drift from what the engine actually executes.

Used by:
  - the planner prompt (format_node_catalog) — the LLM only proposes real nodes,
  - tests/test_workflow_node_contracts.py — a drift guard that fails the build
    when an emitted action has no handler or a handler regresses to a stub.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

_RT = Path(__file__).resolve().parent.parent / "templates" / "runtime" / "workflows"

# Actions intentionally left as no-ops. Empty: every workflow action must be
# functional — the drift test fails if ANY handler is a stub.
KNOWN_STUBS: set[str] = set()


def _union_members(text: str, type_name: str) -> list[str]:
    """Extract the string-literal members of a `export type <name> = ...;` union.

    Tolerant of both the leading-pipe multiline form (`= | "a" | "b";`, the runtime
    types.ts style) and the inline no-leading-pipe form (`= "a" | "b";`, the editor's
    ActionType style) — captures everything up to the terminating `;` and pulls the
    quoted literals out."""
    m = re.search(rf"export type {type_name}\s*=\s*([^;]+);", text)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


@functools.lru_cache(maxsize=1)
def node_contracts() -> dict:
    """Parse the runtime and return the workflow-node contract."""
    types = (_RT / "types.ts").read_text(encoding="utf-8")
    index = (_RT / "index.ts").read_text(encoding="utf-8")
    ai = (_RT / "ai.ts").read_text(encoding="utf-8")
    ocr = (_RT / "ocr.ts").read_text(encoding="utf-8")
    engine = (_RT / "engine.ts").read_text(encoding="utf-8")

    node_types = _union_members(types, "NodeType")
    action_types = _union_members(types, "ActionType")
    trigger_types = _union_members(types, "TriggerType")

    actions: dict[str, dict] = {}
    # Registered handlers (index.ts + ai.ts). A handler whose body window mentions
    # "no-op"/"not configured" is a stub (a silent placeholder).
    for src in (index, ai, ocr):
        for m in re.finditer(r'registerActionHandler\("([a-z_]+)"', src):
            name = m.group(1)
            block = src[m.start():m.start() + 900]
            stub = ("no-op" in block) or ("not configured" in block)
            # first registration wins; don't let a later window flip an earlier real one
            actions.setdefault(name, {"handled": "registered", "stub": stub})
    # Inline handlers in engine.ts (set_variable / transform).
    for m in re.finditer(r'actionType === "([a-z_]+)"', engine):
        actions.setdefault(m.group(1), {"handled": "inline", "stub": False})

    return {
        "node_types": node_types,
        "action_types": action_types,
        "trigger_types": trigger_types,
        "actions": actions,
    }


def real_actions() -> set[str]:
    """Action names that have a real (non-stub) handler."""
    return {a for a, info in node_contracts()["actions"].items() if not info.get("stub")}


def emit_node_catalog_json(out_path) -> Path:
    """Write the runtime-derived node catalog to `out_path` as JSON
    `{"nodeTypes":[...], "actionTypes":[...], "triggerTypes":[...]}` and return the
    path. Pure emission from `node_contracts()` — no network, deterministic."""
    c = node_contracts()
    catalog = {
        "nodeTypes": list(c["node_types"]),
        "actionTypes": list(c["action_types"]),
        "triggerTypes": list(c["trigger_types"]),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return out


def parse_editor_catalog(types_ts_path) -> dict:
    """Parse the EDITOR's hand-authored catalog (`frontend/src/types/workflow.ts`)
    into the vocabularies it exposes, so a drift guard (Task A5) can compare them
    against the runtime authority from `node_contracts()`.

    Returns:
      - `nodeTypes`     — members of the `WorkflowNodeType` union,
      - `actionTypes`   — members of the `ActionType` union,
      - `paletteTypes`  — every `type: "<x>"` literal in the `NODE_CATEGORIES` array,
      - `paletteActions`— every `actionType: "<x>"` (in `defaultConfig`) in that array.

    Pure parsing; tolerant of formatting/whitespace. Reuses `_union_members` for the
    two unions."""
    types_ts_path = Path(types_ts_path)
    text = types_ts_path.read_text(encoding="utf-8")

    node_types = set(_union_members(text, "WorkflowNodeType"))
    action_types = set(_union_members(text, "ActionType"))

    # The palette is derived from the workflow node catalog, whose frontend
    # copy sits beside the types file (`src/catalog/workflow-nodes.json`).
    catalog = json.loads(
        (types_ts_path.parents[1] / "catalog" / "workflow-nodes.json").read_text("utf-8")
    )
    palette_types = {n["type"] for n in catalog["nodes"] if n.get("palette", True)}
    palette_actions = {
        v["key"] for n in catalog["nodes"] if n["type"] == "action"
        for v in n.get("variants") or []
    }

    return {
        "nodeTypes": node_types,
        "actionTypes": action_types,
        "paletteTypes": palette_types,
        "paletteActions": palette_actions,
    }


def format_node_catalog() -> str:
    """A compact, authoritative catalog for the planner/business-logic prompt —
    the node types + actions that actually exist and run (stubs flagged)."""
    c = node_contracts()
    lines = [
        "## WORKFLOW NODE VOCABULARY (authoritative — only these exist at runtime)",
        "",
        "Node types: " + ", ".join(f"`{n}`" for n in c["node_types"]),
        "Trigger types: " + ", ".join(f"`{t}`" for t in c["trigger_types"]),
        "",
        "Action handlers (`action` nodes set config.actionType):",
    ]
    for name in sorted(c["actions"]):
        info = c["actions"][name]
        tag = " — STUB (no-op, avoid)" if info.get("stub") else ""
        lines.append(f"- `{name}`{tag}")
    lines.append("")
    lines.append("Do NOT invent node types or actionTypes not listed above — the engine has no handler for them.")
    lines.append("Every action above is FULLY IMPLEMENTED (no stubs); use real actions, never a placeholder.")
    lines.append("")
    lines.append("COMPOSE COMPLETE WORKFLOWS:")
    lines.append("- Start with a trigger and end every path at an `end` node — no dangling steps.")
    lines.append("- After an `ai_extract`, add a `db_insert`/`db_update` that persists the extracted fields.")
    lines.append("- Raise alerts (SLA breach, expiry, exception) with `send_notification` (or `send_email`).")
    lines.append("- Periodic checks (reminders, SLA/expiry sweeps, maintenance) use a `schedule` trigger.")
    lines.append("- `approval`/`user_task` steps need an assignee or role; use a pool for load-balancing.")
    lines.append("- Produce documents (invoice, certificate, report) with `generate_document`.")
    lines.append(
        "- Any variable a gateway/condition branches on MUST be produced by an "
        "upstream node — set it with a `set_variable`/`ai_decide`/`ai_generate` "
        "(declare its output) or read it from the trigger input/entity. Never "
        "branch on a variable no prior step writes (the branch would be dead)."
    )
    return "\n".join(lines)

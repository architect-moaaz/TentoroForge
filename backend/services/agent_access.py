"""An agent's tools are checked against what the app it lives in will actually allow.

THE BUG THIS EXISTS FOR (Movie Review, 2026-10-10). The builder offered the agent a
`data` tool that creates a rating and one that creates a comment. The generated app
lets nobody write `ratings` or `comments` through its data API (`ENTITY_ACCESS`
says ``write: []``) — those records are made by the SubmitRating and PostComment
workflows, which hold the app's rules (stars 1-5, one comment per person). So every
chat attempt came back 403 and the agent could never rate or comment, whoever was
signed in. Nothing at build time noticed: the compiler knew the agent's graph, not
the app's access rules.

The rule now: at install time, with the app on disk, each write tool is compared
with the app's own access list.

* A tool that writes an entity the app lets a person write is left alone.
* A tool that writes an entity nobody may write directly is REPLACED by the app's
  own workflow for that entity, when there is one (same tool name, so the prompt and
  the model still call it the same thing; the workflow's rules now apply).
* With no such workflow it is REMOVED and the agent's prompt is told it cannot do
  that, rather than shipping a tool that can only fail.

Every change is reported, so Apply shows what happened and why. Deterministic, no
model involved, and a no-op for an app that has no access list (older apps).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WRITE_OPS = {"create": "db_insert", "update": "db_update", "delete": "db_delete"}


# ---------------------------------------------------------------------------
# reading the app
# ---------------------------------------------------------------------------

def read_entity_access(app_root: Path) -> dict[str, dict[str, list[str]]]:
    """``{entity: {read: [roles], write: [roles]}}`` from the app's generated
    ``src/lib/entity-access.ts``; ``{}`` when absent or unreadable (no opinion)."""
    path = app_root / "src" / "lib" / "entity-access.ts"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.search(r"ENTITY_ACCESS[^=]*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(1))
    except ValueError:
        return {}
    out: dict[str, dict[str, list[str]]] = {}
    for entity, rules in raw.items():
        if isinstance(rules, dict):
            out[str(entity).lower()] = {
                "read": [str(r) for r in rules.get("read") or []],
                "write": [str(r) for r in rules.get("write") or []],
            }
    return out


def _blueprint_inputs(app_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Typed workflow inputs by blueprint id, when the project's Blueprint is on disk."""
    path = app_root.parent / ".forge" / "blueprint" / "current.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for wf in doc.get("workflows") or []:
        if isinstance(wf, dict) and wf.get("id"):
            out[str(wf["id"])] = [i for i in wf.get("inputs") or [] if isinstance(i, dict)]
    return out


def read_workflows(app_root: Path) -> list[dict[str, Any]]:
    """The app's workflows: ``{id, name, writes: {table: {op}}, inputs: [...]}``."""
    directory = app_root / "src" / "lib" / "workflows" / "definitions"
    if not directory.is_dir():
        return []
    typed = _blueprint_inputs(app_root)
    found: list[dict[str, Any]] = []
    for file in sorted(directory.glob("*.json")):
        try:
            doc = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        writes: dict[str, set[str]] = {}
        for node in (doc.get("definition") or {}).get("nodes") or []:
            cfg = ((node or {}).get("data") or {}).get("config") or {}
            action, table = cfg.get("actionType"), cfg.get("table")
            if action in _WRITE_OPS.values() and isinstance(table, str):
                writes.setdefault(table.lower(), set()).add(action)
        wid = str(doc.get("id") or file.stem)
        records = {str(r.get("name")): r for r in doc.get("recordInputs") or [] if isinstance(r, dict)}
        by_name = {str(i.get("name")): i for i in typed.get(str(doc.get("blueprintId") or ""), [])}
        inputs: list[dict[str, Any]] = []
        for name in doc.get("requiredInputs") or []:
            name = str(name)
            kind = "record" if name in records else str((by_name.get(name) or {}).get("type") or "string")
            inputs.append({"name": name, "kind": kind, "table": (records.get(name) or {}).get("table")})
        found.append({"id": wid, "name": str(doc.get("name") or wid), "writes": writes, "inputs": inputs})
    return found


# ---------------------------------------------------------------------------
# rewriting a tool
# ---------------------------------------------------------------------------

_JSON_TYPE = {"integer": "integer", "int": "integer", "number": "number", "decimal": "number",
              "float": "number", "boolean": "boolean", "bool": "boolean"}


def _input_schema(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for i in inputs:
        if i["kind"] == "record":
            props[i["name"]] = {
                "type": "object",
                "description": f'The {i.get("table") or i["name"]} record, as {{"id": "<its id>"}}. '
                               "Look the id up with a list tool first.",
                "properties": {"id": {"type": "string"}}, "required": ["id"],
            }
        else:
            props[i["name"]] = {"type": _JSON_TYPE.get(str(i["kind"]).lower(), "string")}
    return {"type": "object", "properties": props, "required": [i["name"] for i in inputs]}


def _workflow_for(entity: str, op: str, workflows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The workflow that performs ``op`` on ``entity``: one that really writes it (insert for
    create, update for update, delete for delete); a workflow that handles BOTH insert and
    update (an upsert, like SubmitRating) is the best match for either."""
    want = _WRITE_OPS[op]
    candidates = [w for w in workflows if want in w["writes"].get(entity, set())]
    if not candidates:
        return None
    candidates.sort(key=lambda w: (-len(w["writes"].get(entity, set())), w["id"]))
    return candidates[0]


def reconcile_agent(config: dict[str, Any], app_root: Path) -> list[str]:
    """Fix ``config`` in place so no tool asks the app for something it will refuse.
    Returns plain-language notes, one per change."""
    access = read_entity_access(app_root)
    if not access:
        return []
    workflows = read_workflows(app_root)
    notes: list[str] = []
    kept: list[dict[str, Any]] = []
    cannot: list[str] = []
    for tool in config.get("tools") or []:
        op = str(tool.get("operation") or "").lower()
        entity = str(tool.get("entity") or "").lower()
        closed = (tool.get("kind") == "data" and op in _WRITE_OPS and entity in access
                  and not access[entity]["write"])
        if not closed:
            kept.append(tool)
            continue
        wf = _workflow_for(entity, op, workflows)
        if wf:
            rewritten = {k: v for k, v in tool.items() if k not in ("entity", "operation")}
            rewritten.update({"kind": "workflow", "workflowId": wf["id"], "inputSchema": _input_schema(wf["inputs"])})
            kept.append(rewritten)
            notes.append(
                f"tool '{tool['name']}' wrote {entity} directly, which this app does not allow anyone to do — "
                f"it now runs the app's '{wf['name']}' workflow instead, so the app's own rules apply")
        else:
            cannot.append(f"{op} {entity}")
            notes.append(
                f"tool '{tool['name']}' wrote {entity} directly, which this app does not allow anyone to do, "
                "and no workflow does it either — the tool was removed")
    config["tools"] = kept
    if cannot:
        config["systemPrompt"] = (str(config.get("systemPrompt") or "").rstrip()
                                  + "\n\nYou cannot do these in this app: " + "; ".join(cannot)
                                  + ". If asked, say so plainly.")
    return notes

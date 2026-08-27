"""Tool palette for the Fix-Assistant agent (Slice 3, Task 3-A).

Thin, well-typed wrappers around the already-built Slice 0-2 primitives that
inspect and analyze a generated app. Every wrapper:

- takes ``output_dir`` first (the generated app on disk),
- returns a JSON-serializable dict,
- rejects absolute paths and ``..`` traversal for any user-supplied path arg,
- never raises — bad input becomes ``{"error": "..."}``.

The agent is given only these wrappers plus two terminal tools (``propose_fix``
and ``ask_user``) defined in :mod:`agents.fix_chat_agent`. Nothing here mutates the
app; the ``[APPLY_FIX]`` chip flow (Slice 1-D) is still the only apply gate.
"""
from __future__ import annotations

import glob
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REGISTRY_REL = os.path.join("contracts", "resource-registry.json")


# --------------------------------------------------------------------------- #
# path safety
# --------------------------------------------------------------------------- #

def _safe_rel(path: Any) -> Optional[str]:
    """Return a cleaned relative path, or None if it is absolute / escapes."""
    if not isinstance(path, str) or not path.strip():
        return None
    p = path.strip().replace("\\", "/")
    if p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        return None
    parts = [seg for seg in p.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in parts):
        return None
    return "/".join(parts)


def _abs_under(output_dir: str, rel: str) -> Optional[str]:
    """Join a validated rel path under output_dir; None if it still escapes."""
    base = os.path.realpath(output_dir)
    abs_ = os.path.realpath(os.path.join(base, rel))
    if abs_ != base and not abs_.startswith(base + os.sep):
        return None
    return abs_


def _read_json(path: str) -> Optional[Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _load_registry(output_dir: str) -> dict:
    reg = _read_json(os.path.join(output_dir, _REGISTRY_REL))
    return reg if isinstance(reg, dict) else {}


# --------------------------------------------------------------------------- #
# recall
# --------------------------------------------------------------------------- #

def recall(output_dir: str) -> dict:
    """Return the app's generation dossier as a prompt block + a compact entity
    and role summary. Wraps ``services.app_recall.assemble_recall``.
    """
    try:
        from services.app_recall import assemble_recall
        ctx = assemble_recall(output_dir)
        entities = [
            {
                "name": e.get("name"),
                "slug": e.get("slug"),
                "table": e.get("table"),
            }
            for e in (ctx.entities or [])
            if isinstance(e, dict)
        ]
        roles: list[str] = []
        for r in (ctx.roles or []):
            if isinstance(r, str):
                roles.append(r)
            elif isinstance(r, dict):
                nm = r.get("name") or r.get("id") or r.get("role")
                if nm:
                    roles.append(str(nm))
        return {
            "promptBlock": ctx.to_prompt_block(),
            "entities": entities,
            "roles": roles,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("fix_agent_tools.recall failed: %s", exc)
        return {"error": f"recall failed: {exc}"}


# --------------------------------------------------------------------------- #
# workflows
# --------------------------------------------------------------------------- #

def list_workflows(output_dir: str) -> dict:
    """List every workflow file in ``workflows/*.json`` with id + name."""
    try:
        wdir = os.path.join(output_dir, "workflows")
        if not os.path.isdir(wdir):
            return {"workflows": []}
        out: list[dict] = []
        for path in sorted(glob.glob(os.path.join(wdir, "*.json"))):
            data = _read_json(path) or {}
            rel = os.path.relpath(path, output_dir).replace(os.sep, "/")
            out.append({
                "id": data.get("id") if isinstance(data, dict) else None,
                "path": rel,
                "name": data.get("name") if isinstance(data, dict) else None,
            })
        return {"workflows": out}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"list_workflows failed: {exc}"}


def read_workflow(output_dir: str, path: str) -> dict:
    """Read a workflow JSON. Returns a compact ``{name, nodes[], edges[]}``
    view — the full node list with each node's id/type/label/config.
    """
    rel = _safe_rel(path)
    if rel is None:
        return {"error": "invalid path: must be relative to output_dir, no '..'"}
    abs_ = _abs_under(output_dir, rel)
    if abs_ is None or not os.path.isfile(abs_):
        return {"error": f"workflow not found: {rel}"}
    data = _read_json(abs_)
    if not isinstance(data, dict):
        return {"error": f"workflow not readable: {rel}"}
    defn = data.get("definition") if isinstance(data.get("definition"), dict) else {}
    nodes_out: list[dict] = []
    for n in (defn.get("nodes") or []):
        if not isinstance(n, dict):
            continue
        d = n.get("data") if isinstance(n.get("data"), dict) else {}
        nodes_out.append({
            "id": n.get("id"),
            "type": n.get("type") or d.get("nodeType"),
            "label": d.get("label"),
            "config": d.get("config") if isinstance(d.get("config"), dict) else {},
        })
    edges_out = [e for e in (defn.get("edges") or []) if isinstance(e, (dict, list))]
    return {
        "path": rel,
        "id": data.get("id"),
        "name": data.get("name"),
        "nodes": nodes_out,
        "edges": edges_out,
    }


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #

def _walk_workflow_refs(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        wf = props.get("workflowId") or props.get("workflow")
        if isinstance(wf, str) and wf:
            out.append(wf)
        # actions on buttons: props.action { workflow: "..." }
        act = props.get("action")
        if isinstance(act, dict):
            aw = act.get("workflow") or act.get("workflowId")
            if isinstance(aw, str) and aw:
                out.append(aw)
        for v in node.values():
            _walk_workflow_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_workflow_refs(v, out)


def _walk_field_defs(node: Any, out: list[dict]) -> None:
    if isinstance(node, dict):
        t = str(node.get("type") or "").lower()
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        name = props.get("name") or node.get("name")
        # Anything that looks like a form field control
        if name and t in {
            "input", "select", "textarea", "checkbox", "radio", "datepicker",
            "datetimepicker", "timepicker", "combobox", "fileupload", "field",
            "numberinput", "textfield", "keyvalueinput",
        }:
            out.append({"name": name, "type": t or "field"})
        for v in node.values():
            _walk_field_defs(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_field_defs(v, out)


def read_page(output_dir: str, path: str) -> dict:
    """Read a page schema JSON. Returns route + referenced workflow ids + a flat
    list of the form fields the page defines.
    """
    rel = _safe_rel(path)
    if rel is None:
        return {"error": "invalid path: must be relative to output_dir, no '..'"}
    abs_ = _abs_under(output_dir, rel)
    if abs_ is None or not os.path.isfile(abs_):
        return {"error": f"page not found: {rel}"}
    data = _read_json(abs_)
    if not isinstance(data, dict):
        return {"error": f"page not readable: {rel}"}
    refs: list[str] = []
    _walk_workflow_refs(data, refs)
    # dedupe while preserving order
    seen: set[str] = set()
    wf_refs: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            wf_refs.append(r)
    fields: list[dict] = []
    _walk_field_defs(data, fields)
    return {
        "path": rel,
        "route": data.get("route"),
        "workflowRefs": wf_refs,
        "fields": fields,
    }


# --------------------------------------------------------------------------- #
# registry / columns
# --------------------------------------------------------------------------- #

def read_column(output_dir: str, entity: str, column: str) -> dict:
    """Return the column's SQL type, notNull, and fk target (if any). Uses
    ``services.fk_semantics._columns_for`` for identical name matching to the
    rest of the pipeline."""
    if not isinstance(entity, str) or not isinstance(column, str):
        return {"error": "entity and column are required strings"}
    try:
        from services.fk_semantics import _columns_for, _resolve_entity
    except Exception as exc:  # noqa: BLE001
        return {"error": f"fk_semantics unavailable: {exc}"}
    reg = _load_registry(output_dir)
    if not reg:
        return {"error": "resource registry not found"}
    ent, key = _resolve_entity(reg.get("entities") or {}, entity)
    if not isinstance(ent, dict):
        return {"error": f"unknown entity: {entity}"}
    for col in _columns_for(ent, reg, key):
        if not isinstance(col, dict):
            continue
        if str(col.get("name")) == column:
            return {
                "type": col.get("type"),
                "notNull": bool(col.get("notNull")),
                "fk": col.get("fk"),
                "primaryKey": bool(col.get("primaryKey")),
            }
    return {"error": f"unknown column: {entity}.{column}"}


# --------------------------------------------------------------------------- #
# analyzers
# --------------------------------------------------------------------------- #

def analyze_workflow_values_tool(output_dir: str, path: str) -> dict:
    """Value↔column type check for a workflow (wraps
    ``services.workflow_value_types.analyze_workflow_file``). Returns the list
    of findings; empty list = clean."""
    rel = _safe_rel(path)
    if rel is None:
        return {"error": "invalid path: must be relative to output_dir, no '..'"}
    abs_ = _abs_under(output_dir, rel)
    if abs_ is None or not os.path.isfile(abs_):
        return {"error": f"workflow not found: {rel}"}
    reg_abs = os.path.join(output_dir, _REGISTRY_REL)
    if not os.path.isfile(reg_abs):
        return {"error": "resource registry not found"}
    try:
        from services.workflow_value_types import analyze_workflow_file
        findings = analyze_workflow_file(abs_, reg_abs)
        return {"findings": findings or []}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"analyze failed: {exc}"}


def parse_error_tool(text: str) -> dict:
    """Extract workflow/table/column/component out of a raw error string. Wraps
    ``agents.fix_diagnoser.parse_error``. Returns ``{}`` when nothing parses."""
    if not isinstance(text, str):
        return {"error": "text must be a string"}
    try:
        from agents.fix_diagnoser import parse_error
        parsed = parse_error(text)
        return parsed or {}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"parse_error failed: {exc}"}


# --------------------------------------------------------------------------- #
# probes
# --------------------------------------------------------------------------- #

def probe_logs_tool(output_dir: str, lines: int = 200) -> dict:
    """Read the tail of the app's server log (read-only, bounded)."""
    try:
        from services.fix_probe import probe
        try:
            n = int(lines)
        except (TypeError, ValueError):
            n = 200
        n = max(1, min(n, 1000))
        res = probe(output_dir, {"kind": "logs"}, max_lines=n)
        return {
            "available": bool(res.get("available")),
            "evidence": res.get("evidence"),
            "reason": res.get("reason"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "evidence": None, "reason": f"probe failed: {exc}"}


def probe_endpoint_tool(output_dir: str, url: str) -> dict:
    """Bounded, localhost-only GET (the fix_probe module enforces the localhost
    check). Returns the same ``{available, evidence, reason}`` shape."""
    if not isinstance(url, str) or not url:
        return {"available": False, "evidence": None, "reason": "url required"}
    try:
        from services.fix_probe import probe
        res = probe(output_dir, {"kind": "read_endpoint", "url": url})
        return {
            "available": bool(res.get("available")),
            "evidence": res.get("evidence"),
            "reason": res.get("reason"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "evidence": None, "reason": f"probe failed: {exc}"}


# --------------------------------------------------------------------------- #
# palette catalog — used by the agent to render the prompt.
# --------------------------------------------------------------------------- #

TOOL_CATALOG: list[dict] = [
    {"name": "recall", "signature": "recall() -> {promptBlock, entities, roles}",
     "desc": "Why the app is the way it is: intent, entities, roles, history."},
    {"name": "list_workflows", "signature": "list_workflows() -> {workflows:[{id,path,name}]}",
     "desc": "Enumerate every workflow file (path relative to output_dir)."},
    {"name": "read_workflow", "signature": "read_workflow(path) -> {name, nodes:[{id,type,label,config}], edges}",
     "desc": "Load a workflow definition; inspect its mutation nodes and their config.values."},
    {"name": "read_page", "signature": "read_page(path) -> {route, workflowRefs:[...], fields:[{name,type}]}",
     "desc": "Load a page/form schema; see which workflows its buttons trigger and its field controls."},
    {"name": "read_column", "signature": "read_column(entity, column) -> {type, notNull, fk}",
     "desc": "SQL type + FK target of a column from the resource registry."},
    {"name": "analyze_workflow_values", "signature": "analyze_workflow_values(path) -> {findings:[{node,column,valueKind,columnType,reason}]}",
     "desc": "Type-check a workflow's db_insert/db_update value bindings against the columns' real SQL types."},
    {"name": "parse_error", "signature": "parse_error(text) -> {kind, workflow?, table?, column?, componentPath?, rawType?}",
     "desc": "Extract structured locators from a pasted Postgres/workflow/JS-stack error string."},
    {"name": "probe_logs", "signature": "probe_logs(lines=200) -> {available, evidence, reason?}",
     "desc": "Read the tail of the app's server log if one exists (read-only)."},
    {"name": "probe_endpoint", "signature": "probe_endpoint(url) -> {available, evidence, reason?}",
     "desc": "Bounded GET to a localhost URL (only localhost is allowed)."},
    {"name": "propose_fix", "signature": "propose_fix(diagnosis) -> terminates the loop",
     "desc": "TERMINAL. Present a structured Diagnosis (see contract) for the user to approve via [APPLY_FIX]."},
    {"name": "ask_user", "signature": "ask_user(question) -> terminates the loop",
     "desc": "TERMINAL. Ask ONE focused clarifying question when you cannot localize with confidence."},
]

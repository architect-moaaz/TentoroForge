"""Derive a workflow's declared process variables.

Process variables are the workflow's mutable scratchpad — distinct from
trigger inputs (immutable) and per-step outputs (scoped). Historically they
were dropped by every generator except the CRUD emitter, so the runtime saw
none and the editor picker showed none. This module recovers them from three
sources, merging in this order (later wins is *not* used — first wins so the
planner keeps authority):

  1. Whatever the planner authored on the workflow (`wf.processVariables`).
  2. Any `set_variable` node's `variableName` (the workflow itself declared it).
  3. Any node output that a user promoted via `outputMappings[i].processVar`.
  4. Any `{{ref}}` root in a node config with no provider — for manual /
     button / form / api-dispatched workflows these are launcher-supplied
     inputs (the runtime lands the dispatch payload in ctx.variables), so
     they belong in the declaration. Schedule triggers carry no payload,
     so their free refs stay undeclared for the validator to flag.

Each entry is normalized to ``{name, type, required?, description?, source?}``.
`source` is a debug breadcrumb ("planner", "set_variable:<nodeId>",
"output:<nodeId>.<name>") kept off the wire when writing back — the runtime
only reads `name` and `type`.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Iterator


def derive_process_variables(wf: dict, nodes: Iterable[dict] | None = None) -> list[dict]:
    """Return the merged process-variable list for ``wf``.

    ``wf`` is the planner workflow dict (may have ``processVariables``).
    ``nodes`` is the engine node list (each ``{id, type, data: {config: {...}}}``).
    Both are read defensively — missing keys/types just skip that source.

    Order: planner-authored → set_variable-node-derived → output-mapping-derived.
    Later entries with a name that already exists are dropped, so the planner's
    type/description wins over anything inferred.
    """
    seen: dict[str, dict] = {}

    for entry in _iter_planner(wf):
        if entry["name"] not in seen:
            seen[entry["name"]] = entry

    node_list = [n for n in (nodes or []) if isinstance(n, dict)]
    if node_list:
        for entry in _iter_set_variable_nodes(node_list):
            if entry["name"] not in seen:
                seen[entry["name"]] = entry
        for entry in _iter_output_promotions(node_list):
            if entry["name"] not in seen:
                seen[entry["name"]] = entry
        for entry in _iter_free_refs(wf, node_list, set(seen)):
            if entry["name"] not in seen:
                seen[entry["name"]] = entry

    return list(seen.values())


# ---------------------------------------------------------------------------
# Source 1: planner-authored
# ---------------------------------------------------------------------------

def _iter_planner(wf: dict) -> list[dict]:
    raw = wf.get("processVariables") if isinstance(wf, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        entry: dict[str, Any] = {"name": name, "type": _norm_type(item.get("type"))}
        if item.get("required") is True:
            entry["required"] = True
        desc = item.get("description")
        if isinstance(desc, str) and desc.strip():
            entry["description"] = desc.strip()
        entry["source"] = "planner"
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Source 2: set_variable nodes
# ---------------------------------------------------------------------------

def _iter_set_variable_nodes(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        cfg = _config(n)
        if cfg.get("actionType") != "set_variable":
            continue
        name = str(cfg.get("variableName") or "").strip()
        if not name:
            continue
        # variableValue OR value — the runtime accepts both.
        val = cfg.get("variableValue", cfg.get("value"))
        out.append({
            "name": name,
            "type": _infer_type_from_value(val),
            "source": f"set_variable:{n.get('id') or ''}",
        })
    return out


# ---------------------------------------------------------------------------
# Source 3: outputMappings with a non-empty processVar
# ---------------------------------------------------------------------------

def _iter_output_promotions(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        cfg = _config(n)
        mappings = cfg.get("outputMappings")
        if not isinstance(mappings, list):
            continue
        for m in mappings:
            if not isinstance(m, dict):
                continue
            promoted = str(m.get("processVar") or "").strip()
            if not promoted:
                continue
            out.append({
                "name": promoted,
                "type": "any",
                "source": f"output:{n.get('id') or ''}.{m.get('output') or ''}",
            })
    return out


# ---------------------------------------------------------------------------
# Source 4: {{ref}} roots with no provider (launcher-supplied inputs)
# ---------------------------------------------------------------------------

_REF_ROOT_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)")

# The roots the workflow validator treats as always-provided; a free ref
# harvested here would double-declare them.
_BUILTIN_ROOTS = {"trigger", "input", "event", "context", "process",
                  "processVariables", "id"}

# Config keys under which a node PRODUCES a variable — mirrors the
# validator's _declared_names so harvest and validation can't disagree.
_OUTPUT_KEYS = ("variableName", "outputVariable", "outputVar", "resultVar",
                "resultVariable", "assignTo")


def _is_schedule_trigger(wf: dict) -> bool:
    t = wf.get("trigger")
    if isinstance(t, dict):
        t = t.get("type")
    return str(t or "").strip().lower().startswith(("schedule", "cron", "timer"))


def _provided_roots(nodes: list[dict]) -> set[str]:
    provided: set[str] = set(_BUILTIN_ROOTS)
    for n in nodes:
        nid = n.get("id")
        if nid:
            provided.add(str(nid))
        cfg = _config(n)
        for key in _OUTPUT_KEYS:
            v = cfg.get(key)
            if isinstance(v, str) and v:
                provided.add(v)
        fields = cfg.get("aiExtractFields")
        if isinstance(fields, list):
            for f in fields:
                if isinstance(f, str) and f:
                    provided.add(f)
                elif isinstance(f, dict) and isinstance(f.get("name"), str):
                    provided.add(f["name"])
        params = cfg.get("outputParams")
        if isinstance(params, list):
            for p in params:
                if isinstance(p, dict):
                    nm = p.get("name") or p.get("target")
                    if isinstance(nm, str) and nm:
                        provided.add(nm)
    return provided


def _walk_strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def _infer_type_from_name(name: str) -> str:
    if name == "id" or name.endswith("Id") or name.endswith("_id"):
        return "uuid"
    if name.endswith("At") or name.endswith("_at") or \
            name.lower().endswith("date"):
        return "date"
    for prefix in ("is", "has", "can"):
        if name.startswith(prefix) and name[len(prefix):len(prefix) + 1].isupper():
            return "boolean"
    if name.lower().endswith(("count", "amount", "qty", "quantity", "position")):
        return "number"
    return "string"


def _iter_free_refs(wf: dict, nodes: list[dict],
                    already_declared: set[str]) -> list[dict]:
    """Source 4 — see module docstring. Skips schedule-style triggers:
    they carry no dispatch payload, so an unprovided ref there is a real
    defect the validator must keep flagging."""
    if not isinstance(wf, dict) or _is_schedule_trigger(wf):
        return []
    provided = _provided_roots(nodes) | already_declared
    out: list[dict] = []
    emitted: set[str] = set()
    for n in nodes:
        for val in _walk_strings(_config(n)):
            for root in _REF_ROOT_RE.findall(val):
                if root in provided or root in emitted:
                    continue
                emitted.add(root)
                out.append({
                    "name": root,
                    "type": _infer_type_from_name(root),
                    "source": f"ref:{n.get('id') or ''}",
                })
    return out


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _config(node: dict) -> dict:
    """Return the config dict of a runtime node, tolerating both node shapes.

    Engine nodes carry it at ``data.config``; some fixtures pass the raw
    config dict itself. Anything else → empty dict.
    """
    data = node.get("data")
    if isinstance(data, dict):
        cfg = data.get("config")
        if isinstance(cfg, dict):
            return cfg
    cfg = node.get("config")
    if isinstance(cfg, dict):
        return cfg
    return {}


_ALLOWED_TYPES = {"string", "number", "boolean", "object", "array", "date", "uuid", "any"}


def _norm_type(t: Any) -> str:
    if isinstance(t, str) and t.strip().lower() in _ALLOWED_TYPES:
        return t.strip().lower()
    return "string"


def _infer_type_from_value(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if v is None:
        return "any"
    # A string that looks like a `{{binding}}` — we don't know the runtime
    # value's type, so leave it opaque.
    return "string"


def strip_source(entries: list[dict]) -> list[dict]:
    """Return a copy without the ``source`` breadcrumb (for on-disk write)."""
    out: list[dict] = []
    for e in entries:
        out.append({k: v for k, v in e.items() if k != "source"})
    return out

"""The application as an MCP server: the tools it offers, written from its definition.

An assistant such as Claude can use an application the way a person does —
run its processes and read its records — when the application speaks MCP.
None of that is written by an agent. The protocol, the sign-in and the
dispatch are the platform's (`templates/app-foundation/src/lib/mcp`,
`src/app/api/mcp`); what an application adds is its TOOLS, and those are
already in the Blueprint:

* each workflow a person starts — its name, its purpose, the inputs it
  declares (typed the way the SDK types them) and the roles whose pages
  launch it (`launch_roles`, the gate the run route applies);
* each record type — find (search, filters, page) and get (by id), with the
  roles that may read it (`entity_access`, the gate the data route applies).

So this is a projection, beside `launch-roles.ts` and `entity-access.ts`,
and it moves with them: a workflow Smith adds is a tool on the next sync.
The catalogue only SAYS who may use a tool; the routes a tool calls decide,
as the person, exactly as they do for a button.

Whether the server answers at all is the owner's switch (`app_settings`),
read by the app from `FORGE_APP_MCP`; the catalogue is written either way.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CATALOG = "src/lib/mcp/catalog.json"
#: Triggers a person starts. A schedule, a record change or another system's
#: call is not something an assistant runs on someone's behalf.
STARTED_BY_A_PERSON = frozenset({"", "manual", "api_event"})
#: Fields a record tool lists per type — enough to know what to filter on.
MAX_FIELDS = 40


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def _snake(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(text or "").lower())).strip("_") or "tool"


def _unique(name: str, taken: set[str]) -> str:
    out, n = name[:56], 2
    while out in taken:
        out, n = f"{name[:52]}_{n}", n + 1
    taken.add(out)
    return out


def _schema_of(ts: str, description: str) -> dict:
    """A JSON Schema for one input, from the SDK's TypeScript type for it."""
    ts = ts.strip()
    out: dict[str, Any]
    if ts == "number":
        out = {"type": "number"}
    elif ts == "boolean":
        out = {"type": "boolean"}
    elif ts.endswith("[]"):
        out = {"type": "array", "items": {"type": "string"}}
    elif ts.startswith('"'):
        out = {"type": "string", "enum": [json.loads(p.strip()) for p in ts.split("|")]}
    elif ts.startswith("{"):
        out = {"type": "object"}
    elif ts == "unknown":
        out = {}
    else:
        out = {"type": "string"}
    if description:
        out["description"] = description[:300]
    return out


def workflow_tools(doc: dict, taken: set[str]) -> list[dict]:
    from services.blueprint.app_sdk import input_type
    from services.blueprint.projection import launch_roles

    roles = launch_roles(doc)
    entities = _live((doc.get("data") or {}).get("entities"))
    out: list[dict] = []
    for w in _live(doc.get("workflows")):
        kind = str(((w.get("trigger") or {}) if isinstance(w.get("trigger"), dict) else {}).get("kind") or "")
        if kind not in STARTED_BY_A_PERSON:
            continue
        props: dict[str, Any] = {}
        required: list[str] = []
        for inp in w.get("inputs") or []:
            if not isinstance(inp, dict) or not inp.get("name"):
                continue
            name = str(inp["name"])
            what = str(inp.get("description") or "").strip()
            if inp.get("kind") == "record":
                target = next((e for e in entities if str(e.get("id")) == str(inp.get("entity"))
                               or str(e.get("name")) == str(inp.get("entity"))), None)
                what = (f"id of the {target.get('name')} record" if target else "a record id") \
                    + (f" — {what}" if what else "")
            props[name] = _schema_of(input_type(doc, w, inp), what)
            if inp.get("required", True):
                required.append(name)
        purpose = " ".join(str(w.get("purpose") or w.get("description") or "").split())
        out.append({
            "tool": _unique(_snake(w.get("name") or w.get("id")), taken),
            "id": str(w.get("id")),
            "name": str(w.get("name") or w.get("id")),
            "description": (f"{w.get('name')}: {purpose}" if purpose else str(w.get("name") or ""))[:600],
            "roles": roles.get(str(w.get("id"))),
            "inputSchema": {"type": "object", "properties": props, "required": required},
        })
    return out


def record_tools(doc: dict, taken: set[str]) -> list[dict]:
    from services.blueprint.app_sdk import entity_columns
    from services.blueprint.projection import entity_access

    access = entity_access(doc)
    out: list[dict] = []
    for e in _live((doc.get("data") or {}).get("entities")):
        slug = str(e.get("table") or str(e.get("name") or "").lower())
        if not slug:
            continue
        fields = [{"name": str(f.get("name")), "type": str(f.get("type") or "string")}
                  for f in entity_columns(e, doc)][:MAX_FIELDS]
        readers = access.get(slug, {}).get("read") if slug in access else None
        base = _snake(slug)
        out.append({
            "slug": slug,
            "name": str(e.get("name") or slug),
            "description": " ".join(str(e.get("description") or "").split())[:300],
            "find": _unique(f"find_{base}", taken),
            "get": _unique(f"get_{base}", taken),
            "fields": fields,
            "roles": readers,
        })
    return out


def catalog(doc: dict) -> dict:
    taken: set[str] = set()
    app = doc.get("application") or {}
    return {"app": str(app.get("name") or "Application"),
            "about": " ".join(str(app.get("description") or "").split())[:500],
            "workflows": workflow_tools(doc, taken),
            "records": record_tools(doc, taken)}


def project_app_mcp(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/mcp/catalog.json`` — the tools the app's MCP server offers."""
    data = catalog(doc)
    path = Path(app_root) / CATALOG
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, sort_keys=True) + "\n"
    try:
        if path.read_text("utf-8") == text:
            return {"files": [CATALOG], "tools": _count(data)}
    except OSError:
        pass
    path.write_text(text, "utf-8")
    return {"files": [CATALOG], "tools": _count(data)}


def _count(data: dict) -> int:
    return len(data["workflows"]) + 2 * len(data["records"])


__all__ = ["CATALOG", "catalog", "project_app_mcp", "record_tools", "workflow_tools"]

"""Suggest an agent for an app, from the app's own Blueprint.

THE PROBLEM THIS REMOVES. The Agent Builder started from generic templates ("Customer
Support Bot": a Knowledge Base tool that connects to nothing). Making an agent that does
something in a real app meant drawing it by hand and knowing which tables the app lets a
person write, which workflows exist and what rules they carry. Movie Review's hand-drawn
agent offered "create a rating" as a direct write; the app lets nobody do that (a workflow
does, with the rules), so every attempt was a 403.

THE RULE. The Blueprint already says what the app can do. This reads it and draws the agent
from it, with plain rules and no model, so the same app always gives the same agent:

* one tool to list and one to get each readable entity (never one nobody may read: `users`);
* WORKFLOW FIRST for writes. A table some workflow writes is written through that workflow
  (it carries the rules: stars 1-5, one comment each, admin-only). A direct create/update tool
  appears only for a writable table no workflow writes. Never a delete tool.
* each user-launched workflow becomes an action tool whose inputs are the workflow's own;
* a prompt built from the app's name, purpose and business rules, that makes the agent
  confirm before it changes anything and explain a refusal in plain words;
* safety rules and conversation memory. No router or handoff box: neither runs yet, and a
  box that does nothing is a promise nothing keeps.

One agent per app. It acts as the signed-in person, so an action only an Admin may do is
refused for a Reviewer by the app itself, and the prompt tells it to say so.
"""
from __future__ import annotations

import re
from typing import Any

AGENT_ID = "app_assistant"
_WRITE_ACTIONS = {"db_insert": "create", "db_update": "update", "db_delete": "delete"}
_HIDDEN_FIELD_TYPES = {"vector", "image", "file", "password", "secret"}
_HIDDEN_FIELD_RX = re.compile(r"password|passwd|secret|token|hash|salt|api_?key", re.I)
_TYPE = {"integer": "integer", "int": "integer", "number": "number", "decimal": "number",
         "float": "number", "boolean": "boolean", "bool": "boolean"}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _live(items: Any) -> list[dict[str, Any]]:
    return [i for i in (items or []) if isinstance(i, dict) and i.get("status") != "DEPRECATED"]


def _snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name or "")).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _singular(word: str) -> str:
    w = word
    if w.endswith("ies"):
        return w[:-3] + "y"
    if re.search(r"(sses|xes|zes|ches|shes)$", w):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _node(nid: str, kind: str, label: str, x: int, y: int, config: dict[str, Any]) -> dict[str, Any]:
    return {"id": nid, "type": kind, "position": {"x": x, "y": y},
            "data": {"label": label, "nodeType": kind, "config": config}}


def _sentences(text: str, limit: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    return " ".join(parts[:limit]).strip()


def _fields_note(entity: dict[str, Any], by_id: dict[str, dict[str, Any]], rels: list[dict[str, Any]]) -> str:
    """'title, synopsis, releaseYear …; movieId is the id of a movie' — what the model may ask for."""
    names = []
    for f in entity.get("fields") or []:
        if str(f.get("type") or "").lower() in _HIDDEN_FIELD_TYPES or _HIDDEN_FIELD_RX.search(str(f.get("name"))):
            continue
        names.append(str(f.get("name")))
    pointers = []
    for r in rels:
        if r.get("from") == entity.get("id") and r.get("fromField") and by_id.get(r.get("to")):
            target = str(by_id[r["to"]].get("name")).lower()
            # "an order", but "a user" (a leading u that sounds like "you")
            article = "an" if target[:1] in "aeio" or (target[:1] == "u" and not target.startswith(("us", "uni", "uti"))) else "a"
            # The data engine puts the referenced record's name beside every id, as `<id field>Label`.
            pointers.append(f"{r['fromField']} is the id of {article} {target} (its name comes back as {r['fromField']}Label)")
    note = "Fields: " + ", ".join(names) + "." if names else ""
    return (note + (" " + "; ".join(pointers) + "." if pointers else "")).strip()


def _workflow_writes(workflow: dict[str, Any]) -> dict[str, set[str]]:
    """``{table: {create|update|delete}}`` the workflow's steps perform."""
    out: dict[str, set[str]] = {}
    for step in workflow.get("steps") or []:
        cfg = (step or {}).get("config") or {}
        op, table = _WRITE_ACTIONS.get(str(cfg.get("actionType"))), cfg.get("table")
        if op and isinstance(table, str):
            out.setdefault(table.lower(), set()).add(op)
    return out


def _params(workflow: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    params: list[dict[str, Any]] = []
    for i in workflow.get("inputs") or []:
        if not isinstance(i, dict) or not i.get("name"):
            continue
        required = bool(i.get("required"))
        kind = str(i.get("kind") or "field")
        if kind == "record":
            table = str((by_id.get(i.get("entity")) or {}).get("name") or i["name"]).lower()
            params.append({"name": i["name"], "type": "object", "required": required,
                           "description": f'The {table}, as {{"id": "<its id>"}}. Look the id up first with a list tool.'})
            continue
        ftype = str(i.get("type") or "string").lower()
        if ftype in _HIDDEN_FIELD_TYPES:
            continue  # a file or image the agent cannot supply; the workflow takes it as optional
        params.append({"name": i["name"], "type": _TYPE.get(ftype, "string"), "required": required,
                       "description": str(i.get("description") or "")})
    return params


# ---------------------------------------------------------------------------
# the suggestion
# ---------------------------------------------------------------------------

def suggest_agent(doc: dict[str, Any]) -> dict[str, Any]:
    """The agent definition (builder graph) for the app a Blueprint describes. Not saved."""
    from services.blueprint.projection import _workflow_slug, entity_access

    app = doc.get("application") or {}
    app_name = str(app.get("name") or "this app").strip()
    entities = [e for e in _live((doc.get("data") or {}).get("entities")) if e.get("id")]
    by_id = {e["id"]: e for e in entities}
    rels = _live((doc.get("data") or {}).get("relationships"))
    access = entity_access(doc)
    workflows = [w for w in _live(doc.get("workflows"))
                 if str((w.get("trigger") or {}).get("kind") or "manual") == "manual"]

    # which tables some workflow writes: those are written through the workflow only
    written_by: dict[str, list[dict[str, Any]]] = {}
    for w in workflows:
        for table in _workflow_writes(w):
            written_by.setdefault(table, []).append(w)

    tools: list[dict[str, Any]] = []
    taken: set[str] = set()

    def add(name: str, cfg: dict[str, Any]) -> None:
        base, n = name, 2
        while name in taken:
            name, n = f"{base}_{n}", n + 1
        taken.add(name)
        tools.append(_node(f"tool_{name}", "tool", name.replace("_", " ").capitalize(), 420, 0,
                           {"tool_name": name, **cfg}))

    for e in entities:
        table = str(e.get("table") or _snake(str(e.get("name"))) + "s").lower()
        rule = access.get(table) or {}
        if not rule.get("read"):
            continue  # nobody reads it through the data API (users): the agent never offers it
        single, plural = _snake(str(e.get("name") or "")) or _singular(table), table
        note = _fields_note(e, by_id, rels)
        label = str(e.get("name") or single)
        add(f"list_{plural}", {"tool_type": "data_engine", "entity": plural, "operation": "list",
                               "description": f"List or search {label} records. {note}".strip()})
        add(f"get_{single}", {"tool_type": "data_engine", "entity": plural, "operation": "get",
                              "description": f"Get one {label} record by its id. {note}".strip()})
        if rule.get("write") and table not in written_by:
            add(f"add_{single}", {"tool_type": "data_engine", "entity": plural, "operation": "create",
                                  "description": f"Create a {label} record. {note}".strip()})
            add(f"update_{single}", {"tool_type": "data_engine", "entity": plural, "operation": "update",
                                     "description": f"Change a {label} record by id. {note}".strip()})

    rules = _live(doc.get("businessRules"))
    for w in workflows:
        wid_ref = w.get("id")
        written_ids = {eid for eid, e in by_id.items()
                       if str(e.get("table") or "").lower() in _workflow_writes(w)}
        applying = [r for r in rules
                    if wid_ref in (r.get("appliesTo") or []) or written_ids & set(r.get("appliesTo") or [])]
        why = " ".join(str(r.get("statement") or "").strip() for r in applying if r.get("statement"))
        desc = _sentences(w.get("purpose"), 3) or str(w.get("name"))
        if why:
            desc = f"{desc} Rules the app enforces: {why}"
        add(_snake(str(w.get("name"))), {"tool_type": "workflow", "workflow_id": _workflow_slug(w),
                                         "description": desc, "parameters": _params(w, by_id)})

    # ---- the prompt ------------------------------------------------------
    objectives = [str(o) for o in ((doc.get("product") or {}).get("objectives") or [])]
    roles = [r for r in _live(doc.get("roles")) if r.get("name")]
    lines = [f"You are the assistant for {app_name}."]
    about = re.split(r"\b(?:Design direction|Interface language)\b", str(app.get("description") or ""))[0]
    if about.strip():
        lines.append(_sentences(about, 4))
    if objectives:
        lines += ["", "What people use this app for:", *[f"- {o}" for o in objectives]]
    lines += [
        "", "How you work:",
        "- Use your tools for every fact about this app's records. Never invent a record or a number.",
        "- Use the id of a record you already have from earlier in this conversation. Look a record up with a list "
        "tool only when you do not have its id, or when it may have changed since you last saw it.",
        "- Before anything that creates or changes something, say exactly what you are about to do and wait "
        "for a clear yes. Be extra careful when the app says it cannot be undone.",
        "- You act as the person who is signed in, so you can only do what they are allowed to do. If an action "
        "is refused, say why in plain words and do not try again.",
        "- Keep answers short. Use a short list for several records, one line each.",
        "- Refer to people and records by name, never by id. Results carry the name beside each id, in a field "
        "ending in Label (customerIdLabel, for example); show an id only if the person asks for it.",
        "- You cannot transfer anyone to a person; if asked, say so and suggest contacting the app's administrator.",
    ]
    if rules:
        lines += ["", "Rules of this app (the app enforces them; explain them if you are asked or refused):",
                  *[f"- {str(r.get('statement') or r.get('name')).strip()}" for r in rules]]
    if len(roles) > 1:
        lines += ["", "Who can do what:", *[f"- {r['name']}: {_sentences(r.get('description'), 1)}".rstrip(": ")
                                            for r in roles]]
    prompt = "\n".join(lines)

    # ---- the graph -------------------------------------------------------
    for i, t in enumerate(tools):
        t["position"] = {"x": 420, "y": i * 110}
    sp = _node("sp_1", "system_prompt", f"{app_name} assistant", 40, max(0, len(tools) * 55 - 60),
               {"is_entry_point": True, "prompt": prompt})
    guard = _node("guard_1", "guardrail", "Input and output safety", 800, 40, {
        "guardrail_type": "both",
        "rules": [{"id": "r1", "name": "No prompt attacks", "type": "block_topics",
                   "expression": "ignore previous instructions, reveal your system prompt, jailbreak"},
                  {"id": "r2", "name": "No personal data out", "type": "pii_redaction"}]})
    memory = _node("mem_1", "memory", "Conversation memory", 800, 240,
                   {"memory_type": "conversation", "capacity": 20})
    nodes = [sp, *tools, guard, memory]
    edges = [{"id": f"e_sp_1_{n['id']}", "source": "sp_1", "target": n["id"], "data": {"edgeType": "default"}}
             for n in nodes[1:]]
    return {
        "id": AGENT_ID,
        "name": f"{app_name} Assistant",
        "description": f"Answers questions about {app_name} and does what its workflows allow, as the signed-in person.",
        "nodes": nodes, "edges": edges, "config": {"max_turns": 8},
    }

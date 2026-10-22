"""The guided parts of a phone screen: a form that runs a workflow, a button that runs one, and a list of records.

On the website these are the palette entries that ask a question first. Here they are the same three, against the phone kit's own
`WorkflowForm`, `WorkflowButton` and `ListView`. What they connect to is what the Blueprint declares: a workflow is `workflows.<key>`
(a change to data is always a workflow, run on the server), a list is `useList("<Entity>")` (a read).

The code is built HERE, from the Blueprint, never from text the browser sends: the browser names a workflow or an entity and a few
words to show, and the server checks the names against the Blueprint and writes the code. Words are written as quoted strings, so
nothing typed can become code. The result is not trusted: it goes through the phone's compiler like any change that is not a
palette part, so a form that leaves a required input out is refused with the reason.
"""
from __future__ import annotations

import json
import re
from typing import Any

from services.react_editor.phone_palette import CONTAINERS


class GuideError(ValueError):
    """The guided part cannot be built as asked; the message says why, in words a person reads."""


# ---------------------------------------------------------------------------
# What the dialogs may choose from
# ---------------------------------------------------------------------------

def refs(doc: dict) -> dict[str, Any]:
    """The workflows and the kinds of record this application has, as the dialogs list them."""
    from services.react_editor.service import _entity_refs, _workflow_refs
    workflows = [{"id": w["id"], "key": w["key"], "name": w["name"], "description": w["description"], "inputs": w["inputs"]}
                 for w in _workflow_refs(doc) if w.get("key")]
    entities = [{"name": e["name"], "typeName": e["typeName"], "fields": e["fields"]} for e in _entity_refs(doc)]
    return {"workflows": workflows, "entities": entities}


# ---------------------------------------------------------------------------
# The code
# ---------------------------------------------------------------------------

def _q(text: Any) -> str:
    """A string as a quoted literal: what was typed is a value, never code."""
    return json.dumps(str(text), ensure_ascii=False)


def _human(name: str) -> str:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ").replace("-", " ")
    return " ".join(w[:1].upper() + w[1:] for w in spaced.split())


def _kind(inp: dict) -> str:
    """How a form collects one workflow input: the website's own rules, in the phone kit's words."""
    t = str(inp.get("type") or "").lower()
    if inp.get("options"):
        return "select"
    if t != "text" and "text" in t and "string" not in t:
        return "textarea"
    if t == "email":
        return "email"
    if t in ("date", "time"):
        return t
    if t in ("timestamp", "datetime"):
        return "datetime"
    if t in ("boolean", "bool"):
        return "checkbox"
    if t == "money":
        return "money"
    if t in ("number", "integer", "int", "decimal", "float"):
        return "number"
    return "text"


def _is_record(inp: dict) -> bool:
    return inp.get("kind") == "record"


def form_jsx(wf: dict, row_var: str | None) -> str:
    """`<WorkflowForm …>` with one entry per input. A record the form is about is the row's, when the form sits in a list row."""
    lines: list[str] = []
    for inp in wf["inputs"]:
        name = str(inp["name"])
        if _is_record(inp) and row_var:
            lines.append(f"    {name}: {{ value: {row_var}.id }},")
            continue
        label = _human(name) + ("" if inp.get("required", True) else " (optional)")
        parts = [f"label: {_q(label)}"]
        kind = _kind(inp)
        if kind != "text":
            parts.append(f"kind: {_q(kind)}")
        if kind == "select":
            parts.append("options: [" + ", ".join(f"{{ label: {_q(o)}, value: {_q(o)} }}" for o in inp["options"]) + "]")
        if inp.get("description"):
            parts.append(f"help: {_q(inp['description'])}")
        lines.append(f"    {name}: {{ {', '.join(parts)} }},")
    fields = "\n".join(lines)
    return "\n".join([
        "<WorkflowForm", f"  workflow={{workflows.{wf['key']}}}", "  fields={{", *([fields] if fields else []), "  }}",
        '  submitLabel="Save"', f"  successMessage={_q(wf['name'] + ' — done.')}", "/>",
    ])


def _literal(inp: dict, given: Any) -> str:
    t = str(inp.get("type") or "").lower()
    text = "" if given is None else str(given).strip()
    if t in ("number", "integer", "int", "decimal", "float", "money"):
        try:
            return repr(float(text)) if "." in text else str(int(text))
        except ValueError:
            raise GuideError(f"“{_human(inp['name'])}” needs a number.") from None
    if t in ("boolean", "bool"):
        return "true" if text.lower() in ("true", "yes", "1", "on") else "false"
    return _q(text)


def button_jsx(wf: dict, label: str, values: dict[str, Any], row_var: str | None) -> str:
    """`<WorkflowButton …>` with what it sends. Every required input is given: a fixed word, or the row's record."""
    sent: list[str] = []
    for inp in wf["inputs"]:
        if not inp.get("required", True):
            continue
        name = str(inp["name"])
        if _is_record(inp):
            if not row_var:
                raise GuideError(f"“{wf['name']}” acts on one {inp.get('entity') or 'record'}, so the button has to sit in a row of a list "
                                 f"of them. Drop it inside a box or a row that is part of a list item.")
            sent.append(f"{name}: {row_var}.id")
        else:
            sent.append(f"{name}: {_literal(inp, values.get(name))}")
    return f"<WorkflowButton workflow={{workflows.{wf['key']}}} input={{{{ {', '.join(sent)} }}}}>{{{_q(label)}}}</WorkflowButton>"


def _lower_first(name: str) -> str:
    return name[:1].lower() + name[1:]


def unique(name: str, source: str) -> str:
    """A name the screen does not use yet."""
    taken = set(re.findall(r"[A-Za-z_$][\w$]*", source))
    if name not in taken:
        return name
    n = 2
    while f"{name}{n}" in taken:
        n += 1
    return f"{name}{n}"


def list_parts(entity: dict, title: str, subtitle: str | None, source: str) -> tuple[str, str]:
    """`(the statement that reads the records, the list that shows them)`."""
    names = {f["name"] for f in entity["fields"]}
    for field in (title, subtitle):
        if field and field not in names:
            raise GuideError(f"{entity['name']} has no “{field}”.")
    var = unique(_lower_first(entity["typeName"]) + "List", source)
    row = "row"
    show = f"title={{String({row}.{title} ?? \"\")}}" + (f" subtitle={{String({row}.{subtitle} ?? \"\")}}" if subtitle else "")
    statement = f"const {var} = useList({_q(entity['typeName'])}, {{}});"
    jsx = f"<ListView list={{{var}}} keyExtractor={{({row}) => {row}.id}} separators renderItem={{({row}) => <ListItem {show} />}} />"
    return statement, jsx


# ---------------------------------------------------------------------------
# Where, and the changes
# ---------------------------------------------------------------------------

def row_var_at(nodes: dict[str, dict], holder_id: str | None) -> str | None:
    """What the list row is called where a part is added, when it is added inside a row (`renderItem={(item) => …}`)."""
    seen = 0
    here = nodes.get(str(holder_id)) if holder_id else None
    while here is not None and seen < 100:
        if here.get("rowVar"):
            return str(here["rowVar"])
        here = nodes.get(str(here.get("parent"))) if here.get("parent") else None
        seen += 1
    return None


def holder_of(nodes: dict[str, dict], place: dict[str, str]) -> dict | None:
    """The part the new one goes into: the named one, or the parent of the brother it goes beside."""
    if place.get("parentId"):
        return nodes.get(str(place["parentId"]))
    ref = nodes.get(str(place.get("afterId") or place.get("beforeId") or ""))
    return nodes.get(str(ref.get("parent"))) if ref and not ref.get("slot") and ref.get("parent") else None


def holds_others(holder: dict | None, imports: dict[str, str]) -> bool:
    return bool(holder) and imports.get(str(holder.get("type"))) in CONTAINERS


def build(doc: dict, spec: dict[str, Any], *, source: str, nodes: dict[str, dict], imports: dict[str, str]) -> list[dict[str, Any]]:
    """The changes that add the part `spec` asks for, or a GuideError that says why they cannot."""
    available = refs(doc)
    place = {k: str(spec["place"][k]) for k in ("parentId", "afterId", "beforeId") if (spec.get("place") or {}).get(k)}
    if len(place) != 1:
        raise GuideError("Say where the part goes.")
    holder = holder_of(nodes, place)
    if not holds_others(holder, imports):
        raise GuideError("A part can't go there. Choose the screen itself, or a box, a column or a row.")
    kind = spec.get("kind")
    row_var = row_var_at(nodes, str(holder.get("id"))) if holder else None
    if kind in ("form", "button"):
        wf = next((w for w in available["workflows"] if w["id"] == spec.get("workflow")), None)
        if wf is None:
            raise GuideError("That workflow is not one of this application's.")
        if kind == "form":
            return [{"op": "addImport", "source": "@/ui", "names": ["WorkflowForm"]},
                    {"op": "addImport", "source": "@/sdk", "names": ["workflows"]},
                    {"op": "insert", "jsx": form_jsx(wf, row_var), **place}]
        label = str(spec.get("label") or "").strip()[:80] or wf["name"]
        values = {str(k): v for k, v in (spec.get("values") or {}).items() if str(k) in {i["name"] for i in wf["inputs"]}}
        return [{"op": "addImport", "source": "@/ui", "names": ["WorkflowButton"]},
                {"op": "addImport", "source": "@/sdk", "names": ["workflows"]},
                {"op": "insert", "jsx": button_jsx(wf, label, values, row_var), **place}]
    if kind == "list":
        entity = next((e for e in available["entities"] if e["name"] == spec.get("entity")), None)
        if entity is None:
            raise GuideError("That kind of record is not one of this application's.")
        if not spec.get("title"):
            raise GuideError("Choose what each row should say.")
        statement, jsx = list_parts(entity, str(spec["title"]), str(spec["subtitle"]) if spec.get("subtitle") else None, source)
        return [{"op": "addImport", "source": "@/ui", "names": ["ListView", "ListItem"]},
                {"op": "addImport", "source": "@/sdk", "names": ["useList"]},
                {"op": "addStatement", "code": statement},
                {"op": "insert", "jsx": jsx, **place}]
    raise GuideError("That is not a part this editor can build.")

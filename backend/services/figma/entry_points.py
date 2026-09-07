"""A drawn entry point opens a form for what its workflow needs.

A frame draws "+ New Case" as a button. When the file also draws the New Case
screen, the classifier binds the button to that route and the page composes.
When it does not — the destination was never drawn, so the plan has no page
for it — the classifier binds the button to the workflow the label names,
and the layout contract refuses the page: the workflow needs `caseType`,
`title`, `severity`… and a lone button collects nothing. Four pages of one
file were refused on exactly this, all of them entry points.

The button was drawn to raise a case; what raising a case takes is written
in the workflow's inputs. So the button opens a dialog holding a form for
those inputs, and the form runs the workflow. Enumerated fields become
selects with the entity's values; a field naming another record becomes a
select whose options come from that record's resource; everything else is
the input the type implies. Nothing is invented: the fields are the
workflow's required inputs and nothing more.

A control whose workflow needs a *record* — "Refund" on a queue, which needs
the case it is drawn beside — is not an entry point and is left alone: what
it needs is the row it sits in, which is the drawn list's binding, not a form.
"""
from __future__ import annotations

import re
from typing import Any

#: Workflow input types → form field kinds.
_KIND = {
    "string": "text", "text": "textarea", "enum": "select", "boolean": "checkbox",
    "decimal": "number", "number": "number", "integer": "number", "int": "number",
    "float": "number", "date": "date", "datetime": "date", "timestamp": "date",
    "email": "email",
}


def open_forms(doc: dict, page: dict, root: dict, sources: list[dict]) -> tuple[dict, list[dict], int]:
    """Rewrite each entry-point button under ``root`` to open a dialog form.

    Returns the root, the data sources the forms' pickers add, and how many
    buttons were rewritten. A button whose workflow's required fields are
    already collected by a form around it is not an entry point and is kept.
    """
    workflows = {str(w.get("id")): w for w in _live(doc.get("workflows"))}
    if not workflows or not isinstance(root, dict):
        return root, [], 0
    from services.blueprint.functional_completeness import _form_fields_around

    entities = _live((doc.get("data") or {}).get("entities"))
    by_id = {str(e.get("id")): e for e in entities}
    by_name = {str(e.get("name") or "").lower(): e for e in entities}
    added: list[dict] = []
    dialogs: list[dict] = []
    taken = {str((s or {}).get("name")) for s in sources if isinstance(s, dict)}
    ids: set[str] = set()

    def visit(node: dict) -> None:
        for child in node.get("children") or []:
            if not isinstance(child, dict):
                continue
            props = child.get("props") or {}
            if child.get("type") == "Button" and props.get("workflow") and not props.get("submit"):
                wf = workflows.get(str(props["workflow"]))
                if wf is not None:
                    needed = _fields_needed(wf, props, _form_fields_around(root, child))
                    if needed:
                        _rewrite(child, wf, needed)
                        continue
            visit(child)

    def _rewrite(button: dict, wf: dict, needed: list[dict]) -> None:
        props = dict(button.get("props") or {})
        label = str(props.get("label") or wf.get("name") or "").strip()
        title = re.sub(r"^[+＋]\s*", "", label) or str(wf.get("name") or "")
        dialog_id = _unique(_slug(title) or "entry", ids)
        entity = _acted_on(wf, by_id)
        fields = [_field(inp, entity, by_name, added, taken) for inp in needed]
        props.pop("workflow", None)
        props.pop("args", None)
        props["opensDialog"] = dialog_id
        button["props"] = props
        dialogs.append({
            "type": "Dialog",
            "props": {"id": dialog_id, "title": title, "size": "md"},
            "children": [{
                "type": "Form",
                "props": {"workflow": str(wf.get("id")), "submitLabel": title,
                          "fields": fields},
                "children": [],
            }],
        })

    visit(root)
    if dialogs:
        root.setdefault("children", []).extend(dialogs)
    return root, added, len(dialogs)


def _fields_needed(wf: dict, props: dict, around: set[str] | None) -> list[dict]:
    """The workflow's required field inputs the button does not supply."""
    args = props.get("args") if isinstance(props.get("args"), dict) else {}
    have = set(around or ())
    out = []
    for inp in wf.get("inputs") or []:
        if inp.get("kind") != "field" or not inp.get("required", True):
            continue
        name = str(inp.get("name") or "")
        if name and name not in args and name not in have:
            out.append(inp)
    return out


def _field(inp: dict, entity: dict | None, by_name: dict, added: list[dict],
           taken: set[str]) -> dict:
    name = str(inp.get("name") or "")
    kind = _KIND.get(str(inp.get("type") or "").lower(), "text")
    field: dict[str, Any] = {"kind": kind, "name": name, "label": _label(name),
                             "required": bool(inp.get("required", True))}
    if kind == "checkbox":
        field.pop("required")
    if kind == "select":
        values = _enum_values(inp, entity, name)
        if values:
            field["options"] = [{"value": v, "label": v} for v in values]
        else:
            field["kind"] = "text"
    if str(inp.get("type") or "").lower() == "uuid":
        target = _referenced(name, by_name)
        if target is not None:
            resource = str(target.get("table") or "")
            field.update({"kind": "select", "options": [],
                          "interaction": {"optionsFrom": {
                              "source": resource, "value": "id",
                              "label": str(target.get("labelField") or "name")}}})
            field["label"] = str(target.get("name") or _label(name))
            if resource and resource not in taken:
                taken.add(resource)
                added.append({"name": resource, "op": "list",
                              "entity": str(target.get("name") or ""), "limit": 50})
    return field


def _enum_values(inp: dict, entity: dict | None, name: str) -> list[str]:
    for key in ("enumValues", "values", "options"):
        vals = inp.get(key)
        if isinstance(vals, list) and vals:
            return [str(v) for v in vals]
    for f in (entity or {}).get("fields") or []:
        if str(f.get("name")) == name:
            vals = f.get("enumValues") or f.get("values") or []
            return [str(v) for v in vals]
    return []


def _referenced(name: str, by_name: dict) -> dict | None:
    """The entity a `<thing>Id` input names, when the model has it."""
    stem = re.sub(r"(Id|ID|_id)$", "", name)
    if not stem or stem == name:
        return None
    return by_name.get(stem.lower())


def _acted_on(wf: dict, by_id: dict) -> dict | None:
    for step in wf.get("steps") or []:
        ent = by_id.get(str(step.get("entity") or ""))
        if ent is not None:
            return ent
    return None


def _label(name: str) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ")
    words = re.sub(r"\s+[Ii]d$", "", words)
    return words[:1].upper() + words[1:]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _unique(base: str, taken: set[str]) -> str:
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    taken.add(out)
    return out


def _live(items: Any) -> list[dict]:
    return [x for x in (items or []) if isinstance(x, dict) and x.get("status") != "retired"]

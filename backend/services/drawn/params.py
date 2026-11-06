"""A converted screen's example content, turned into props — its contract.

`tsx` draws a frame exactly, with the designer's example content written in:
"MedStaff Partners", "7 of 10", five table rows. What of that is data, what
is fixed copy, which rows are one list and what each button does is a
judgement about meaning, so it is a model's — but a model's that does not
touch the drawing. It is shown the frame and its markup with every element
numbered (`markup.numbered`), and answers with the CONTRACT that says what
each prop is and, by number, where each prop goes: which texts are values,
which sibling rows are one list (and which field picks a row's look), which
elements each action is pressed on, which texts are inputs, which elements
are drawn only in some states.

THE VIEW IS WRITTEN BY CODE FROM THAT ANSWER (`apply`), so the markup is the
drawing by construction: the first row of a list is kept as its template, a
look chosen by a field is another drawn row's classes on the template's
elements, and nothing else changes. The SAMPLE — the drawing's own content in
the contract's shape — is read from the drawing too: every drawn row through
the template's bindings.

Asked to write the markup back with props in it, the model emitted up to 38k
tokens a screen and lost or invented classes on half of them: four of eight
D6 Promotions conversions were refused after three rounds (DITANS,
2026-10-29). An answer by number is a few thousand tokens, and what is
checked is only what a model can get wrong: a number that is not there, a
path the contract does not have, a prop nothing reads.
"""
from __future__ import annotations

import colorsys
import copy
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from services.drawn import markup as M
from services.drawn.contract import change_handler, props_type, unused

#: Rounds a screen gets to come back right.
ROUNDS = 3

_FIELD_TYPES = ["string", "text", "number", "money", "percent", "date", "datetime", "boolean", "enum",
                "email", "phone", "url", "image", "id"]

_PATH = re.compile(r"^(props|row)\.([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?$")


def _schema(children: bool) -> dict[str, Any]:
    ids = {"type": "array", "items": {"type": "string"}}
    props: dict[str, Any] = {
        "contract": {
            "type": "object",
            "additionalProperties": False,
            "required": ["data", "actions"],
            "properties": {
                "data": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["name", "kind", "label", "fields"],
                    "properties": {
                        "name": {"type": "string"}, "label": {"type": "string"},
                        "kind": {"type": "string", "enum": ["list", "record", "form", "value"]},
                        "type": {"type": "string", "enum": _FIELD_TYPES},
                        "fields": {"type": "array", "items": {
                            "type": "object", "additionalProperties": False,
                            "required": ["name", "label", "type"],
                            "properties": {
                                "name": {"type": "string"}, "label": {"type": "string"},
                                "type": {"type": "string", "enum": _FIELD_TYPES},
                                "options": {"type": "array", "items": {"type": "string"}},
                                "many": {"type": "boolean"},
                                "required": {"type": "boolean"},
                            }}},
                    }}},
                "actions": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["name", "label", "kind", "nodes"],
                    "properties": {
                        "name": {"type": "string"}, "label": {"type": "string"},
                        "kind": {"type": "string", "enum": ["navigate", "open", "submit", "run"]},
                        "target": {"type": "string"}, "on": {"type": "string"},
                        "nodes": ids,
                    }}},
            },
        },
        "lists": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["prop", "rows"],
            "properties": {
                "prop": {"type": "string"}, "rows": ids,
                "where": {"type": "object", "additionalProperties": False, "required": ["field", "equals"],
                          "properties": {"field": {"type": "string"}, "equals": {"type": "string"}}},
                "looks": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["field", "by"],
                    "properties": {"node": {"type": "string"}, "field": {"type": "string"},
                                   "by": {"type": "array", "items": {
                                       "type": "object", "additionalProperties": False, "required": ["value", "row"],
                                       "properties": {"value": {"type": "string"}, "row": {"type": "string"}}}}}}},
            }}},
        "values": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["node", "expr"],
            "properties": {"node": {"type": "string"}, "expr": {"type": "string"}, "prop": {"type": "string"}}}},
        "inputs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["node", "form", "field", "kind"],
            "properties": {
                "node": {"type": "string"}, "form": {"type": "string"}, "field": {"type": "string"},
                "kind": {"type": "string", "enum": ["text", "select", "toggle", "choice"]},
                "value": {"type": "string"}, "placeholder": {"type": "boolean"},
                "on_look": {"type": "string"}, "off_look": {"type": "string"}, "prop": {"type": "string"},
                "on": {"type": "boolean"},
            }}},
        "shows": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["node", "when"],
            "properties": {"node": {"type": "string"}, "when": {"type": "string"}, "not": {"type": "boolean"}}}},
        "leave_out": ids,
    }
    if children:
        props["controls"] = ids
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


REPLY_SCHEMA = _schema(False)

SYSTEM = """You say what a drawn screen's example content is, so the screen can be built from data.

The screen is already converted to React markup, and every element is numbered (`12|<div …>`). You do NOT
write or change markup: you name elements by their number, and code builds the view from the drawing exactly
as drawn. You answer with:

CONTRACT — what the view is given: `data` (each a `list`, `record`, `form` or `value`, each field with the type
the drawing shows — a date, money, an enum with the drawn options, a boolean for an on/off) and `actions`.
What would be different for another record or another day is data — names, numbers, dates, amounts,
statuses, counts, the rows of a table, the cards of a list, a selected record's details, what an input holds.
What is the same whatever the data — headings, column headers, labels, helper text, button words, the rules and
notes the screen states — is not data; leave it as drawn. Names are camelCase; an action's name is `on` + the
words on it in PascalCase ("New tenant" → `onNewTenant`). `navigate` goes to another screen (give `target`
when the screen's links say where), `open` opens a dialog, drawer or tab of this one, `submit` sends a form,
`run` does something to a record. Everything in the contract is used below.

LISTS — rows, cards or chips of one structure repeated as siblings are one list: `{prop, rows}`, `rows` every
drawn row's number in order (the first is kept as the template). Rows of one shape that each name a different
thing (settings, entitlements, key/value lines, a checklist) are ONE list with `label` and `value` fields —
never one field per row. Where the rows are drawn in different looks, each element whose look differs names
the field that picks it: `looks: [{node, field, by: [{value, row}]}]` — `node` the element in the template row
(leave it out for the whole row), and for each value of an enum or boolean field ("true"/"false") a drawn row
where that element has that look. One row can have several: the selected row's highlight follows `selected`
while its status pill follows `status` — give them as two looks, never one. Rows under different headings of
one list (a menu's groups) are one entry per heading, each with `where: {field, equals}`. A table drawn column
by column (each column a stack of cells, not each row a line of them) is one list given once per column: an
entry per column with the same `prop`, its `rows` that column's cells top to bottom.

VALUES — `{node, expr}` puts data where the drawing has example content: a text's words, a picture's `src`, or
one of a shared component's words (`prop`: which). `expr` is `props.<value>`, `props.<record or form>.<field>`,
or `row.<field>` for an element inside a list's template row (the first of its `rows`).

ACTIONS — every action's `nodes` are the elements pressed for it: a button, a row, a tab, a link, a menu item.
Pressed inside a list's template row, it is given that row.

INPUTS — what the person sets is a field of a `form`: `{node, form, field, kind}`. `text` and `select`: `node` is
the text showing the value (it becomes the input; `placeholder: true` when the drawn words are a hint such as
"Search…", not a value), or a shared component drawn as a field, with `prop` the one of its words that is the
value. `toggle`: `node` is the switch or check box, `on: true` when it is drawn switched on or ticked. `choice`: `node` is one option (a chip, a radio row,
a segment) and `value` the option it sets; `on_look` / `off_look` are the numbers of an option drawn selected
and one drawn not selected, so the selection shows. When several options may be chosen together (more than one
drawn selected, "pick up to 3"), the form's field says `many: true`: it holds a list, and each option adds or
removes its `value`.

SHOWS — `{node, when}`: an element drawn for one state only (a dialog drawn open, a banner, an empty state) is
shown while `when` — a path as above, `not: true` for its opposite — is true.

LEAVE OUT — `leave_out`: elements drawn on the screen that are not part of the app: a phone's status bar (the
time, signal, battery), a home indicator or a keyboard drawn on a phone screen, a note or annotation the designer
wrote for the developer. Nothing else: an element that shows the app's own content is bound, never left out.

The drawing's own content (the sample) is read from the drawing by code: do not write it."""

_SHELL = """

THIS IS THE APPLICATION'S SHELL — the sidebar and top bar every screen is drawn in — not a screen. The sidebar's
destinations are the list `nav` (fields `label`, `icon` (the drawn picture's src), `href`, `active` (boolean,
the look of the screen you are on) and `section` (the heading it sits under, "" for none)), pressed for one
action `onNav`; group headings stay as drawn. `controls`: the numbers of the drawn bell and account avatar —
the application puts its own there. The top bar's search is a `form` `search` (field `query`, a placeholder);
its main button is an action."""


@dataclass
class _Plan:
    """A reply resolved against the markup."""
    root: M.Node
    nodes: dict[str, M.Node]
    slots: dict[str, dict]
    lists: list[dict] = field(default_factory=list)
    #: template row id → its list entry.
    templates: dict[str, dict] = field(default_factory=dict)
    #: node id → the list whose template it is inside.
    scope: dict[str, str] = field(default_factory=dict)
    skip: set[str] = field(default_factory=set)
    values: dict[str, list[dict]] = field(default_factory=dict)
    actions: dict[str, dict] = field(default_factory=dict)
    inputs: dict[str, dict] = field(default_factory=dict)
    shows: dict[str, dict] = field(default_factory=dict)
    controls: list[str] = field(default_factory=list)
    #: The contract's `data`, for what the bindings declare.
    data: list = field(default_factory=list)
    #: Elements of a list given up for the lists inside its rows.
    dropped: set[str] = field(default_factory=set)
    #: node id → the field that picks its look and, by value, the element drawn in it.
    looks: dict[str, dict] = field(default_factory=dict)
    components: set[str] = field(default_factory=set)



def _fields(slot: dict) -> dict[str, dict]:
    return {str(f.get("name")): f for f in slot.get("fields") or [] if isinstance(f, dict) and f.get("name")}


def _dropped_row(plan: _Plan, at: str, expr: Any) -> bool:
    """A row's binding inside a list given up for the lists in its rows."""
    return at in plan.dropped and at not in plan.scope and str(expr or "").strip().startswith("row.")


def _path(plan: _Plan, expr: str, at: str, problems: list[str], what: str, *, whole: bool = False) -> bool:
    """Whether ``expr`` reads something the contract has (declaring what it
    can). ``whole``: a condition may ask of a record itself — shown while
    there is one."""
    m = _PATH.match(expr.strip())
    if not m:
        problems.append(f"{what}: `{expr}` is not `props.<name>`, `props.<name>.<field>` or `row.<field>`")
        return False
    base, name, sub = m.groups()

    # A VALUE DECLARES WHAT IT READS. Bound by number to a field the contract
    # forgot (`props.newKitLabel`, `row.owner`), the screen was refused three
    # rounds for it (DITANS wzml1sa6, 2026-10-29); what it reads is words.
    def declare(slot: dict, field: str) -> None:
        if field != "id" and field not in _fields(slot):
            slot.setdefault("fields", []).append({"name": field, "label": field, "type": "string"})

    if base == "row":
        listed = plan.scope.get(at)
        if listed is None:
            problems.append(f"{what}: `{expr}` is not inside a list's template row")
            return False
        if sub:
            problems.append(f"{what}: a row's field is `row.<field>`, one name")
            return False
        declare(plan.slots[listed], name)
        return True
    slot = plan.slots.get(name)
    if slot is None:
        slot = {"name": name, "label": name, "kind": "record" if sub else "value", "fields": []}
        if not sub:
            slot["type"] = "string"
        plan.slots[name] = slot
        plan.data.append(slot)
    kind = str(slot.get("kind") or "value")
    if kind == "list":
        problems.append(f"{what}: `{name}` is a list — its rows are a `lists` entry, its fields `row.<field>`")
        return False
    if kind == "value" and sub:
        problems.append(f"{what}: `{name}` is a value, read as `props.{name}`")
        return False
    if kind in ("record", "form") and not sub:
        if whole:
            return True
        problems.append(f"{what}: `{name}` is a {kind}, read as `props.{name}.<field>`")
        return False
    if kind in ("record", "form"):
        declare(slot, sub)
    return True


def _resolve(root: M.Node, reply: dict, *, children: bool) -> tuple[_Plan, list[str]]:
    contract = reply.get("contract") or {}
    plan = _Plan(root=root, nodes=M.index(root), data=contract.setdefault("data", []),
                 slots={str(s.get("name")): s for s in contract.get("data") or []
                        if isinstance(s, dict) and s.get("name")})
    problems: list[str] = []
    nodes = plan.nodes

    def node(i: Any, what: str, *, quiet_root: bool = False) -> M.Node | None:
        n = nodes.get(str(i))
        if n is None:
            problems.append(f"{what}: there is no element {i}")
        elif n is root:
            # A value, an input or a condition on the whole screen binds
            # nothing a person sees; it is left out rather than refused.
            if not quiet_root:
                problems.append(f"{what}: element {i} is the whole screen")
            return None
        return n

    # A LIST INSIDE ANOTHER LIST'S ROWS: THE INNER ONE IS THE DATA. A ladder
    # drawn as steps each holding its tasks was answered as both, and refused
    # as "its rows are already another list's" (DITANS readiness ladder,
    # 2026-10-30). The outer rows are drawn as they are, and what was bound
    # to them as a row is left as drawn.
    # NOT THE APP: a phone's status bar ("9:41 ●●● ▲ ▮") rendered inside a
    # job's page, a designer's note shown to every candidate (DITANS QA D-19,
    # D-48, 2026-11-02).
    for nid in reply.get("leave_out") or []:
        if str(nid) in nodes and nodes[str(nid)] is not root:
            plan.skip.add(str(nid))
    entries = [e for e in reply.get("lists") or [] if isinstance(e, dict)]
    inside = [{n.id for r in e.get("rows") or [] if str(r) in nodes for n in nodes[str(r)].walk()} for e in entries]
    outer = {i for i, area in enumerate(inside)
             if any(j != i and set(map(str, entries[j].get("rows") or [])) & area for j in range(len(entries)))}
    for i in outer:
        plan.dropped |= inside[i]
    for entry in (e for i, e in enumerate(entries) if i not in outer):
        prop = str(entry.get("prop") or "")
        slot = plan.slots.get(prop)
        what = f"the list `{prop}`"
        if slot is None and re.match(r"^[A-Za-z_]\w*$", prop):
            # A list declares itself, as a value does what it reads.
            slot = {"name": prop, "label": prop, "kind": "list", "fields": []}
            plan.slots[prop] = slot
            plan.data.append(slot)
        if slot is None or slot.get("kind") != "list":
            problems.append(f"{what} is not a `list` in the contract")
            continue
        rows = [node(r, what) for r in entry.get("rows") or []]
        if not rows:
            problems.append(f"{what} names no rows")
        if not rows or None in rows:
            continue
        if len({id(r.parent) for r in rows}) > 1:
            problems.append(f"{what}: its rows {[r.id for r in rows]} are not siblings of one element")
            continue
        template = rows[0]
        if any(n.id in plan.scope or n.id in plan.skip for r in rows for n in r.walk()):
            problems.append(f"{what}: its rows are already another list's")
            continue
        names = _fields(slot)
        where = entry.get("where") or None
        if where and str(where.get("field")) not in names:
            problems.append(f"{what}: `where` names `{where.get('field')}`, not one of its fields")
            continue
        looks, bad = [], False
        inside = {n.id for n in template.walk()}
        for lk in entry.get("looks") or []:
            at = str(lk.get("node") or template.id)
            # Named in another row, the element is its place in the template:
            # the row itself is the template row, an element in it the one at
            # the same place (DITANS wzml1sa6, 2026-10-30).
            if at not in inside and at in nodes:
                other = next((r for r in rows if r.id == at or any(n.id == at for n in r.walk())), None)
                if other is not None:
                    there = template if other.id == at else M.counterpart(other, template, nodes[at])
                    at = there.id if there is not None else at
            if at not in inside:
                problems.append(f"{what}: a look's node {at} is not in its template row {template.id}")
                bad = True
                continue
            f = str(lk.get("field") or "")
            if not re.match(r"^[A-Za-z_]\w*$", f):
                problems.append(f"{what}: a look names `{f}`, not a field name")
                bad = True
                continue
            if f not in names:
                # A LOOK DECLARES ITS FIELD. Asked for the selected row's look,
                # the model named `selected` and forgot the field; three rounds
                # were refused for it (DITANS A-11, 2026-10-29). Its values say
                # what it is: on/off, or the drawn options.
                values = [str(b.get("value")) for b in lk.get("by") or []]
                spec = {"name": f, "label": f, "type": "boolean"} if set(v.lower() for v in values) <= {"true", "false"} \
                    else {"name": f, "label": f, "type": "enum", "options": list(dict.fromkeys(values))}
                slot.setdefault("fields", []).append(spec)
                names = _fields(slot)
            by = []
            for b in lk.get("by") or []:
                drawn = nodes.get(str(b.get("row")))
                if drawn is None:
                    problems.append(f"{what}: a look's row {b.get('row')} is not an element")
                    bad = True
                    continue
                if at == template.id:
                    there = drawn
                elif any(drawn is r for r in rows):
                    there = M.counterpart(template, drawn, nodes[at])
                else:
                    # NAMED BY AN ELEMENT, NOT ITS ROW: the look is that element
                    # as drawn, or the one at the element's place in the row it
                    # sits in (DITANS wzml1sa6, 2026-10-30: "row 14 draws
                    # nothing where element 14 is").
                    holder = next((r for r in rows if any(n is drawn for n in r.walk())), None)
                    if M.same_kind(nodes[at], drawn):
                        there = drawn
                    elif holder is not None:
                        there = M.counterpart(template, holder, nodes[at])
                    else:
                        there = None
                # A ROW THAT DRAWS NOTHING THERE IS THAT LOOK: a document's
                # button drawn only for the statuses that have one (DITANS
                # R-205, 2026-10-30). For that value the element is not drawn.
                by.append((str(b.get("value")), there))
            if by:
                looks.append({"node": at, "field": str(lk["field"]), "by": by, "list": prop})
        if bad:
            continue
        for lk in looks:
            plan.looks[lk["node"]] = lk
        resolved = {**entry, "prop": prop, "rows": [r.id for r in rows], "looks": looks}
        plan.lists.append(resolved)
        plan.templates[template.id] = resolved
        # Every row is the list's: a look drawn only on one (an Extend button
        # on an expired code) is bound where it is drawn, given the row.
        for r in rows:
            for n in r.walk():
                plan.scope[n.id] = prop
        plan.skip |= {r.id for r in rows[1:]}

    for v in reply.get("values") or []:
        n = node(v.get("node"), f"the value at {v.get('node')}", quiet_root=True)
        if n is None or n.id in plan.skip:
            continue
        what = f"the value at {n.id}"
        if _dropped_row(plan, n.id, v.get("expr")):
            continue
        if not _path(plan, str(v.get("expr") or ""), n.id, problems, what):
            continue
        unit = n.unit()
        if n.body is None and not unit.is_component and unit.tag != "img":
            # Named by its box, the value is the one text, picture or component in it.
            held = [t for t in n.walk() if t is not n and (t.body is not None or t.tag == "img" or t.is_component)
                    and not (t.parent is not None and t.parent.unit() is t)]
            if len(held) == 1:
                n, unit = held[0], held[0].unit()
        prop = str(v.get("prop") or "")
        if unit.is_component:
            words = [k for k, _v in unit.attrs]
            prop = prop or (words[0] if len(words) == 1 else "")
            if prop not in words:
                problems.append(f"{what}: `{unit.tag}` takes {words}; say which in `prop`")
                continue
        elif unit.tag == "img":
            prop = "src"
        elif n.body is None:
            problems.append(f"{what}: element {n.id} is not a text, a picture or a shared component")
            continue
        plan.values.setdefault(n.id, []).append({"expr": str(v["expr"]).strip(), "prop": prop})

    for a in contract.get("actions") or []:
        name = str(a.get("name") or "")
        if not re.match(r"^on[A-Z]\w*$", name):
            problems.append(f"the action `{name}` is not named `on` + PascalCase")
            continue
        scopes: dict[str | None, list[str]] = {}
        for i in a.get("nodes") or []:
            # The whole screen is not a button, and an element already
            # pressed for one action is that action's; an action left with
            # nothing to press is one the drawing does not have (`apply`).
            if str(i) == root.id or str(i) in plan.actions:
                continue
            n = node(i, f"the action `{name}`")
            if n is None or n.id in plan.skip:
                continue
            plan.actions[n.id] = a
            scopes.setdefault(plan.scope.get(n.id), []).append(n.id)
        if len(scopes) > 1:
            # Pressed on a row it is done to that row; pressed outside, to none —
            # two things, as an "Extend" on a summary card and one on an
            # expired code's row are (DITANS A-11, 2026-10-29).
            where = "; ".join(f"in the rows of `{k}`: {v}" if k else f"outside any list's rows: {v}"
                              for k, v in scopes.items())
            problems.append(f"the action `{name}` is pressed {where} — pressed in a row it is done to that row, "
                            "so the elements in the rows are a second action of their own (its name says it acts "
                            "on one), with only those elements in its `nodes`")
        elif scopes and None not in scopes:
            a["on"] = next(iter(scopes))
        elif str(a.get("on") or "") and (plan.slots.get(str(a["on"])) or {}).get("kind") == "list":
            a.pop("on")  # pressed outside the rows, it is given none

    for inp in reply.get("inputs") or []:
        n = node(inp.get("node"), f"the input at {inp.get('node')}", quiet_root=True)
        if n is None or n.id in plan.skip:
            continue
        what = f"the input at {n.id}"
        form, name, kind = str(inp.get("form") or ""), str(inp.get("field") or ""), str(inp.get("kind") or "")
        # AN INPUT DECLARES ITS FORM AND FIELD, as a value does what it reads:
        # a record the person types into is a form.
        slot = plan.slots.get(form)
        if not re.match(r"^[A-Za-z_]\w*$", form) or not re.match(r"^[A-Za-z_]\w*$", name):
            problems.append(f"{what}: `{form}.{name}` is not a form and field name")
            continue
        if slot is None:
            slot = {"name": form, "label": form, "kind": "form", "fields": []}
            plan.slots[form] = slot
            plan.data.append(slot)
        if slot.get("kind") == "record":
            slot["kind"] = "form"
        if slot.get("kind") != "form":
            problems.append(f"{what}: `{form}` is a {slot.get('kind')}, not a form")
            continue
        if name not in _fields(slot):
            slot.setdefault("fields", []).append({"name": name, "label": name,
                                                   "type": "boolean" if kind == "toggle" else "string"})
        if n.id in plan.scope:
            problems.append(f"{what} is inside a list's rows — a row's control is an action given the row")
            continue
        unit = n.unit()
        if kind in ("text", "select") and unit.is_component:
            # A SHARED COMPONENT DRAWN AS A FIELD IS THE INPUT. A design
            # system's text field is a component whose words are its label,
            # value and help; refused as "not the text showing its value", every
            # form drawn with one failed three rounds (DITANS R-204, 2026-10-30).
            # The word that is the value is named, or read off the words' names.
            words = [k for k, _v in unit.attrs]
            prop = str(inp.get("prop") or "")
            if prop not in words:
                named = [w for w in words if re.search(r"value|text|input|placeholder|content", w, re.I)]
                prop = words[0] if len(words) == 1 else (named[0] if len(named) == 1 else "")
            if not prop:
                problems.append(f"{what}: `{unit.tag}` has the words {words}; say which is the value in `prop`")
                continue
            if n.id in plan.actions:
                plan.actions.pop(n.id)
            plan.inputs[n.id] = {**inp, "form": form, "field": name, "kind": kind, "prop": prop}
            continue
        if kind in ("text", "select") and n.body is None:
            # Named by its box, the input is the one text drawn in it.
            texts = [t for t in n.walk() if t.body is not None and t.unit() is t and t is not n]
            # The text that fills the box is the value; a unit or a hint beside it is drawn as it is.
            filling = [t for t in texts if re.search(r"(?:^|\s)(?:flex-1|w-full|self-stretch)(?:\s|$)", t.classes())]
            if len(texts) == 1 or len(filling) == 1:
                n = (filling or texts)[0]
        if kind in ("text", "select") and (n.body is None or n.unit() is not n):
            problems.append(f"{what}: a {kind} input's node is the text showing its value")
            continue
        if kind == "choice" and not str(inp.get("value") or ""):
            problems.append(f"{what}: a choice says the `value` it sets")
            continue
        if n.id in plan.actions:
            # What the person sets is what the element does; the action named
            # for it too is pressed elsewhere or nowhere (and then left out).
            plan.actions.pop(n.id)
        if all(node(inp[key], what) is not None for key in ("on_look", "off_look") if inp.get(key)):
            plan.inputs[n.id] = {**inp, "form": form, "field": name, "kind": kind}

    for s in reply.get("shows") or []:
        n = node(s.get("node"), f"the condition at {s.get('node')}", quiet_root=True)
        if n is None or n.id in plan.skip:
            continue
        if _dropped_row(plan, n.id, s.get("when")):
            continue
        if _path(plan, str(s.get("when") or ""), n.id, problems, f"the condition at {n.id}", whole=True):
            plan.shows[n.id] = s

    if children:
        for i in reply.get("controls") or []:
            n = node(i, "controls")
            if n is not None and n.id not in plan.skip:
                plan.controls.append(n.id)
    if not problems:
        problems += _lost(plan)
    return plan, problems


_COLOUR = re.compile(r"^(?:text|bg|border|fill|stroke)-\[(?:#|rgba?\()")


def _colours(node: M.Node) -> set[str]:
    return {c for c in node.classes().split() if _COLOUR.match(c)}


def _lost(plan: _Plan) -> list[str]:
    """What a list would lose of its drawn rows: words, pictures, parts or
    colours that differ from row to row where nothing is bound and no look
    is given — each row is drawn as the template, so a ✗ drawn on two rules
    came out ✓ on every one, and a selected first row lit up all of them
    (DITANS A-11, A-12, 2026-10-29)."""
    out: list[str] = []
    for listed in plan.lists:
        rows = [plan.nodes[r] for r in listed["rows"]]
        template, others = rows[0], rows[1:]
        if not others:
            continue
        looked = {lk["node"] for lk in listed.get("looks") or []}

        def covered(t: M.Node) -> bool:
            at: M.Node | None = t
            while at is not None:
                if at.id in looked:
                    return True
                if at is template:
                    return False
                at = at.parent
            return False

        found: list[str] = []
        for t in template.walk():
            # A component in its sizing box is bound where the box is: its words
            # bound on the box are bound (Build your CV's "From: …" tags were
            # refused as unbound words, DITANS 2026-10-30); its component is
            # still its look.
            boxed = t.parent is not None and t.parent.unit() is t
            words_bound = t.id in plan.values or (boxed and t.parent.id in plan.values)
            if t.id in plan.inputs or (boxed and t.parent.id in plan.inputs):
                continue
            # A LOOK GIVES A ROW ITS COLOURS, NOT ITS WORDS. Every look keeps the
            # template row's text (markup.relook), so a stepper whose rows were
            # looked by status read "Organisation type" on every step, with a ✓
            # on each (DITANS QA D-28, D-34, 2026-11-02): under a look, words
            # that differ from row to row must still be bound.
            in_look = covered(t)
            unit = t.unit()
            if words_bound and not (unit is t and unit.is_component):
                continue
            for r in others:
                there = M.counterpart(template, r, t)
                if there is None or not M.same_kind(t, there):
                    continue
                if in_look:
                    if t.body is not None and not unit.is_component and M.plain(t) != M.plain(there):
                        found.append(f"element {t.id} reads “{M.plain(t)[:30]}” but “{M.plain(there)[:30]}” on row {r.id}")
                    continue
                if unit.is_component and (there.unit().tag != unit.tag
                                          or (not words_bound and M.plain(there) != M.plain(t))):
                    found.append(f"element {t.id} is drawn as `{there.unit().tag}` “{M.plain(there)}” on row {r.id}")
                elif t.tag == "img" and t.attr("src") != there.attr("src"):
                    found.append(f"element {t.id} is a different picture on row {r.id}")
                elif t.body is not None and not unit.is_component and M.plain(t) != M.plain(there):
                    found.append(f"element {t.id} reads “{M.plain(t)[:30]}” but “{M.plain(there)[:30]}” on row {r.id}")
                elif _colours(t) != _colours(there):
                    # A COLOUR IS A MEANING: the selected row's tint, a figure
                    # drawn green for good. A border or a gap that differs on
                    # the last row is not, and is left as the template draws it.
                    found.append(f"element {t.id} is drawn in other colours on row {r.id} "
                                 f"({' '.join(sorted(_colours(there) - _colours(t))) or 'none of its own'})")
                else:
                    continue
                break
        if found:
            out.append(f"the list `{listed['prop']}` would draw every row as row {template.id}, losing what the "
                       "rows draw differently: " + "; ".join(found[:4])
                       + " — bind what is data (a value `row.<field>`), give what is a look a `looks` entry")
    return out


def _shown_as_words(plan: _Plan) -> None:
    """A field the view shows as words is words. "New accounts only: Yes"
    typed `boolean` rendered nothing where the drawing says Yes (DITANS A-11,
    2026-10-29); a field that picks a look, a condition or a switch stays one."""
    deciding = {(lk["list"], lk["field"]) for lk in plan.looks.values()}
    for s in plan.shows.values():
        m = _PATH.match(str(s["when"]))
        if m:
            deciding.add((m.group(2), m.group(3)) if m.group(1) == "props" else (plan.scope.get(s["node"]), m.group(2)))
    deciding |= {(i["form"], i["field"]) for i in plan.inputs.values()}
    for nid, values in plan.values.items():
        if plan.nodes[nid].tag == "img":
            continue
        for v in values:
            m = _PATH.match(v["expr"])
            if not m:
                continue
            slot, name = (plan.scope.get(nid), m.group(2)) if m.group(1) == "row" else (m.group(2), m.group(3))
            f = _fields(plan.slots.get(slot or "") or {}).get(name or "")
            if f is not None and str(f.get("type")) == "boolean" and (slot, name) not in deciding:
                f["type"] = "string"


#: What `present(props.x)` asks of a record a view draws a card for.
PRESENT = """
/** A record is there when anything in it is: not null, not only empty words. */
function present(record: unknown): boolean {
  return !!record && Object.values(record as Record<string, unknown>).some(
    (v) => v !== "" && v != null && v !== false && !(Array.isArray(v) && v.length === 0));
}
"""


def _guard_records(plan: _Plan) -> None:
    """A CARD ABOUT ONE RECORD IS SHOWN WHILE THERE IS ONE. A new DITANS
    candidate's home drew its next step, an invitation and an unfinished
    application as cards of empty words and wordless buttons, because the
    drawing shows one of each and nothing said they could be missing (QA
    2026-11-06). The card is the largest element holding everything bound to
    the record and nothing bound to anything else; it is drawn while the
    record is there, and the page gives `null` when it is not."""
    reads: dict[str, set[str]] = {}

    def note(nid: str, expr: Any) -> None:
        m = _PATH.match(str(expr or "").strip())
        if m and m.group(1) == "props":
            reads.setdefault(nid, set()).add(m.group(2))

    for nid, values in plan.values.items():
        for v in values:
            note(nid, v["expr"])
    for nid, a in plan.actions.items():
        if a.get("on"):
            reads.setdefault(nid, set()).add(str(a["on"]).split(".")[0])
    for nid, t in plan.templates.items():
        reads.setdefault(nid, set()).add(str(t.get("prop") or "").split(".")[0])
    for nid, inp in plan.inputs.items():
        reads.setdefault(nid, set()).add(str(inp["form"]))
    for nid, s in plan.shows.items():
        note(nid, s["when"])
    asked = {_PATH.match(str(s["when"])).group(2) for s in plan.shows.values() if _PATH.match(str(s["when"]))}

    def chain(n: M.Node) -> list[M.Node]:
        out = []
        while n is not None:
            out.append(n)
            n = n.parent
        return out[::-1]

    for name, slot in plan.slots.items():
        if slot.get("kind") != "record" or "." in name or name in asked:
            continue
        bound = [plan.nodes[nid] for nid, slots in reads.items() if name in slots]
        if not bound or any(n.id in plan.scope for n in bound):
            continue
        chains = [chain(n) for n in bound]
        card = None
        for level in zip(*chains):
            if any(n is not level[0] for n in level):
                break
            card = level[0]
        if card is None:
            continue

        def others(n: M.Node) -> bool:
            return any(reads.get(t.id, set()) - {name} for t in n.walk())

        top = card
        while top.parent is not None and top.parent is not plan.root and not others(top.parent):
            top = top.parent
        if top is plan.root or others(top):
            continue
        # A CARD IS WHAT THE DRAWING DRAWS AS ONE: a box with its own fill, edge or
        # shadow, or a shared component. Climbing to whatever held nothing else
        # took page headers and whole bodies with it — a 90-day check-in lost its
        # question when there was no placement, and 124 of DITANS' 226 guards were
        # a "Header", "Body" or "KPI row" (2026-11-06). With no box, nothing hides.
        span = chain(card)[chain(card).index(top):] if top is not card else [card]
        card = next((n for n in span if _surface(n)), None)
        if card is None or card.id in plan.shows:
            continue
        # THERE WHILE ANYTHING IN IT IS. `null` is none; so is an object of empty
        # words, which is what a page gives that wrote `x?.title ?? ""` for one
        # it does not have. A record being written has no id yet but has words
        # — a new job's title, its "Draft" — and keeps its card.
        plan.shows[card.id] = {"node": card.id, "when": f"present(props.{name})"}


_SURFACE = re.compile(r"(?:^|\s)(?:bg-|border(?:-\[|\s|$)|shadow)")


def _surface(n: M.Node) -> bool:
    """The element draws a box of its own: a fill, an edge, a shadow, or it is
    (or only sizes) a shared component."""
    return n.unit().is_component or bool(_SURFACE.search(n.classes()))


def _attrs(attrs: list[tuple[str, str]]) -> str:
    return "".join(f" {k}={v}" for k, v in attrs)


#: Elements the browser already lets a person reach with Tab and press with a key.
_NATIVE = frozenset({"button", "a", "input", "select", "textarea", "label", "summary", "option"})
_KEYS = ('{(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); '
         '(e.currentTarget as HTMLElement).click(); } }}')


def _with(attrs: list[tuple[str, str]], tag: str = "div", **extra: str) -> list[tuple[str, str]]:
    out = [(k, v) for k, v in attrs if k not in extra]
    if extra.get("onClick"):
        # A PRESSABLE DRAWING SHOWS THE HAND. The drawn controls are divs, and a
        # div keeps the arrow: on DITANS no chip, row or card said it could be
        # pressed (2026-10-31).
        out = [(k, _pointer(v) if k == "className" else v) for k, v in out]
        if not any(k == "className" for k, _ in out):
            out.insert(0, ("className", '"cursor-pointer"'))
        # AND IT IS A BUTTON TO THE KEYBOARD AND A SCREEN READER. A drawn div with
        # a press handler was a "generic" Tab never reached: 4,218 of them on
        # DITANS, every action of the app out of a keyboard's reach (QA DIT-015,
        # 2026-11-05).
        if tag not in _NATIVE:
            have = {k for k, _ in out} | {k for k, v in extra.items() if v}
            out += [(k, v) for k, v in (("role", '"button"'), ("tabIndex", "{0}"), ("onKeyDown", _KEYS))
                    if k not in have]
    return out + [(k, v) for k, v in extra.items() if v]


def _unclipped(classes: str) -> str:
    """A className attribute without `overflow-hidden`, as written."""
    if not classes.startswith('"'):
        return classes
    return '"' + " ".join(c for c in classes[1:-1].split() if c != "overflow-hidden") + '"'


def _pointer(classes: str) -> str:
    """A className attribute with `cursor-pointer` added, as written."""
    if "cursor-" in classes or not classes.startswith('"'):
        return classes
    return '"' + (classes[1:-1] + " cursor-pointer").strip() + '"'


def _cond(expr: str, negate: bool = False) -> str:
    return f"!{expr}" if negate else expr


def _face(node: M.Node) -> tuple:
    """How a node is drawn, whatever its words and whichever picture it shows:
    options of one group with their own icons are drawn alike."""
    return (node.tag, node.attr("className"), node.attr("style"),
            tuple(_face(c) for c in node.children))


def _px(node: M.Node, dim: str) -> float | None:
    m = re.search(rf"(?:^|\s){dim}-\[(\d+(?:\.\d+)?)px\]", node.classes())
    return float(m.group(1)) if m else None


def _is_switch(node: M.Node) -> bool:
    """A track with a knob in it, wider than tall; a check box otherwise."""
    w, h = _px(node, "w"), _px(node, "h")
    return bool(node.children) and w is not None and h is not None and w >= 1.5 * h


_FILL = re.compile(r"bg-\[#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\]")
_LINE = re.compile(r"border-\[#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\]")


def _accent(root: M.Node) -> str | None:
    """The screen's own accent: the strong colour it fills most often."""
    counts: Counter = Counter()
    for node in root.walk():
        for c in node.classes().split():
            m = _FILL.fullmatch(c)
            if not m or len(m.group(1)) != 6:
                continue
            r, g, b = (int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))
            _h, light, sat = colorsys.rgb_to_hls(r, g, b)
            if sat >= 0.4 and 0.2 <= light <= 0.8:
                counts["#" + m.group(1).lower()] += 1
    return counts.most_common(1)[0][0] if counts else None


def _other_state(node: M.Node, drawn_on: bool, accent: str | None) -> M.Node | None:
    """A switch or check box drawn in one state, in the other.

    A DRAWING SHOWS A CONTROL ONCE. Drawn ticked it stayed ticked, drawn off it
    stayed off, whatever the person did: 72 on DITANS, 9 with the other state
    drawn anywhere on their screen (QA DIT-004, 2026-11-05). The other state is
    the drawn one turned over in the drawing's own colour — its fill becomes its
    outline (a check box loses its tick, a switch's track pales and its knob goes
    to the start), or its outline (else the screen's accent) becomes its fill.
    """
    other = copy.deepcopy(node)
    classes = node.classes().split()
    fill = next((c for c in classes if _FILL.fullmatch(c)), None)
    line = next((c for c in classes if _LINE.fullmatch(c)), None)
    switch = _is_switch(node)
    if drawn_on:
        if fill is None:
            return None
        colour = "#" + _FILL.fullmatch(fill).group(1)
        classes = [c for c in classes if c != fill]
        if switch:
            classes.append(f"bg-[{colour}]/25")
        else:
            classes.append("bg-transparent")
            if not any(c == "border" or re.fullmatch(r"border-\[\d+(\.\d+)?px\]", c) for c in classes):
                classes.append("border-[1.5px]")
            if line is None:
                classes.append(f"border-[{colour}]")
            other.children = []
    else:
        colour = "#" + _LINE.fullmatch(line).group(1) if line else accent
        if colour is None:
            return None
        classes = [c for c in classes if c not in (fill, "bg-transparent")] + [f"bg-[{colour}]"]
        if not switch and not other.children:
            other.children = [M.Node(tag="p", id=f"{node.id}.tick", parent=other, body="\u2713", attrs=[
                ("className", '"shrink-0 text-[12px] leading-[16px] font-[600] text-[#ffffff]"')])]
    if switch:
        swap = {"justify-start": "justify-end", "justify-end": "justify-start"}
        if not any(c in swap for c in classes):
            classes.append("justify-start" if drawn_on else "justify-end")
        else:
            classes = [swap.get(c, c) for c in classes]
    other.attrs = [(k, json.dumps(" ".join(classes)) if k == "className" else v) for k, v in other.attrs]
    if not any(k == "className" for k, _ in other.attrs):
        other.attrs.insert(0, ("className", json.dumps(" ".join(classes))))
    return other


class _Writer:
    def __init__(self, plan: _Plan):
        self.plan = plan
        self.first_control = True
        self.accent = _accent(plan.root)

    def _many(self, inp: dict) -> bool:
        slot = self.plan.slots.get(inp.get("form"))
        return bool(slot and _fields(slot).get(inp.get("field"), {}).get("many"))

    def _look_of(self, inp: dict, key: str) -> M.Node | None:
        """The option drawn selected (`on_look`) or not (`off_look`): this
        input's own, else a sibling option's of the same field. Without it, the
        selected look of four of six country chips was their unselected one,
        and picking them showed nothing (DITANS QA D-09)."""
        own = self.plan.nodes.get(str(inp.get(key) or ""))
        if own is not None:
            return own
        for other in self.plan.inputs.values():
            if other.get("form") == inp.get("form") and other.get("field") == inp.get("field") and other.get(key):
                found = self.plan.nodes.get(str(other.get(key)))
                if found is not None:
                    return found
        return None

    def _test(self, inp: dict) -> str:
        """Whether this option is chosen, or this switch on."""
        value = f"props.{inp['form']}.{inp['field']}"
        if inp["kind"] == "toggle":
            return f"!!{value}"
        if self._many(inp):
            return f"({value} ?? []).includes({json.dumps(inp['value'])} as never)"
        return f"{value} === {json.dumps(inp['value'])}"

    def _states(self, inp: dict, n: M.Node) -> tuple[M.Node, M.Node]:
        """The element drawn chosen (on) and not chosen (off)."""
        plan = self.plan
        if inp["kind"] == "choice":
            on, off = self._look_of(inp, "on_look"), self._look_of(inp, "off_look")
            if on is not None and off is not None and _face(on) != _face(off):
                return on, off
            # THE GROUP SAYS WHICH LOOK IS CHOSEN. Given one look, or the same
            # look twice, both branches drew the option the same and picking it
            # showed nothing (DITANS: 30 chip groups, QA 2026-11-05). Among the
            # options drawn two ways, the fewer are the chosen.
            group = [plan.nodes[i] for i, o in plan.inputs.items() if i in plan.nodes and o.get("kind") == "choice"
                     and o.get("form") == inp["form"] and o.get("field") == inp["field"]]
            faces: dict[tuple, list[M.Node]] = {}
            for g in group:
                faces.setdefault(_face(g), []).append(g)
            if len(faces) == 2:
                few, most = sorted(faces.values(), key=len)
                if len(few) < len(most):
                    return few[0], most[0]
                known = on if on is not None else off
                if known is not None:
                    rest = next(g for g in group if _face(g) != _face(known))
                    return (known, rest) if on is not None else (rest, known)
            return on or n, off or n
        on = plan.nodes.get(str(inp.get("on_look") or ""))
        off = plan.nodes.get(str(inp.get("off_look") or ""))
        if on is not None and off is not None and _face(on) != _face(off):
            return on, off
        drawn_on = bool(inp["on"]) if "on" in inp else (on is not None and _face(n) == _face(on))
        # ANOTHER SWITCH OF THE SAME KIND ON THE SCREEN, DRAWN THE OTHER WAY.
        for i, o in plan.inputs.items():
            m = plan.nodes.get(i)
            if m is None or m is n or o.get("kind") != "toggle" or not M.same_kind(m, n) \
                    or (_px(m, "w"), _px(m, "h")) != (_px(n, "w"), _px(n, "h")) or _face(m) == _face(n):
                continue
            if "on" in o and bool(o["on"]) == drawn_on:
                continue
            return (n, m) if drawn_on else (m, n)
        other = _other_state(n, drawn_on, self.accent)
        if other is None:
            return n, n
        return (n, other) if drawn_on else (other, n)

    def press(self, n: M.Node, row: str | None) -> str:
        a = self.plan.actions.get(n.id)
        if a is not None:
            arg = "row" if row and a.get("on") == row else ""
            return f"{{() => props.{a['name']}({arg})}}"
        inp = self.plan.inputs.get(n.id)
        if inp and inp["kind"] == "choice" and self._many(inp):
            have, v = f"(props.{inp['form']}.{inp['field']} ?? [])", json.dumps(inp["value"])
            return (f"{{() => props.{change_handler(inp['form'])}({json.dumps(inp['field'])}, "
                    f"{have}.includes({v} as never) ? {have}.filter((x) => x !== {v}) : [...{have}, {v}])}}")
        if inp and inp["kind"] == "choice":
            return f"{{() => props.{change_handler(inp['form'])}({json.dumps(inp['field'])}, {json.dumps(inp['value'])})}}"
        if inp and inp["kind"] == "toggle":
            return f"{{() => props.{change_handler(inp['form'])}({json.dumps(inp['field'])}, " \
                   f"!props.{inp['form']}.{inp['field']})}}"
        return ""

    def piece(self, n: M.Node, depth: int, row: str | None, done: frozenset = frozenset(),
              child: bool = True, key: bool = False) -> list[str]:
        """``n`` as JSX: a child of an element (``child``) or an expression."""
        plan, pad = self.plan, "  " * depth
        if n.id in plan.skip:
            return []
        if n.id in plan.controls:
            first, self.first_control = self.first_control, False
            return [pad + "{props.controls}"] if first else []

        def wrapped(head: str, inner: list[str], tail: str) -> list[str]:
            return [pad + ("{" if child else "") + head, *inner, pad + tail + ("}" if child else "")]

        show = plan.shows.get(n.id)
        listed = plan.templates.get(n.id)
        # A row's own condition (`row.x`) is asked inside the list, of each row.
        per_row = bool(show) and str(show["when"]).startswith("row.") and listed is not None
        if show and (n.id, "show") not in done and not (per_row and (n.id, "list") not in done):
            inner = self.piece(n, depth + 1, row, done | {(n.id, "show")}, child=False, key=key)
            return wrapped(f"{_cond(show['when'], bool(show.get('not')))} && (", inner, ")")
        if listed and (n.id, "list") not in done:
            source = f"props.{listed['prop']}"
            where = listed.get("where")
            if where:
                source += f".filter((row) => row.{where['field']} === {json.dumps(where['equals'])})"
            inner = self.piece(n, depth + 1, listed["prop"], done | {(n.id, "list")}, child=False, key=True)
            return wrapped(f"{source}.map((row) => (", inner, "))")
        inp = plan.inputs.get(n.id)
        if inp and inp["kind"] in ("choice", "toggle") and (n.id, "look") not in done \
                and _face((states := self._states(inp, n))[0]) != _face(states[1]):
            on, off = states
            test = self._test(inp)
            yes = self.piece(M.relook(n, on, set(plan.values), own_pictures=True), depth + 1, row, done | {(n.id, "look")},
                             child=False)
            no = self.piece(M.relook(n, off, set(plan.values), own_pictures=True), depth + 1, row, done | {(n.id, "look")},
                            child=False)
            return wrapped(f"{test} ? (", [*yes, pad + ") : (", *no], ")")
        lk = plan.looks.get(n.id)
        if lk and (n.id, "look") not in done:
            return wrapped("", self.looks(n, lk, depth + 1, row, done | {(n.id, "look")}, key), "")
        return self.element(n, depth, row, done, key)

    def looks(self, n: M.Node, lk: dict, depth: int, row: str | None, done: frozenset, key: bool) -> list[str]:
        """``n`` in the look its field picks: a chain of the drawn looks."""
        pad = "  " * depth
        f = lk["field"]
        boolean = str(_fields(self.plan.slots[lk["list"]]).get(f, {}).get("type")) == "boolean"
        # A FIELD ALREADY ASKED IS NOT ASKED AGAIN. A row and its pill both
        # drawn by `status`: inside the row's "Expired" branch the pill is the
        # Expired look, and comparing again does not type-check (DITANS A-11).
        decided = next((d[2] for d in done if len(d) == 3 and d[0] == "field" and d[1] == f), None)
        if decided is not None:
            value, drawn = next(((v, d) for v, d in lk["by"] if v == decided), lk["by"][-1])
            if drawn is None:
                return ["  " * depth + "null"]
            return self.piece(M.relook(n, drawn, set(self.plan.values)), depth, row, done, child=False, key=key)
        out: list[str] = []
        for i, (value, drawn) in enumerate(lk["by"]):
            body = ["  " * (depth + 1) + "null"] if drawn is None else \
                self.piece(M.relook(n, drawn, set(self.plan.values)), depth + 1, row,
                           done | {("field", f, value)}, child=False, key=key)
            if i == len(lk["by"]) - 1:
                out += [pad + "(", *body, pad + ")"]
            else:
                test = (f"row.{f}" if value.lower() == "true" else f"!row.{f}") if boolean \
                    else f"row.{f} === {json.dumps(value)}"
                out += [pad + f"{test} ? (", *body, pad + ") :"]
        return out

    def element(self, n: M.Node, depth: int, row: str | None, done: frozenset, key: bool) -> list[str]:
        plan, pad = self.plan, "  " * depth
        values = plan.values.get(n.id) or []
        press = self.press(n, row)
        extra = {"key": "{row.id}" if key else "", "onClick": press}
        state = plan.inputs.get(n.id)
        if press and state and state["kind"] == "toggle":
            extra["role"] = '"switch"' if _is_switch(n) else '"checkbox"'
            extra["aria-checked"] = "{" + self._test(state) + "}"
        elif press and state and state["kind"] == "choice":
            extra["aria-pressed"] = "{" + self._test(state) + "}"
        unit = n.unit()
        if unit.is_component:
            plan.components.add(unit.tag)
            u_attrs = list(unit.attrs)
            for v in values:
                u_attrs = [(k, "{" + v["expr"] + "}" if k == v["prop"] else val) for k, val in u_attrs]
            typed = plan.inputs.get(n.id)
            if typed and typed["kind"] in ("text", "select") and typed.get("prop"):
                form, field_name, word = typed["form"], typed["field"], typed["prop"]
                # THE DRAWN WORDS ARE AN EXAMPLE: a hint in an empty field, never a
                # choice of their own. A select offers what its field declares and
                # starts on none; with nothing declared it is typed into.
                drawn = M.prop_value(unit, word)
                declared = _fields(plan.slots[form])[field_name].get("options") or []
                options = f", options: {json.dumps(declared)}" if typed["kind"] == "select" and declared else ""
                hint = f", placeholder: {json.dumps(drawn)}" if drawn and (not options or typed.get("placeholder")) else ""
                u_attrs.append((f"{word}Input", "{{ value: String(props." + form + "." + field_name + ' ?? ""), '
                                "onChange: (v: string) => props." + change_handler(form) + "("
                                + json.dumps(field_name) + ", v)" + hint + options + " }}"))
            comp = f"<{unit.tag}{_attrs(u_attrs)} />"
            if unit is n:
                if not press and not key:
                    return [pad + comp]
                return [pad + f'<div{_attrs(_with([("className", chr(34) + "contents" + chr(34))], **extra))}>'
                        + comp + "</div>"]
            return [pad + f"<{n.tag}{_attrs(_with(n.attrs, n.tag, **extra))}>{comp}</{n.tag}>"]
        if n.tag == "img":
            src = next((v["expr"] for v in values if v["prop"] == "src"), None)
            attrs = _with(n.attrs, "img", **extra, **({"src": "{" + src + "}"} if src else {}))
            return [pad + f"<img{_attrs(attrs)} />"]
        inp = plan.inputs.get(n.id)
        if inp and inp["kind"] in ("text", "select") and n.body is not None:
            return [pad + self.field(n, inp, extra)]
        if n.body is not None:
            body = "{" + values[0]["expr"] + "}" if values else n.body
            return [pad + f"<{n.tag}{_attrs(_with(n.attrs, n.tag, **extra))}>{body}</{n.tag}>"]
        inner = [line for c in n.children for line in self.piece(c, depth + 1, row, done)]
        attrs = n.attrs
        if re.search(r"(^|\s)h-\[", n.classes()) and any(d.id in plan.controls for d in n.walk() if d is not n):
            # THE BAR THAT HOLDS THE ACCOUNT MENU DOES NOT CLIP. Auto layout draws
            # every frame `overflow-hidden`; the top bar holding the bell and the
            # account then cut their menus off at its bottom edge (DITANS). Only a
            # box of fixed height ends above the menu — the shell and its columns
            # keep clipping, so a wide page still does not scroll the window.
            attrs = [(k, _unclipped(v) if k == "className" else v) for k, v in attrs]
        head = f"<{n.tag}{_attrs(_with(attrs, n.tag, **extra))}"
        return [pad + head + ">", *inner, pad + f"</{n.tag}>"] if inner else [pad + head + " />"]

    def field(self, n: M.Node, inp: dict, extra: dict) -> str:
        """A drawn value as the input that sets it, in the text's own look."""
        form, name = inp["form"], inp["field"]
        # Full width of where the text was, and no control of the browser's own
        # drawn over the drawing's (a select's arrow beside the drawn chevron).
        classes = (n.classes() + " w-full bg-transparent outline-none border-0 p-0 m-0 min-w-0 appearance-none").strip()
        attrs = [(k, v) for k, v in n.attrs if k not in ("className",)]
        value = f"{{props.{form}.{name} ?? \"\"}}"
        change = f"{{(e) => props.{change_handler(form)}({json.dumps(name)}, e.target.value)}}"
        drawn = M.plain(n)
        declared = _fields(self.plan.slots[form])[name].get("options") or []
        # THE DRAWN WORDS ARE AN EXAMPLE, NOT A CHOICE. A field drawn with a
        # chevron became a select of the one value the designer typed: an empty
        # field showed "Egyptian" as chosen and nothing else could be picked
        # (DITANS: 211 selects, QA DIT-012, 2026-11-05). A select offers what its
        # field declares and starts on none; with nothing declared it is typed
        # into, the drawn words its hint.
        if inp["kind"] == "select" and declared:
            base = _with([("className", json.dumps(classes)), *attrs], "select", onClick=extra.get("onClick", ""))
            first = drawn if inp.get("placeholder") and drawn else "Choose\u2026"
            opts = f"<option value=\"\">{{{json.dumps(first)}}}</option>" + "".join(
                f"<option value={{{json.dumps(o)}}}>{{{json.dumps(o)}}}</option>" for o in declared)
            return (f"<select{_attrs(base)} value={value} onChange={change}>{opts}</select>")
        base = _with([("className", json.dumps(classes)), *attrs], "input", onClick=extra.get("onClick", ""))
        # As an expression: a JSX attribute string does not read `\u2026`.
        hint = f" placeholder={{{json.dumps(drawn)}}}" if drawn else ""
        return f"<input{_attrs(base)} value={value}{hint} onChange={change} />"


def _sample(plan: _Plan, contract: dict) -> dict[str, Any]:
    """The drawing's own content, in the contract's shape."""
    out: dict[str, Any] = {}

    def coerce(slot: dict, name: str, value: Any) -> Any:
        f = _fields(slot).get(name) or {}
        if str(f.get("type")) == "boolean":
            return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "yes", "on", "1")
        if str(f.get("type")) == "enum" and isinstance(value, str) and value:
            # The options are the values the drawing shows.
            options = f.setdefault("options", [])
            if value not in options:
                options.append(value)
        return value

    def alike(a: M.Node, b: M.Node) -> int:
        return sum(x.attr("className") == y.attr("className") and x.tag == y.tag for x, y in zip(a.walk(), b.walk()))

    def read(rec: dict, listed: dict, rid: str) -> None:
        """One drawn row's content, through its list entry's template."""
        template, drawn = plan.nodes[listed["rows"][0]], plan.nodes[rid]
        for t in template.walk():
            for v in plan.values.get(t.id) or []:
                m = _PATH.match(v["expr"])
                if not m or m.group(1) != "row":
                    continue
                there = M.counterpart(template, drawn, t)
                if there is not None:
                    rec[m.group(2)] = M.prop_value(there, v["prop"]) if there.unit().is_component else M.plain(there)
            show = plan.shows.get(t.id)
            m = _PATH.match(show["when"]) if show else None
            if m and m.group(1) == "row":
                rec[m.group(2)] = not show.get("not")
        for lk in listed.get("looks") or []:
            if lk["field"] in rec:
                continue
            here = drawn if lk["node"] == template.id else M.counterpart(template, drawn, plan.nodes[lk["node"]])
            if here is None:
                # Not drawn in this row: the value whose look draws nothing there.
                absent = [v for v, d in lk["by"] if d is None]
                if len(absent) == 1:
                    rec[lk["field"]] = absent[0]
                continue
            # The value whose drawn look this row's element has.
            drawn_looks = [(v, d) for v, d in lk["by"] if d is not None]
            exact = [v for v, d in drawn_looks if d is here or M.look(d) == M.look(here)]
            if exact or drawn_looks:
                rec[lk["field"]] = exact[0] if exact else max(drawn_looks, key=lambda vd: alike(vd[1], here))[0]

    by_prop: dict[str, list[dict]] = {}
    for listed in plan.lists:
        by_prop.setdefault(listed["prop"], []).append(listed)
    for prop, entries in by_prop.items():
        slot = plan.slots.get(prop)
        if slot is None:
            continue
        rows: list[dict] = []
        # A TABLE DRAWN BY COLUMN is one entry per column: the n-th cell of
        # each is the n-th row.
        columns = [e for e in entries if not e.get("where")]
        for i in range(max((len(e["rows"]) for e in columns), default=0)):
            rec: dict[str, Any] = {"id": str(i + 1)}
            for e in columns:
                if i < len(e["rows"]):
                    read(rec, e, e["rows"][i])
            rows.append(rec)
        # …and a menu drawn under headings, one entry per heading.
        for e in entries:
            if e.get("where"):
                for rid in e["rows"]:
                    rec = {"id": str(len(rows) + 1)}
                    read(rec, e, rid)
                    rec[str(e["where"]["field"])] = str(e["where"]["equals"])
                    rows.append(rec)
        for rec in rows:
            for name, f in _fields(slot).items():
                rec.setdefault(name, False if str(f.get("type")) == "boolean" else "")
                rec[name] = coerce(slot, name, rec[name])
        out[prop] = rows

    def put(expr: str, value: Any) -> None:
        m = _PATH.match(expr)
        if not m or m.group(1) != "props":
            return
        slot = plan.slots.get(m.group(2))
        if slot is None:
            return  # left out of the contract: nothing reads it
        if not m.group(3) and slot.get("kind") in ("record", "form"):
            return  # a record asked of itself is always given
        if m.group(3):
            rec = out.setdefault(m.group(2), {"id": "1"} if slot.get("kind") == "record" else {})
            rec[m.group(3)] = coerce(slot, m.group(3), value)
        else:
            out[m.group(2)] = value

    for nid, values in plan.values.items():
        n = plan.nodes[nid]
        for v in values:
            put(v["expr"], M.prop_value(n, v["prop"]) if n.unit().is_component else M.plain(n))
    # A FORM STARTS EMPTY. What the designer typed into a field, the chip drawn
    # chosen and the box drawn ticked are examples: taken as the sample, the page
    # writer started every new form with them — a new account's profile already
    # "Staff Nurse" at "Kasr Al Ainy Hospital", "Female" chosen (DITANS QA DIT-009,
    # DIT-013, 2026-11-05). The drawn words are each field's hint instead
    # (`_Writer.field`); a form's fields are given their empty values below.
    for nid, show in plan.shows.items():
        if nid not in plan.scope:
            put(show["when"], not show.get("not"))
    for name, slot in plan.slots.items():
        if slot.get("kind") in ("record", "form"):
            rec = out.setdefault(name, {"id": "1"} if slot.get("kind") == "record" else {})
            for f, spec in _fields(slot).items():
                rec.setdefault(f, [] if spec.get("many") else False if str(spec.get("type")) == "boolean" else "")
        elif slot.get("kind") == "list":
            out.setdefault(name, [])
    return out


def apply(static: str, reply: dict, name: str, *, components: dict[str, list[str]] | None = None,
          children: bool = False) -> tuple[dict[str, Any] | None, list[str]]:
    """``({"code", "contract", "sample"}, [])`` for a reply that binds the
    drawing, else ``(None, problems)`` in words the model can act on."""
    root = M.parse(static)
    contract = json.loads(json.dumps(reply.get("contract") or {"data": [], "actions": []}))
    contract.setdefault("data", [])
    contract.setdefault("actions", [])
    plan, problems = _resolve(root, {**reply, "contract": contract}, children=children)
    if problems:
        return None, problems
    _shown_as_words(plan)
    _guard_records(plan)
    writer = _Writer(plan)
    body = writer.piece(root, 2, None, child=False)
    imports = "".join(f'import {c} from "./{c}";\n' for c in sorted(plan.components)
                      if components is None or c in components)
    code = (f'"use client";\nimport type * as React from "react";\n{imports}\n'
            f"export default function {name}(props: {name}Props) {{\n  return (\n"
            + "\n".join(body) + "\n  );\n}\n")
    if "present(props." in code:
        code += PRESENT
    for a in contract["actions"]:
        a.pop("nodes", None)
    # WHAT NOTHING READS IS NOT IN THE CONTRACT. An action with no element to
    # press, a slot nothing shows: the drawing has no such thing, and asking
    # again three rounds for it failed screens that were right (DITANS
    # wzml1sa6, 2026-10-29). A form nobody types into is a record.
    missing = set(unused(code, contract))
    for slot in contract["data"]:
        if slot.get("kind") == "form" and change_handler(slot["name"]) in missing:
            missing.discard(change_handler(slot["name"]))
            if slot["name"] not in missing:
                slot["kind"] = "record"
    contract["actions"] = [a for a in contract["actions"] if a.get("name") not in missing]
    contract["data"] = [d for d in contract["data"] if d.get("name") not in missing]
    plan.slots = {str(d["name"]): d for d in contract["data"]}
    # Read before the type is written: an enum's options grow by what is drawn.
    sample = _sample(plan, contract)
    return {"code": finish(name, code, contract, children=children), "contract": contract,
            "sample": sample}, []


def user_prompt(name: str, static: str, *, heading: str, links: list[dict], components: dict[str, list[str]],
                feedback: str = "") -> str:
    shared = "\n".join(f"- `{n}` — its words: {', '.join(keys)}" for n, keys in components.items())
    leads = "\n".join(f"- “{l.get('via') or '?'}” → {l.get('to_name') or l.get('to')} "
                      f"(frame {l.get('to')}, {l.get('kind')})" for l in links)
    out = [f"The screen: “{heading}”. The view is `{name}`.",
           "The drawn frame is attached. Its markup, every element numbered:\n```\n"
           + M.numbered(M.parse(static)) + "\n```"]
    if shared:
        out.append("Shared components the markup uses (their words are props — bind one with `prop`):\n" + shared)
    if leads:
        out.append("Where its prototype links lead (the words pressed → the screen):\n" + leads)
    if feedback:
        out.append("Your previous answer was refused. Fix every one of these and keep what was right:\n" + feedback)
    return "\n\n".join(out)


def parameterise(client: Any, name: str, static: str, *, heading: str, image: str | None,
                 links: list[dict], components: dict[str, list[str]],
                 usage: list | None = None, children: bool = False, retry: Any = None) -> dict[str, Any]:
    """``{"code", "contract", "sample", "rounds"}`` for one screen. Raises
    ValueError with the last findings when no round comes back right; every
    round's spend is in ``usage`` either way. A round after a refusal is asked
    of ``retry`` when given (the same model thinking harder)."""
    import time

    feedback = ""
    system = SYSTEM + (_SHELL if children else "")
    for round_ in range(1, ROUNDS + 1):
        user = user_prompt(name, static, heading=heading, links=links, components=components, feedback=feedback)
        t0 = time.monotonic()
        kwargs: dict[str, Any] = {"system": system, "user": user, "schema": _schema(children)}
        if image and getattr(client, "accepts_images", False):
            kwargs["images"] = [image]
        reply = (retry if feedback and retry is not None else client)(**kwargs)
        if usage is not None and getattr(reply, "usage", None) is not None:
            usage.append((reply.usage, time.monotonic() - t0))
        try:
            body = json.loads(getattr(reply, "text", reply))
        except (json.JSONDecodeError, TypeError) as exc:
            feedback = f"- the reply was not valid JSON ({exc})"
            continue
        out, problems = apply(static, body if isinstance(body, dict) else {}, name,
                              components=components, children=children)
        if out is not None:
            return {**out, "rounds": round_}
        feedback = "\n".join(f"- {p}" for p in problems[:20])
    raise ValueError(f"{name}: the view did not come back right in {ROUNDS} rounds — {feedback[:600]}")


def finish(name: str, code: str, contract: dict, *, children: bool = False) -> str:
    """The view's file with its generated Props type in place."""
    typed = props_type(name, contract, children=children, code=code)
    code = code.lstrip()
    head = ""
    for directive in ('"use client";', "'use client';"):
        if code.startswith(directive):
            head, code = directive + "\n", code[len(directive):].lstrip()
            break
    if "import type * as React" not in code and "import * as React" not in code:
        code = 'import type * as React from "react";\n' + code
    lines = code.split("\n")
    at = 0
    while at < len(lines) and (lines[at].startswith("import ") or not lines[at].strip()):
        at += 1
    return (head or '"use client";\n') + "\n".join(lines[:at]).rstrip() + "\n\n" + typed + "\n" + "\n".join(lines[at:])

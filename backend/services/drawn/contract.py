"""What a drawn view needs: its contract, its props type, and a digest of
every contract for the steps that generate the data model and the processes.

The contract (`DrawnContract` in the Blueprint) is the one statement of the
view's needs; the TypeScript props type is generated from it, never written
by hand or by a model, so the two cannot disagree.

WHAT A VIEW IS GIVEN IS WHAT IT SHOWS. A drawn table cell says "10 (7 used)"
and "renews 1 Mar 2027": the view displays words, so its fields are strings
the binder formats from the records. An `enum` stays a union of the drawn
values (a view picks a pill's colour by it) and a `boolean` stays a boolean
(a toggle is drawn on or off); every row has an `id` to key it and to hand
back to a handler.
"""
from __future__ import annotations

import json
import re
from typing import Any

#: Field types the view receives as booleans; every other non-enum field is
#: a display string.
_BOOLEAN = {"boolean"}


def _ts_field(field: dict) -> str:
    kind = str(field.get("type") or "string")
    if kind == "enum" and field.get("options"):
        return " | ".join(json.dumps(str(o)) for o in field["options"])
    if kind in _BOOLEAN:
        return "boolean"
    return "string"


def _ts_object(fields: list[dict], *, with_id: bool) -> str:
    lines = ["id: string"] if with_id else []
    for f in fields:
        if not isinstance(f, dict) or not f.get("name") or f.get("name") == "id":
            continue
        optional = "" if with_id or f.get("required") else "?"
        lines.append(f"{f['name']}{optional}: {_ts_field(f)}")
    return "{ " + "; ".join(lines) + " }"


def _row(slot: dict) -> str:
    return _ts_object(slot.get("fields") or [], with_id=True)


def props_type(name: str, contract: dict, *, children: bool = False) -> str:
    """``export type <Name>Props = {...}`` from the contract."""
    lines: list[str] = []
    slots = {str(s.get("name")): s for s in contract.get("data") or [] if isinstance(s, dict) and s.get("name")}
    for slot in slots.values():
        kind = str(slot.get("kind") or "value")
        if kind == "list":
            lines.append(f"  {slot['name']}: Array<{_row(slot)}>;")
        elif kind == "record":
            # A RECORD THE DRAWING SHOWS IS ALWAYS THERE. The drawing shows a
            # tenant selected, and its view reads `props.selectedTenant.code`
            # as drawn; typed optional, the page fed `undefined` until one was
            # chosen and the drawn page crashed the moment it had rows
            # (d6drawn, 2026-10-28). Required, the page must give it one.
            lines.append(f"  {slot['name']}: {_row(slot)};")
        elif kind == "form":
            lines.append(f"  {slot['name']}: {_ts_object(slot.get('fields') or [], with_id=False)};")
            lines.append(f"  {change_handler(slot['name'])}(field: string, value: string | boolean): void;")
        else:
            lines.append(f"  {slot['name']}?: {_ts_field({'type': slot.get('type') or 'string', 'options': slot.get('options')})};")
    for action in contract.get("actions") or []:
        if not isinstance(action, dict) or not action.get("name"):
            continue
        target = slots.get(str(action.get("on") or ""))
        arg = ""
        if target is not None and str(target.get("kind")) == "list":
            arg = f"row: {_row(target)}"
        lines.append(f"  {action['name']}({arg}): void;")
    if children:
        # THE SHELL HOLDS THE PAGE, and the application's own controls (its
        # notifications, the account menu) where the drawing puts its bell.
        lines.append("  children?: React.ReactNode;")
        lines.append("  controls?: React.ReactNode;")
    return f"export type {name}Props = {{\n" + "\n".join(lines) + "\n};\n"


def change_handler(form: str) -> str:
    """The handler a form's inputs call: `promoForm` → `onPromoFormChange`."""
    return "on" + form[:1].upper() + form[1:] + "Change"


def names(contract: dict) -> list[str]:
    """Every prop the contract gives the view."""
    out = []
    for slot in contract.get("data") or []:
        if isinstance(slot, dict) and slot.get("name"):
            out.append(str(slot["name"]))
            if slot.get("kind") == "form":
                out.append(change_handler(str(slot["name"])))
    out += [str(a["name"]) for a in contract.get("actions") or [] if isinstance(a, dict) and a.get("name")]
    return out


def unused(code: str, contract: dict) -> list[str]:
    """Props the contract declares that the code never reads."""
    return [n for n in names(contract) if not re.search(r"\bprops\." + re.escape(n) + r"\b", code)]


def digest(doc: dict, *, limit: int = 60000) -> str:
    """Every drawn screen's contract, for the data model, the records' fields,
    the processes and the access rules to be written against — "" when the
    application has none."""
    views = [v for v in doc.get("drawnViews") or [] if isinstance(v, dict) and v.get("kind") == "screen"
             and v.get("status") != "DEPRECATED"]
    if not views:
        return ""
    frames = {}
    for source in doc.get("designSources") or []:
        for f in source.get("frames") or []:
            frames[str(f.get("nodeId"))] = str(f.get("shows") or f.get("name") or "")
    lines = []
    for view in views:
        contract = view.get("contract") or {}
        lines.append(f"## {frames.get(str(view.get('frame') or '').split('/')[-1]) or view.get('name')}  "
                     f"(view {view.get('name')})")
        for slot in contract.get("data") or []:
            fields = ", ".join(
                f"{f.get('name')}:{f.get('type')}" + (f"[{'|'.join(map(str, f.get('options') or []))}]"
                                                    if f.get("options") else "")
                + ("*" if f.get("required") else "")
                for f in slot.get("fields") or [] if isinstance(f, dict))
            lines.append(f"- {slot.get('kind')} `{slot.get('name')}` “{slot.get('label') or ''}”"
                         + (f": {fields}" if fields else f": {slot.get('type') or 'string'}"))
        for action in contract.get("actions") or []:
            target = frames.get(str(action.get("target") or "").split("/")[-1], "")
            lines.append(f"- action `{action.get('name')}` “{action.get('label') or ''}” ({action.get('kind')}"
                         + (f" on {action.get('on')}" if action.get("on") else "")
                         + (f" → {target}" if target else "") + ")")
    text = "\n".join(lines)
    return text[:limit] + ("\n… (more screens, the same kind of content)" if len(text) > limit else "")


DIGEST_PREAMBLE = (
    "\n\nTHE DESIGN IS ALREADY BUILT AS REACT VIEWS, and this is what each one shows and does — its "
    "CONTRACT. Your answer is what backs them: every list, record and form below is records of some "
    "type with these fields (a field marked * is required; [a|b] are the values the drawing shows), and "
    "every action is something the application does. Name things as the screens do. What a screen "
    "only displays as a figure (a count, a total, a 'used of' share) may be computed from records "
    "rather than stored.\n\n"
)

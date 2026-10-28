"""A converted screen's example content, turned into props — its contract.

`tsx` draws a frame exactly, with the designer's example content written in:
"MedStaff Partners", "7 of 10", five table rows. What of that is data, what
is fixed copy, which rows are one list and what each button does is a
judgement about meaning, so it is a model's — but a model's that may not
touch the drawing. It is shown the frame and its markup, and returns the same
markup with the example content replaced by props, the repeated rows by one
`.map`, the buttons calling handlers and the inputs controlled; with the
CONTRACT that says what each prop is; and with the drawing's own values in
that shape (`sample`).

What it returns is checked, not trusted (`check`): every class the drawing
was converted with is still there, every prop the contract declares is read,
and nothing loads data. A reply that fails is sent back with the findings.
"""
from __future__ import annotations

import json
import re
from typing import Any

from services.drawn.contract import change_handler, props_type, unused

#: Rounds a screen gets to come back right.
ROUNDS = 3
#: The share of the drawing's distinct classes a view must keep. A table
#: collapsed to one row and a `.map` keeps every row's classes; what may go is
#: a drawn example the contract makes conditional (an empty state not shown).
KEEP = 0.95

_FIELD_TYPES = ["string", "text", "number", "money", "percent", "date", "datetime", "boolean", "enum",
                "email", "phone", "url", "image", "id"]

REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["contract", "sample_json", "code"],
    "properties": {
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
                                "required": {"type": "boolean"},
                            }}},
                    }}},
                "actions": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["name", "label", "kind"],
                    "properties": {
                        "name": {"type": "string"}, "label": {"type": "string"},
                        "kind": {"type": "string", "enum": ["navigate", "open", "submit", "run"]},
                        "target": {"type": "string"}, "on": {"type": "string"},
                    }}},
            },
        },
        "sample_json": {"type": "string",
                        "description": "The drawing's own content in the contract's shape, as JSON: every row it shows."},
        "code": {"type": "string", "description": "The view's file, without the Props type (it is generated)."},
    },
}

SYSTEM = """You turn one drawn screen, already converted to React markup, into a view that takes its content as props.

THE MARKUP IS THE DESIGN AND YOU DO NOT CHANGE IT. Keep every element, every className, every style, every
image and the nesting exactly. You do four things to it and nothing else:

1. EXAMPLE CONTENT BECOMES PROPS. What would be different for another record or another day — names, numbers,
   dates, amounts, statuses, counts, the rows of a table, the cards of a list, a selected record's details, the
   values in an input — is read from props. What is the same whatever the data — headings, column headers,
   labels, helper text, button words, the rules and notes the screen states — stays written as it is.
2. REPEATED ROWS BECOME ONE LIST. Rows, cards or chips of one structure repeated as siblings become
   `props.x.map((row) => …)` over a `list` prop, keeping ONE row's markup with `key={row.id}`. Rows of one
   shape that each name a different thing (settings, entitlements, key/value lines, a checklist) are ONE list
   with `label` and `value` fields — never one field per row. A row's action names the list in `on`. Where rows of
   one list are drawn in different looks (a status pill green on one, amber on another), the look follows an
   `enum` field: `row.status === "Active" ? <the green one> : <the amber one>` — both drawn looks kept.
3. EVERY PRESSABLE THING CALLS A HANDLER. A button, a row's action, a tab, a link: `onClick={() => props.onX()}`,
   or `props.onX(row)` on a row. The handler's name is the words on it: "New tenant" → `onNewTenant`.
   `navigate` goes to another screen, `open` opens a dialog, drawer or tab of this one, `submit` sends a form,
   `run` does something to a record. Give `target` when the screen's links (below) say where it leads.
4. INPUTS ARE CONTROLLED. An input, select, checkbox or chip choice the person sets is a field of a `form`
   prop: `value={props.f.code}` and `onChange={(e) => props.onFChange("code", e.target.value)}` (the change
   handler is always `on<Form>Change`, generated for you); a chip choice is `props.f.market === "Egypt"` for the
   selected look and `props.onFChange("market", "Egypt")` on press.

THE CONTRACT says what every prop is: `data` (list / record / form / value, each field with the type the
drawing shows — a date, money, an enum with the drawn options) and `actions`. Every prop you read is in it and
everything in it is read. Names are camelCase; handlers are `on` + PascalCase.

THE SAMPLE is the drawing's own content in the contract's shape — every row it draws, every value — so the view
renders exactly as drawn before there is data. Every row has an `id` ("1", "2", …). Values are what the view
displays, as drawn ("7 of 10", "1 Mar 2027"), except enums (one of the options) and booleans.

THE FILE: start with `"use client";` and `import type * as React from "react";`, import shared components only
from the paths given, and `export default function <Name>(props: <Name>Props)`. Do NOT write the Props type — it
is generated from your contract. No data loading, no fetch, no state beyond what the drawing shows open (a
dialog the screen draws open is shown when its prop says so)."""


def _class_set(code: str) -> set[str]:
    return set(re.findall(r'className="([^"]*)"', code))


def check(static: str, code: str, contract: dict, name: str) -> list[str]:
    """What is wrong with a reply, in words the writer can act on."""
    problems: list[str] = []
    drawn = _class_set(static)
    kept = _class_set(code)
    # A look chosen by a field (`row.status === "Active" ? "…" : "…"`) keeps its
    # classes inside an expression: every drawn class string still written
    # anywhere in the file counts as kept.
    quoted = set(re.findall(r'"([^"\n]*)"', code)) | set(re.findall(r"'([^'\n]*)'", code))
    if drawn:
        lost = sorted(drawn - kept - quoted, key=len)
        if len(drawn & (kept | quoted)) / len(drawn) < KEEP:
            problems.append(f"the drawing's markup was changed: {len(lost)} of its {len(drawn)} distinct classNames "
                            f"are gone (e.g. {lost[:4]}) — keep every element and class exactly")
        added = sorted(kept - drawn)
        if added:
            problems.append(f"classNames the drawing does not have: {added[:4]} — change content, not looks")
    missing = unused(code, contract)
    if missing:
        problems.append("the contract declares props the view never reads: " + ", ".join(missing[:10]))
    if not re.search(r"export\s+default\s+function\s+" + re.escape(name) + r"\s*\(\s*props\s*:\s*"
                     + re.escape(name) + r"Props\s*\)", code):
        problems.append(f"the file must `export default function {name}(props: {name}Props)`")
    if re.search(r"export\s+type\s+" + re.escape(name) + r"Props\b", code):
        problems.append(f"do not write `{name}Props` — it is generated from the contract")
    if re.search(r"\bfetch\(|useEffect\(", code):
        problems.append("a view loads nothing and runs no effects: its content is its props")
    for slot in contract.get("data") or []:
        if slot.get("kind") == "form" and not re.search(r"\bprops\." + change_handler(slot["name"]) + r"\b", code):
            problems.append(f"the form `{slot['name']}` is never changed — its inputs call "
                            f"props.{change_handler(slot['name'])}(field, value)")
    return problems


def user_prompt(name: str, static: str, *, heading: str, links: list[dict], components: dict[str, list[str]],
                feedback: str = "") -> str:
    shared = "\n".join(f"- `{n}` from \"./{n}\" — props: {', '.join(keys)}" for n, keys in components.items())
    leads = "\n".join(f"- “{l.get('via') or '?'}” → {l.get('to_name') or l.get('to')} "
                      f"(frame {l.get('to')}, {l.get('kind')})" for l in links)
    out = [f"The screen: “{heading}”. The view is `{name}`.",
           "The drawn frame is attached. Its markup, as converted:\n```tsx\n" + static + "\n```"]
    if shared:
        out.append("Shared components the markup already uses (keep using them; their props are words — pass "
                   "a prop expression where the words are data):\n" + shared)
    if leads:
        out.append("Where its prototype links lead (the words pressed → the screen):\n" + leads)
    if feedback:
        out.append("Your previous reply was refused. Fix every one of these and keep what was right:\n" + feedback)
    return "\n\n".join(out)


def parameterise(client: Any, name: str, static: str, *, heading: str, image: str | None,
                 links: list[dict], components: dict[str, list[str]],
                 usage: list | None = None, children: bool = False) -> dict[str, Any]:
    """``{"code", "contract", "sample", "rounds"}`` for one screen. Raises
    ValueError with the last findings when no round comes back right."""
    import time

    feedback = ""
    for round_ in range(1, ROUNDS + 1):
        user = user_prompt(name, static, heading=heading, links=links, components=components, feedback=feedback)
        t0 = time.monotonic()
        kwargs: dict[str, Any] = {"system": SYSTEM, "user": user, "schema": REPLY_SCHEMA}
        if image and getattr(client, "accepts_images", False):
            kwargs["images"] = [image]
        reply = client(**kwargs)
        if usage is not None and getattr(reply, "usage", None) is not None:
            usage.append((reply.usage, time.monotonic() - t0))
        try:
            body = json.loads(getattr(reply, "text", reply))
            sample = json.loads(body.get("sample_json") or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            feedback = f"- the reply was not valid JSON ({exc})"
            continue
        code, contract = str(body.get("code") or ""), body.get("contract") or {"data": [], "actions": []}
        problems = check(static, code, contract, name)
        if not problems:
            return {"code": finish(name, code, contract, children=children), "contract": contract,
                    "sample": sample if isinstance(sample, dict) else {}, "rounds": round_}
        feedback = "\n".join(f"- {p}" for p in problems)
    raise ValueError(f"{name}: the view did not come back right in {ROUNDS} rounds — {feedback[:600]}")


def finish(name: str, code: str, contract: dict, *, children: bool = False) -> str:
    """The view's file with its generated Props type in place."""
    typed = props_type(name, contract, children=children)
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

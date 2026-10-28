"""A drawn page, attached to its data and processes without touching the drawing.

A page built from a design held as the specification is the drawn views of
its frames (`drawnViews`): its main frame, and the frames of its dialogs,
tabs, steps and states (`pages[].frames`). Those files are the page's
`parts`, as converted, and are never written here. What the binder writes is
the rest of the page:

* `load.ts` — reads the records the views show, through the app's typed SDK;
* `view.tsx` — shows one drawn view at a time (the main one, or the dialog,
  tab, step or state a person has opened) and gives it its props: the
  records formatted as the drawing displays them, each action wired — to
  another page (`navigate`), to one of this page's other views (`open`), or to
  a process (`submit`, `run`).

WHAT THE VIEWS NEED IS CHECKED, NOT HOPED FOR. Every prop is typed by the
contract, so a prop not given, or given the wrong shape, does not compile; an
action with no process behind it, or data no record holds, comes back as
`needs` and is added (a field to its record, a process to the application)
before the page is written again. A drawing is never bound to nothing.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

#: Rounds a page gets to bind and compile.
ROUNDS = 3

BIND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rationale", "load", "view", "needs_fields", "needs_workflows", "seed"],
    "properties": {
        "rationale": {"type": "string", "description": "One or two sentences: how the drawn props are fed."},
        "load": {"type": "string", "description": "The full contents of load.ts."},
        "view": {"type": "string", "description": "The full contents of view.tsx — no markup of its own."},
        "needs_fields": {
            "type": "array",
            "description": "Data a drawn view shows that no record holds yet.",
            "items": {"type": "object", "additionalProperties": False,
                      "required": ["entity", "name", "type", "label"],
                      "properties": {"entity": {"type": "string"}, "name": {"type": "string"},
                                     "type": {"type": "string"}, "label": {"type": "string"}}}},
        "needs_workflows": {
            "type": "array", "items": {"type": "string"},
            "description": "An action a drawn view offers that no process does, in a sentence each."},
        "seed": {
            "type": "string",
            "description": "JSON: {EntityName: [rows]} — the drawing's own example content as records, field "
                           "names as the entities have them, so the app first opens looking as drawn."},
    },
}


class NeedsFields(RuntimeError):
    """The views show data no record holds; carries the fields to add."""

    def __init__(self, fields: list[dict]):
        self.fields = [f for f in fields if isinstance(f, dict) and f.get("entity") and f.get("name")]
        super().__init__("needs fields that do not exist yet: "
                         + ", ".join(f"{f['entity']}.{f['name']}" for f in self.fields))


def _screens(doc: dict) -> dict[str, dict]:
    return {str(v.get("key")): v for v in doc.get("drawnViews") or []
            if isinstance(v, dict) and v.get("kind") == "screen" and v.get("status") != "DEPRECATED"}


def views_of(doc: dict, page: dict) -> list[tuple[str, str, dict]]:
    """``(as, label, row)`` for every drawn view of a page: its main frame's
    first (`as` = "main"), then its other frames in the order listed."""
    screens = _screens(doc)
    out = []
    main = screens.get(str(page.get("figmaFrame") or ""))
    if main is None:
        return []
    out.append(("main", str(page.get("name") or ""), main))
    for entry in page.get("frames") or []:
        if isinstance(entry, dict) and str(entry.get("frame") or "") in screens:
            out.append((str(entry.get("as") or "state"), str(entry.get("label") or ""), screens[str(entry["frame"])]))
    return out


def applies(doc: dict, page: dict) -> bool:
    """Whether a page is a drawn one: its main frame has a converted view."""
    return bool(views_of(doc, page))


def parts_of(doc: dict, page: dict) -> dict[str, str]:
    """The page's parts: its drawn views and the shared components they use,
    as converted. Never edited by the binder — these are the drawing."""
    components = {str(v.get("name")): str(v.get("code")) for v in doc.get("drawnViews") or []
                  if isinstance(v, dict) and v.get("kind") == "component"}
    parts: dict[str, str] = {}
    for _as, _label, row in views_of(doc, page):
        parts[str(row["name"])] = str(row["code"])
    for name, code in components.items():
        if any(f'from "./{name}"' in code_ for code_ in parts.values()):
            parts[name] = code
    return parts


def _targets(doc: dict) -> dict[str, dict]:
    """``{frame ref: page}`` — where a navigate action leads."""
    from services.blueprint.page_planner import page_frames
    out = {}
    for page in doc.get("pages") or []:
        if isinstance(page, dict) and page.get("status") != "DEPRECATED":
            for f in page_frames(page):
                out.setdefault(f, page)
    return out


def user_prompt(doc: dict, page: dict, *, feedback: str = "") -> str:
    from services.blueprint.ui_engineer import _page_brief
    from services.drawn.contract import props_type

    views = views_of(doc, page)
    targets = _targets(doc)
    out = ["Attach this page to its data and processes.\n\n```json\n" + json.dumps(_page_brief(doc, page), indent=2)
           + "\n```"]
    lines = []
    for as_, label, row in views:
        contract = row.get("contract") or {}
        lines.append(f"### `{row['name']}` from \"./parts/{row['name']}\" — "
                     + ("the page as it opens" if as_ == "main" else f"its {as_} “{label}” (the whole page "
                                                                     f"as drawn with it open)")
                     + "\n```ts\n" + props_type(row["name"], contract) + "```")
        acts = []
        for action in contract.get("actions") or []:
            target = targets.get(str(action.get("target") or ""))
            within = next((a for a, _l, r in views if r.get("key") == action.get("target")), None)
            where = (f" → shows this page's {within} view" if within else
                     f" → page `{target.get('route')}`" if target else "")
            acts.append(f"  - `{action.get('name')}` “{action.get('label')}”: {action.get('kind')}{where}")
        if acts:
            lines.append("Its actions:\n" + "\n".join(acts))
        sample = json.dumps(row.get("sample") or {}, ensure_ascii=False)
        lines.append("As drawn (its sample props):\n```json\n" + sample[:6000]
                     + ("…" if len(sample) > 6000 else "") + "\n```")
    out.append("THE SCREEN IS ALREADY DRAWN, as these views — the design's own markup, which you never change or "
               "restyle:\n\n" + "\n\n".join(lines))
    out.append(
        "WRITE ONLY load.ts AND view.tsx:\n"
        "- load.ts reads exactly what the views show, through the SDK.\n"
        "- view.tsx draws NOTHING of its own. It shows ONE drawn view at a time — the main one, or the dialog, "
        "drawer, tab, step or state a person opened (keep which in `useState`) — and gives it every prop its "
        "type asks for. Records become the props as the drawing displays them: format money, dates and counts "
        "the way the sample shows them (“7 of 10”, “1 Mar 2027”); an `enum` prop takes "
        "one of its drawn values; every row's `id` is the record's id.\n"
        "- Each action: `navigate` goes to its page with `router.push(href(pages.x))`; `open` shows that view; "
        "`submit` and `run` run the process from the brief that does it, the way the SDK runs workflows, and "
        "show the main view again when it is done. A form's change handler updates the form's state.\n"
        "- What a view shows that no record holds: name it in `needs_fields` (entity, field, type, label). An "
        "action no process does: say what it should do in `needs_workflows`. Then leave load.ts and view.tsx "
        "empty — they are written again once those exist. Never feed a prop a made-up constant.\n"
        "- `seed`: the drawing's example content (the samples above) as records of the entities, as JSON — "
        "the rows the app first opens with.")
    if feedback:
        out.append("Your previous version was refused. Fix every one of these:\n" + feedback)
    return "\n\n".join(out)


SYSTEM_NOTE = (
    "\n\nTHIS PAGE IS DRAWN. Its markup is the design's and already written as views under ./parts; your job "
    "is to feed them and wire them, never to draw. The house style rules above do not apply to the views.")


def bind(doc: dict, page: dict, app_root: Path, client: Any, *, feedback: str = "") -> tuple[dict, list]:
    """The page's `pageCode` body, bound and compiled, and what the calls cost.
    Raises NeedsFields / ui_engineer.NeedsWorkflow when the views need what
    the application does not have yet, and ui_engineer.CompileError when no
    round compiles."""
    from services.blueprint import ui_engineer

    system = ui_engineer.system_prompt(doc) + SYSTEM_NOTE
    parts = parts_of(doc, page)
    pid = str(page.get("id"))
    spent: list = []
    note = feedback
    seed: dict = {}
    for _round in range(ROUNDS):
        t0 = time.monotonic()
        reply = client(system=system, user=user_prompt(doc, page, feedback=note), schema=BIND_SCHEMA)
        if getattr(reply, "usage", None) is not None:
            spent.append((reply.usage, time.monotonic() - t0))
        try:
            body = json.loads(getattr(reply, "text", reply))
        except json.JSONDecodeError as exc:
            note = f"Your reply was not valid JSON ({exc}). Return the object only."
            continue
        fields = [f for f in body.get("needs_fields") or [] if isinstance(f, dict) and f.get("name")]
        flows = [str(w).strip() for w in body.get("needs_workflows") or [] if str(w).strip()]
        if fields:
            raise NeedsFields(fields)
        if flows:
            raise ui_engineer.NeedsWorkflow(flows)
        try:
            seed = json.loads(body.get("seed") or "{}") or {}
        except json.JSONDecodeError:
            seed = {}
        load, view = str(body.get("load") or ""), ui_engineer._use_client_first(str(body.get("view") or ""))
        errors = check(view, page, doc) + ui_engineer._static_findings(load, view, exact=True) \
            + ui_engineer._unwired_actions(doc, page, view) \
            + ui_engineer.typecheck(doc, app_root, pid, load, view, parts=parts)
        if not errors:
            return {"page": pid, "rationale": str(body.get("rationale") or ""), "load": load, "view": view,
                    "parts": parts, "requirements": list(page.get("requirements") or []),
                    **({"seed": seed} if seed else {})}, spent
        note = ("The TypeScript compiler (strict) and the page rules refused it:\n"
                + "\n".join(f"- {e}" for e in errors[:40]))
    raise ui_engineer.CompileError(f"{pid}: the drawn page did not bind after {ROUNDS} rounds — {note[:600]}")


def check(view: str, page: dict, doc: dict) -> list[str]:
    """The page around the drawing draws nothing and shows every drawn view."""
    problems = []
    for as_, _label, row in views_of(doc, page):
        if f'"./parts/{row["name"]}"' not in view:
            problems.append(f"view.tsx: never shows the drawn view {row['name']} (its {as_}) — import it from "
                            f"\"./parts/{row['name']}\" and show it")
    markup = re.findall(r"<([a-z][a-z0-9]*)\b", view)
    drawn = [t for t in markup if t not in ("fragment",)]
    if drawn:
        problems.append("view.tsx: draws markup of its own (<" + ">, <".join(sorted(set(drawn))[:5]) + ">) — the "
                        "page is the drawn views; only choose which one shows and feed it")
    return problems

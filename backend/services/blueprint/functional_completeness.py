"""Whether the application the Blueprint describes would actually work.

Every other edge asks whether the Blueprint is *coherent* — a page addressed to
a role that exists, an endpoint guarded by a real permission. None asks whether
the thing it describes DOES anything, and that is the class of defect that
survived every check and reached people using the app:

  * five buttons on one page carrying a label and no action at all — they
    render, they are clickable, and nothing happens
  * `workflow: "markPlantWateredToday"` where no such workflow exists, which
    answers "Workflow not found" on click
  * `{{overdue.value}}` with no `overdue` source, which renders the template
    text to whoever opens the page
  * a declared page with no composed tree, so its route 404s

Each was found by using the application. None needed the application running to
find: they are all two-sided consistency questions over the Blueprint, decidable
before a single file is written.

THE FINDINGS ARE MEANT TO BE REJECTIONS. §73 says verification exists to close
the loop, and the orchestrator already re-asks a node when its output is
refused — that mechanism recovers composition failures on nearly every run. A
button with no action is not a page to repair afterwards; it is a page that was
not composed correctly, and the composer is the thing that should hear about it.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

#: Components that exist to be acted upon. A `Text` that does nothing is
#: content; a `Button` that does nothing is a defect.
_ACTIONABLE = ("Button", "Form")

#: `{{plants}}` and `{{plants.count}}` both name `plants`.
_BINDING = re.compile(r"\{\{([^}]+)\}\}")


def _dangling(schema: dict) -> list[str]:
    """`dangling_bindings`, or nothing if it cannot be reached.

    A verification edge must not fail the run over an import, and a check that
    cannot run is better silent than wrong.
    """
    try:
        from services.a2ui_to_forge import dangling_bindings
        return dangling_bindings(schema)
    except Exception:  # noqa: BLE001
        return []


def _planner_placeholders() -> set[str]:
    """Names the planner substitutes, which are not bindings yet.

    A pattern template says `{{rows}}` and `$item.label`; `plan_page` resolves
    both when it instantiates the template for a page. Read as bindings they
    look like references to data nothing provides — which flagged the coherent
    fixture as broken and would have failed every pattern-derived page.

    Taken from the planner's own constants rather than restated, because a
    vocabulary listed twice drifts.
    """
    try:
        from services.blueprint.page_planner import RECORD, ROWS
        return {ROWS, RECORD, "metrics"}
    except Exception:  # noqa: BLE001
        return {"rows", "record", "metrics"}


def _live(items: Any) -> list[dict]:
    return [i for i in (items or [])
            if isinstance(i, dict) and i.get("status") != "SUPERSEDED"]


def _action_props() -> set[str]:
    """Every way a component may declare that it does something.

    Read from the composer's own contract, so this cannot drift from what the
    composer is told to produce. Hand-listing them is how `opensDialog` came to
    be refused on a page whose create form was a modal: the list held four of
    the six the catalog offers.
    """
    try:
        from services.a2ui_catalog import _COMPOSE_ONE_OF
    except Exception:  # noqa: BLE001 — a lookup must not fail verification
        return {"workflow", "navigate", "submit", "onClick"}
    out: set[str] = set()
    for choices in _COMPOSE_ONE_OF.values():
        out.update(choices)
    return out


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
        return
    if not isinstance(node, dict):
        return
    if node.get("type"):
        yield node
    yield from _walk(node.get("children") or [])


def _workflow_refs(props: Any) -> Iterator[str]:
    """Every `workflow` value at any depth.

    Nested as often as top-level — `Table.rowActions[]`, `emptyAction` — and a
    check that reads one key walks past the rest.
    """
    if isinstance(props, list):
        for item in props:
            yield from _workflow_refs(item)
        return
    if not isinstance(props, dict):
        return
    for key, value in props.items():
        if key == "workflow" and isinstance(value, str) and value:
            yield value
        elif isinstance(value, (dict, list)):
            yield from _workflow_refs(value)


def _bindings(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, list):
        for item in node:
            found |= _bindings(item)
        return found
    if not isinstance(node, dict):
        return found
    for value in node.values():
        if isinstance(value, str):
            found.update(m.split(".")[0].strip() for m in _BINDING.findall(value))
        else:
            found |= _bindings(value)
    return found


def functional_findings(doc: dict) -> list[dict]:
    """`[{rule, page, detail}]` — everything that would not work.

    Returned as plain dicts rather than `Finding`s so the composer's rejection
    path and the verification edge can share one implementation; the caller
    wraps them in whichever shape it needs.
    """
    out: list[dict] = []
    actions = _action_props()
    workflows = {str(w["id"]) for w in _live(doc.get("workflows")) if w.get("id")}
    layouts = {l.get("page"): l for l in _live(doc.get("pageLayouts"))}

    for page in _live(doc.get("pages")):
        pid = str(page.get("id") or "")
        route = page.get("route") or pid
        layout = layouts.get(pid)

        # A page nothing composed has no schema, so its route 404s. The run
        # reports the composition failure; without this the Blueprint still
        # claims the page exists and every consumer believes it.
        if not layout:
            out.append({"rule": "page-not-composed", "page": pid,
                        "detail": f"{route} has no composed tree, so the route "
                                  f"cannot render"})
            continue

        declared = {str(s.get("name")) for s in (layout.get("dataSources") or [])
                    if isinstance(s, dict) and s.get("name")}

        for node in _walk(layout.get("root")):
            kind = str(node.get("type"))
            props = node.get("props") or {}

            # A control with no action renders, is clickable, and does nothing —
            # indistinguishable from a broken application, and with no error to
            # diagnose from. Worse than the control not being there.
            # A repeated control takes its action from the item it repeats
            # over, so the template itself carries none. `$item.label` is the
            # planner's own placeholder, substituted per item at plan time.
            templated = str(props.get("label") or "").startswith("$") or \
                bool(node.get("repeat"))
            if kind in _ACTIONABLE and not (set(props) & actions) and not templated:
                label = props.get("label") or props.get("submitLabel") or kind
                out.append({"rule": "control-without-action", "page": pid,
                            "detail": f"{route}: {kind} {label!r} declares no "
                                      f"action — it would do nothing"})

            for ref in _workflow_refs(props):
                if ref not in workflows:
                    out.append({"rule": "workflow-not-defined", "page": pid,
                                "detail": f"{route}: targets workflow {ref!r}, "
                                          f"which this application does not "
                                          f"define"})

        # A binding with no source behind it renders its own template text.
        #
        # ASKED OF THE BINDER, NOT RE-DERIVED HERE. `dangling_bindings` answers
        # the same question and knows one thing this walker did not: inside a
        # Table or a Repeat, `{{id}}` means this row's id and the renderer
        # resolves it against the row. Reading it as a page-level source
        # refused /tickets twice over `rowHref: "/tickets/{{id}}"` — after the
        # floor had already been taught otherwise, because the rule lived in
        # two places and only one of them learned.
        unresolved = set(_dangling(
            {"dataSources": layout.get("dataSources") or [],
             "root": layout.get("root")})) - _planner_placeholders()
        for name in sorted(unresolved):
            out.append({"rule": "binding-without-source", "page": pid,
                        "detail": f"{route}: binds {{{{{name}}}}}, which no "
                                  f"data source provides"})

    return out

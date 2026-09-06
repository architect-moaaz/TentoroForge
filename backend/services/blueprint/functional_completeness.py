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


def page_findings(doc: dict) -> list[dict]:
    """What a page's controls would do — the composer's refusals."""
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
        node_ids = {str(n.get("id")) for n in _walk(layout.get("root")) if n.get("id")}

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

            target = props.get("opensDialog")
            if isinstance(target, str) and target and target not in node_ids:
                out.append({"rule": "dialog-not-defined", "page": pid,
                            "detail": f"{route}: {kind} {props.get('label') or kind!r} opens dialog "
                                      f"{target!r}, which this page does not contain — a control that "
                                      f"opens nothing does nothing; add the Dialog with that id, or bind "
                                      f"the control to a workflow or route"})
            for ref in _workflow_refs(props):
                if ref not in workflows:
                    out.append({"rule": "workflow-not-defined", "page": pid,
                                "detail": f"{route}: targets workflow {ref!r}, "
                                          f"which this application does not "
                                          f"define"})
                    continue
                for missing in unsatisfied_inputs(doc, page, layout, node, ref):
                    out.append({"rule": "workflow-inputs-unsatisfied", "page": pid,
                                "detail": f"{route}: {missing}"})

        # A binding with no source behind it renders its own template text.
        #
        # ASKED OF THE BINDER, NOT RE-DERIVED HERE. `dangling_bindings` answers
        # the same question and knows one thing this walker did not: inside a
        # Table or a Repeat, `{{id}}` means this row's id and the renderer
        # resolves it against the row. Reading it as a page-level source
        # refused /tickets twice over `rowHref: "/tickets/{{id}}"` — after the
        # floor had already been taught otherwise, because the rule lived in
        # two places and only one of them learned.
        for finding in search_findings(doc, page, layout):
            out.append({"rule": finding[0], "page": pid, "detail": f"{route}: {finding[1]}"})
        for detail in dependent_option_findings(doc, page, layout):
            out.append({"rule": "dependent-options-unsatisfied", "page": pid, "detail": f"{route}: {detail}"})
        unresolved = set(_dangling(
            {"dataSources": layout.get("dataSources") or [],
             "root": layout.get("root")})) - _planner_placeholders()
        for name in sorted(unresolved):
            out.append({"rule": "binding-without-source", "page": pid,
                        "detail": f"{route}: binds {{{{{name}}}}}, which no "
                                  f"data source provides"})

    return out


def authoring_findings(doc: dict) -> list[dict]:
    """What the engine would refuse in a workflow or rule as written — the
    author's refusals. Kept apart from :func:`page_findings` because a page
    composer cannot fix a workflow: on 2026-09-05 one workflow's `concat(...)`
    refused seven pages that had nothing to do with it."""
    out: list[dict] = []
    out.extend(rule_findings(doc))
    out.extend(expression_findings(doc))
    out.extend(template_findings(doc))
    out.extend(insert_findings(doc))
    return out


def functional_findings(doc: dict) -> list[dict]:
    """Everything, for verification."""
    return page_findings(doc) + authoring_findings(doc)


# ---------------------------------------------------------------------------
# A CONTROL SUPPLIES WHAT ITS WORKFLOW NEEDS, FROM WHAT ITS PAGE HAS IN SCOPE.
#
# A workflow declares `inputs` (contract). A record input is satisfied on a
# detail page of that entity — the page shows the record, and projection
# carries its id on the control — or by an explicit argument. A field input
# is satisfied by a form around the control that collects that field, or by
# an argument. Anything else is a button that fails when pressed, and is
# refused here, with what is missing and where it could come from, so the
# author can put the control where its inputs are.
# ---------------------------------------------------------------------------

def _entity_id_by_name(doc: dict) -> dict:
    return {str(e.get("name") or ""): str(e.get("id") or "")
            for e in _live((doc.get("data") or {}).get("entities"))}


def _record_in_scope(doc: dict, page: dict, entity: str) -> bool:
    route = str(page.get("route") or "")
    primary = str((page.get("data") or {}).get("primaryEntity") or "")
    by_name = _entity_id_by_name(doc)
    wanted = {entity, by_name.get(entity, "")} - {""}
    return route.endswith("]") and primary in wanted


def _form_fields_of(form: dict) -> set[str]:
    """Every field a Form collects: its declarative `fields` (the shape a
    generated form takes — the fields live in props, not in child nodes)
    and any input nodes inside it."""
    names: set[str] = set()
    for f in (form.get("props") or {}).get("fields") or []:
        if isinstance(f, dict) and f.get("name"):
            names.add(str(f["name"]))
        for sub in (f.get("fields") or []) if isinstance(f, dict) else []:
            if isinstance(sub, dict) and sub.get("name"):
                names.add(str(sub["name"]))
    for inner in _walk(form):
        name = (inner.get("props") or {}).get("name")
        if inner.get("type") in ("Input", "Select", "Textarea", "Checkbox", "DatePicker", "Field", "Combobox", "MultiSelect") and name:
            names.add(str(name))
    return names


def _form_fields_around(root: Any, target: dict) -> set[str] | None:
    """The field names collected by the nearest Form holding `target` — or by
    `target` itself when it is the Form — or None when no Form does."""
    if target.get("type") == "Form":
        return _form_fields_of(target)

    def walk(node: Any, fields: set | None):
        if not isinstance(node, dict):
            return None
        here = _form_fields_of(node) if node.get("type") == "Form" else fields
        if node is target:
            return here
        for child in node.get("children") or []:
            found = walk(child, here)
            if found is not None or (isinstance(child, dict) and child is target):
                return found if found is not None else here
        return None
    return walk(root, None)


def _reaches(doc: dict, page: dict, entity: str) -> str | None:
    """A detail page reaches the records its record links to: a write-off's
    page reaches the case it belongs to through `caseId`. Returns the
    foreign-key field on the page's entity, or None."""
    primary = str((page.get("data") or {}).get("primaryEntity") or "")
    by_name = _entity_id_by_name(doc)
    wanted = {entity, by_name.get(entity, "")} - {""}
    if not str(page.get("route") or "").endswith("]") or not primary:
        return None
    for rel in _live((doc.get("data") or {}).get("relationships")):
        if str(rel.get("from")) == primary and str(rel.get("to")) in wanted and rel.get("fromField"):
            return str(rel["fromField"])
    return None


def _entity_of_source(doc: dict, layout: dict, name: str) -> str | None:
    for src in layout.get("dataSources") or []:
        if isinstance(src, dict) and src.get("name") == name:
            ent = _entity_by_ref(doc, str(src.get("entity") or ""))
            return str((ent or {}).get("id") or src.get("entity") or "") or None
    return None


def _row_scoped(control: dict, layout: dict, doc: dict) -> str | None:
    """A Table's row actions carry the row, and a control inside a repeated
    item carries that item: the entity of the source the Table or Repeat
    reads is in scope. Returns that entity's id or None."""
    if control.get("type") == "Table":
        data = str((control.get("props") or {}).get("data") or "")
        return _entity_of_source(doc, layout, data.strip("{} ").split(".")[0])
    # Inside a Repeat (or any node repeating over a source), the item is the
    # record — an Approve button drawn once per pending case.
    def holder(node, target):
        if not isinstance(node, dict):
            return None
        for child in node.get("children") or []:
            if child is target or holder(child, target) is not None:
                rep = node.get("repeat") or ((node.get("props") or {}).get("source") if node.get("type") == "Repeat" else None)
                if isinstance(rep, dict):
                    rep = rep.get("source") or rep.get("items")
                if isinstance(rep, str) and rep:
                    return rep.strip("{} ").split(".")[0]
                inner = holder(child, target)
                if inner:
                    return inner
                return "" if child is target else None
        return None
    source = holder(layout.get("root"), control)
    return _entity_of_source(doc, layout, source) if source else None


def _ancestry(root: Any, target: dict) -> str:
    """`Stack > Card > Row` — where the control sits, for the refusal."""
    def walk(node, path):
        if not isinstance(node, dict):
            return None
        for child in node.get("children") or []:
            if child is target:
                return path + [str(node.get("type"))]
            found = walk(child, path + [str(node.get("type"))])
            if found:
                return found
        return None
    chain = walk(root, [])
    return " > ".join(chain[-4:]) if chain else "the page root"


def unsatisfied_inputs(doc: dict, page: dict, layout: dict, control: dict,
                       workflow_id: str) -> list[str]:
    """What the control cannot supply for the workflow it runs."""
    wf = next((w for w in _live(doc.get("workflows")) if w.get("id") == workflow_id), None)
    if not wf:
        return []
    props = control.get("props") or {}
    args = props.get("args") if isinstance(props.get("args"), dict) else {}
    label = props.get("label") or props.get("submitLabel") or control.get("type")
    out: list[str] = []
    fields = None
    for inp in wf.get("inputs") or []:
        if not inp.get("required", True):
            continue
        name = str(inp.get("name") or "")
        if name in args:
            continue
        if inp.get("kind") == "record":
            entity = str(inp.get("entity") or "")
            if _record_in_scope(doc, page, entity) or _reaches(doc, page, entity):
                continue
            by_name = _entity_id_by_name(doc)
            row_entity = _row_scoped(control, layout, doc)
            if row_entity and row_entity in {entity, by_name.get(entity, "")}:
                continue
            ent_name = next((e.get("name") for e in _live((doc.get("data") or {}).get("entities"))
                             if e.get("id") == entity), entity)
            out.append(f"{control.get('type')} {label!r} (inside {_ancestry(layout.get('root'), control)}) "
                       f"runs {wf.get('name') or workflow_id} ({workflow_id}), which needs a {ent_name} "
                       f"record ({name!r}); nothing there names one — put it on the {ent_name} detail "
                       f"page, or make it a `rowActions` entry of a Table whose `data` lists {ent_name}, "
                       f"or a control inside a `Repeat` over a {ent_name} source, or pass {name!r} in `args`")
        elif inp.get("kind") == "field":
            if control.get("type") == "Table":
                out.append(f"Table {label!r} runs {wf.get('name') or workflow_id} ({workflow_id}), "
                           f"which needs the field {name!r}; a table collects no fields — a Button "
                           f"that navigates to the page whose Form collects them is the control here")
                continue
            if fields is None:
                fields = _form_fields_around(layout.get("root"), control)
            if fields is not None and name in fields:
                continue
            out.append(f"{control.get('type')} {label!r} runs {wf.get('name') or workflow_id} "
                       f"({workflow_id}), which needs the field {name!r}; "
                       + ("no Form around the control collects it — add a field named "
                          f"{name!r} to that Form" if fields is not None else
                          f"the control is in no Form — put it in a Form whose fields include {name!r}")
                       + (f", or, when the control itself is the answer (an Approve button is the "
                          f"decision), pass it as a constant: `args: {{\"{name}\": ...}}`"))
    return out


# ---------------------------------------------------------------------------
# A SEARCH BOX SEARCHES THE PAGE'S LIST, AND THE LIST HAS SOMETHING TO SEARCH.
#
# `Input type="search"` writes `q`; the page passes `q` to its list source;
# the searchable-columns manifest says which columns match. Either half
# missing is a search box that finds nothing and looks broken — a page with
# no list, or an entity with no text column — and is refused with which.
# ---------------------------------------------------------------------------

def _list_sources(layout: dict) -> list[dict]:
    return [s for s in (layout.get("dataSources") or [])
            if isinstance(s, dict) and (s.get("op") in (None, "list"))]


def _entity_by_ref(doc: dict, ref: str) -> dict | None:
    for e in _live((doc.get("data") or {}).get("entities")):
        if ref in (e.get("id"), e.get("name")):
            return e
    return None


def search_findings(doc: dict, page: dict, layout: dict) -> list[tuple[str, str]]:
    boxes = [n for n in _walk(layout.get("root"))
             if n.get("type") == "Input" and (n.get("props") or {}).get("type") == "search"]
    if not boxes:
        return []
    lists = _list_sources(layout)
    if not lists:
        return [("search-without-source",
                 "has a search box and no list source — nothing on this page can be "
                 "searched; give the page a list source, or drop the box")]
    from services.blueprint.projection import searchable_columns
    columns = searchable_columns(doc)
    out = []
    for src in lists:
        ent = _entity_by_ref(doc, str(src.get("entity") or ""))
        name = (ent or {}).get("name") or str(src.get("entity") or "")
        if name and not columns.get(name) and not columns.get(name.lower()):
            fields = [f.get("name") for f in (ent or {}).get("fields") or []][:6]
            out.append(("search-without-columns",
                        f"searches {name}, which has no text column to search "
                        f"(its fields: {', '.join(map(str, fields))}) — a text field "
                        f"on {name} is what a search needs"))
    return out


# ---------------------------------------------------------------------------
# A DEPENDENT SELECT DEPENDS ON A SIBLING IT HAS, MATCHED ON A COLUMN THAT IS.
# ---------------------------------------------------------------------------

def _source_entity(doc: dict, layout: dict, source: str) -> dict | None:
    for s in layout.get("dataSources") or []:
        if isinstance(s, dict) and s.get("name") == source:
            return _entity_by_ref(doc, str(s.get("entity") or ""))
    return None


def dependent_option_findings(doc: dict, page: dict, layout: dict) -> list[str]:
    out = []
    for node in _walk(layout.get("root")):
        props = node.get("props") or {}
        of = props.get("optionsFrom") if isinstance(props.get("optionsFrom"), dict) else None
        dep = (of or {}).get("dependsOn") if of else None
        if not isinstance(dep, dict):
            continue
        label = props.get("label") or props.get("name") or node.get("type")
        siblings = _form_fields_around(layout.get("root"), node)
        field, column = str(dep.get("field") or ""), str(dep.get("column") or "")
        if siblings is None:
            out.append(f"{node.get('type')} {label!r} depends on {field!r} but sits in no Form")
        elif field not in siblings:
            out.append(f"{node.get('type')} {label!r} depends on {field!r}, which is not a field "
                       f"of its Form (fields: {', '.join(sorted(siblings)) or 'none'})")
        ent = _source_entity(doc, layout, str(of.get("source") or ""))
        if ent is not None and column not in {str(f.get("name")) for f in ent.get("fields") or []}:
            out.append(f"{node.get('type')} {label!r} is matched on {column!r}, which "
                       f"{ent.get('name')} does not have")
    return out


# ---------------------------------------------------------------------------
# A RULE'S EFFECTS LAND ON FIELDS THE ENTITY HAS. A condition-action rule
# that hides `amountDue` on an entity with no such field would fire on
# nothing and read as a rule that does not work.
# ---------------------------------------------------------------------------

def rule_findings(doc: dict) -> list[dict]:
    out: list[dict] = []
    entities = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    for rule in _live(doc.get("businessRules")):
        if rule.get("kind") != "condition_action":
            continue
        rid = str(rule.get("id") or "")
        ent = entities.get(str(rule.get("entity") or ""))
        if ent is None:
            out.append({"rule": "rule-without-entity", "page": rid,
                        "detail": f"{rule.get('name') or rid} has effects but names no entity "
                                  f"this application defines"})
            continue
        fields = {str(f.get("name")) for f in ent.get("fields") or []}
        for action in list(rule.get("then") or []) + list(rule.get("otherwise") or []):
            field = str((action or {}).get("field") or "")
            if field and field not in fields:
                out.append({"rule": "rule-field-unknown", "page": rid,
                            "detail": f"{rule.get('name') or rid} acts on {field!r}, which "
                                      f"{ent.get('name')} does not have (fields: "
                                      f"{', '.join(sorted(fields))})"})
    return out


# ---------------------------------------------------------------------------
# AN EXPRESSION IS READ BY THE ENGINE'S PARSER BEFORE A PERSON PRESSES THE
# BUTTON. A condition written in JavaScript (`==`, `&&`) is refused at run
# time by the FEEL dialect; refused here, the author is told.
# ---------------------------------------------------------------------------

def _expressions(doc: dict) -> list[tuple[str, str, str]]:
    """(id, where, expression) for every condition the engine will parse."""
    # KEYED BY POSITION, NOT BY ID. A proposal has no id until it is applied,
    # so every rule the author sent shared the key "None/when" and one rule's
    # parse error was reported against all thirty of them.
    out = []
    for n, wf in enumerate(_live(doc.get("workflows"))):
        for m, step in enumerate(wf.get("steps") or []):
            if not isinstance(step, dict):
                continue
            cfg = step.get("config") or {}
            expr = cfg.get("expression") or cfg.get("condition")
            if isinstance(expr, str) and expr.strip():
                out.append((f"workflow#{n}/{step.get('key') or step.get('id') or m}",
                            f"{wf.get('name') or wf.get('id')}, step {step.get('key') or step.get('id')!r}", expr))
    for n, rule in enumerate(_live(doc.get("businessRules"))):
        if rule.get("kind") == "condition_action" and isinstance(rule.get("when"), str) and rule["when"].strip():
            out.append((f"rule#{n}/when", f"rule {rule.get('name') or rule.get('id')}", rule["when"]))
    return out


def expression_findings(doc: dict) -> list[dict]:
    items = _expressions(doc)
    if not items:
        return []
    from services.blueprint.feel_check import check_expressions
    errors = check_expressions([(i, e) for i, _w, e in items])
    out = []
    for i, where, expr in items:
        if i in errors:
            out.append({"rule": "expression-invalid", "page": i.split("/")[0],
                        "detail": f"{where}: the engine cannot parse {expr!r} — {errors[i]}. "
                                  f"Conditions are FEEL: `=` not `==`, `and`/`or`/`not`, field names "
                                  f"without braces (`caseType`, never `input.caseType`), membership as "
                                  f"`stage in [\"A\",\"B\"]` with square brackets, never parentheses"})
    return out


# ---------------------------------------------------------------------------
# A TEMPLATE NAMES SOMETHING THE ENGINE HOLDS. The engine seeds the trigger's
# input as flat variables (`{{title}}`), stores each step's output under the
# step's key (`{{insert_case.id}}`), and `set_variable` steps under their
# `variableName`; `$now`, `$today` and `$user.id` are whole-value sentinels.
# A workflow wrote `{{now}}`, `{{currentUser.id}}`, `{{vars.approvalState}}`
# and `{{steps.insert_case.output.id}}` — none of which exists — and its
# insert wrote blanks where it wrote anything.
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.\[\]|:]+)\s*\}\}")
_WRONG_ROOTS = {
    "now": "the sentinel `$now` as the whole value",
    "today": "the sentinel `$today` as the whole value",
    "currentUser": "the sentinel `$user.id` as the whole value",
    "user": "the sentinel `$user.id` as the whole value",
    "input": "the field name alone — `{{title}}`, not `{{input.title}}`",
    "vars": "the variable name alone — `{{approvalState}}`",
    "steps": "the step key and field — `{{insert_case.id}}`",
    "sequence": "nothing — the engine has no sequences; number records in the data model",
}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def template_findings(doc: dict) -> list[dict]:
    out: list[dict] = []
    for wf in _live(doc.get("workflows")):
        steps = [st for st in wf.get("steps") or [] if isinstance(st, dict)]
        inputs = {str(i.get("name")) for i in wf.get("inputs") or [] if i.get("name")}
        keys = {str(st.get("key") or st.get("id")) for st in steps}
        variables = {str((st.get("config") or {}).get("variableName")) for st in steps
                     if (st.get("config") or {}).get("variableName")}
        known = inputs | keys | variables
        seen: set[str] = set()
        for st in steps:
            for text in _strings(st.get("config") or {}):
                for ref in _TEMPLATE_RE.findall(text):
                    root = ref.split(".")[0].split("[")[0].split("|")[0]
                    if root in known or (root, str(st.get("key"))) in seen:
                        continue
                    seen.add((root, str(st.get("key"))))
                    if root in _WRONG_ROOTS:
                        fix = _WRONG_ROOTS[root]
                        out.append({"rule": "template-unknown", "page": str(wf.get("id")),
                                    "detail": f"{wf.get('name') or wf.get('id')}, step {st.get('key')!r}: "
                                              f"{{{{{ref}}}}} names nothing the engine holds — write {fix}"})
                    else:
                        out.append({"rule": "template-unknown", "page": str(wf.get("id")),
                                    "detail": f"{wf.get('name') or wf.get('id')}, step {st.get('key')!r}: "
                                              f"{{{{{ref}}}}} names nothing the engine holds — an input field "
                                              f"({', '.join(sorted(inputs)) or 'none'}), a step key "
                                              f"({', '.join(sorted(keys)) or 'none'}), or a variable a "
                                              f"set_variable step set ({', '.join(sorted(variables)) or 'none'})"})
    return out


# ---------------------------------------------------------------------------
# AN INSERT SUPPLIES WHAT THE TABLE REQUIRES. A required column the data model
# declares and the insert omits fails at the database, after the row's other
# values are gone. Create Case wrote the case number in a db_update after the
# insert; the column is NOT NULL, so the insert never happened.
# ---------------------------------------------------------------------------

def _entity_for_table(doc: dict, table: str | None) -> dict | None:
    if not table:
        return None
    t = str(table).strip().lower()
    for e in (doc.get("data") or {}).get("entities") or []:
        if str(e.get("table") or "").lower() == t or str(e.get("name") or "").lower() == t:
            return e
    return None


def insert_findings(doc: dict) -> list[dict]:
    out: list[dict] = []
    for wf in _live(doc.get("workflows")):
        for st in wf.get("steps") or []:
            if not isinstance(st, dict):
                continue
            cfg = st.get("config") or {}
            if cfg.get("actionType") != "db_insert":
                continue
            entity = _entity_for_table(doc, cfg.get("table"))
            if entity is None:
                continue
            values = cfg.get("values") if isinstance(cfg.get("values"), dict) else {}
            given = {str(k) for k in values}
            missing = [f["name"] for f in entity.get("fields") or []
                       if f.get("required") and not f.get("primaryKey") and f.get("name") not in given
                       and not (f.get("references") and f["name"] in ("createdById", "updatedById"))]
            if missing:
                out.append({"rule": "insert-missing-required", "page": str(wf.get("id")),
                            "detail": f"{wf.get('name') or wf.get('id')}, step {st.get('key')!r}: inserts into "
                                      f"{entity.get('name')} without {', '.join(repr(m) for m in missing)}, which "
                                      f"the data model requires — supply each in `values`: an input by name, "
                                      f"`$now` for a time, `$user.id` for the actor, `$uuid` for a reference "
                                      f"nothing else supplies, a literal for a starting state"})
    return out


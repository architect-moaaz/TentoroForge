"""The wire between a control and the workflow it runs.

The Blueprint says a control runs a workflow and a workflow declares what it
needs; the completeness checks reason in those terms — "a row of the Table
names the record" — and were satisfied. Then the Table dispatched `{ id }`,
the projected step read `{{record.id}}`, the engine found no object with an
`.id`, and Delete Record refused every row with "WHERE id is empty". Two
correct dialects, and nothing that compared them.

This module is the comparison. It knows what each control actually puts on
the wire — read off the library's own dispatch code, not guessed:

* a Table row action posts ``{ id }`` (``Table.tsx``: ``dispatch(a.workflow,
  { id: r?.id })``); its empty-state action posts ``{}``;
* a Form posts its ``args`` and every field it collects;
* a Button, IconButton, Link or ConfirmDialog posts its ``args`` plus the
  values of the Form that encloses it, if any;

and what a workflow reads — every ``{{ref}}`` inside its step configs — and
what the engine itself supplies (``user``, ``input``, and an earlier step's
output under that step's key). From these:

* :func:`workflow_ref_findings` — a step reads a name nothing declares and no
  earlier step produces: the workflow author's refusal;
* :func:`dispatch_findings` — a control's payload lacks an input the workflow
  declares, and the page's scope does not put it on the wire either: the
  composer's refusal, with the `args` to add named;
* :func:`dispatches` — every control→workflow pair with the payload it sends
  and a sample value per key, written by the projection for the build-time
  dry run that executes each one through the real engine (see
  ``templates/runtime/workflows/verify-dispatches.ts``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from services.blueprint.functional_completeness import (
    _live, _walk, _form_fields_of, _form_fields_around, _workflow_by_id,
    unsatisfied_inputs,
)

#: What the engine puts in scope on its own (`executeWorkflow`: variables =
#: {...input, user}; `ctx.input`), read as `{{user.role}}` / `{{input.x}}`.
RUNTIME_HEADS = frozenset({"user", "input"})

#: Controls whose `workflow` prop dispatches on click, with `args`.
_CLICK_CONTROLS = ("Button", "IconButton", "Link", "ConfirmDialog")

_REF = re.compile(r"\{\{\s*([A-Za-z_][\w]*)((?:\.[\w]+|\[\d+\])*)\s*\}\}")

_SAMPLE_ID = "00000000-0000-4000-8000-000000000001"


@dataclass
class Dispatch:
    """One control → workflow wire."""
    page_id: str
    route: str
    control: str            # "Table.rowActions[2]", "Form", "Button"
    label: str
    workflow_id: str
    keys: set[str] = field(default_factory=set)
    #: keys whose value is a page binding (`args: {record: "{{rec.id}}"}`) —
    #: on the wire as a resolved value, for the dry run an id-shaped sample.
    bound: set[str] = field(default_factory=set)


def _label(props: Mapping[str, Any], fallback: str) -> str:
    return str(props.get("label") or props.get("submitLabel") or props.get("title") or fallback)


def _args_keys(props: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    args = props.get("args") if isinstance(props.get("args"), dict) else {}
    keys = {str(k) for k in args}
    bound = {str(k) for k, v in args.items() if isinstance(v, str) and "{{" in v}
    return keys, bound


def projected_layout(doc: Mapping[str, Any], page: Mapping[str, Any],
                     layout: Mapping[str, Any]) -> dict:
    """The layout as the projection ships it — with the record a detail page
    shows carried onto every control that runs a workflow needing it
    (`record_scope.carry_record`: `args: {record: "{{cases.id}}", id: …}`).
    The wire is read off THAT tree, not the authored one, so what the check
    sees is what the browser sends."""
    import copy
    from services.blueprint.record_scope import carry_record
    lay = copy.deepcopy(dict(layout))
    carry_record(dict(doc), dict(page), lay)
    return lay


def control_dispatches(doc: Mapping[str, Any]) -> list[Dispatch]:
    """Every control bound to a workflow, with the payload it will send."""
    out: list[Dispatch] = []
    for page in _live(doc.get("pages")):
        pid = str(page.get("id") or "")
        route = str(page.get("route") or pid)
        layout = next((l for l in _live(doc.get("pageLayouts")) if str(l.get("page")) == pid), None)
        if not layout:
            continue
        layout = projected_layout(doc, page, layout)
        root = layout.get("root")
        for node in _walk(root):
            kind = str(node.get("type") or "")
            props = node.get("props") or {}
            if kind == "Table":
                for i, a in enumerate(props.get("rowActions") or []):
                    if isinstance(a, dict) and a.get("workflow"):
                        keys, bound = _args_keys(a)
                        out.append(Dispatch(pid, route, f"Table.rowActions[{i}]",
                                            _label(a, "row action"), str(a["workflow"]),
                                            keys | {"id"}, bound))
                ea = props.get("emptyAction")
                if isinstance(ea, dict) and ea.get("workflow"):
                    keys, bound = _args_keys(ea)
                    out.append(Dispatch(pid, route, "Table.emptyAction", _label(ea, "empty action"),
                                        str(ea["workflow"]), keys, bound))
                continue
            wf = props.get("workflow")
            if not isinstance(wf, str) or not wf:
                continue
            keys, bound = _args_keys(props)
            if kind == "Form":
                out.append(Dispatch(pid, route, "Form", _label(props, "form"), wf,
                                    keys | _form_fields_of(node), bound))
            elif kind in _CLICK_CONTROLS:
                enclosing = _form_fields_around(root, node) or set()
                out.append(Dispatch(pid, route, kind, _label(props, kind), wf,
                                    keys | set(enclosing), bound))
    return out


def step_refs(wf: Mapping[str, Any]) -> Iterator[tuple[str, str, str]]:
    """``(step_key, head, full_path)`` for every `{{ref}}` a step's config reads."""
    import json as _json
    for s in wf.get("steps") or []:
        if not isinstance(s, dict):
            continue
        for m in _REF.finditer(_json.dumps(s.get("config") or {})):
            yield str(s.get("key") or "?"), m.group(1), m.group(1) + m.group(2)


def _supplied_by_workflow(wf: Mapping[str, Any]) -> set[str]:
    inputs = {str(i.get("name")) for i in (wf.get("inputs") or []) if isinstance(i, dict) and i.get("name")}
    keys = {str(s.get("key")) for s in (wf.get("steps") or []) if isinstance(s, dict) and s.get("key")}
    return inputs | keys | set(RUNTIME_HEADS)


def workflow_ref_findings(doc: Mapping[str, Any]) -> list[dict]:
    """A step reads what nothing supplies. `{{age}}` in a Create step with no
    `age` input: the composer is never asked to collect it (it checks
    declared inputs), the engine finds nothing, the column is written NULL.
    The author's to fix — declare the input, or set it from a step."""
    out: list[dict] = []
    for wf in _live(doc.get("workflows")):
        supplied = _supplied_by_workflow(wf)
        seen: set[str] = set()
        for step_key, head, path in step_refs(wf):
            if head in supplied or head in seen:
                continue
            seen.add(head)
            # `page` holds the artifact id for every finding (the verification
            # edge reads it as the artifact) — here the workflow's.
            out.append({"rule": "workflow-ref-unsupplied", "page": str(wf.get("id")),
                        "workflow": wf.get("id"),
                        "detail": f"{wf.get('name') or wf.get('id')} ({wf.get('id')}) step "
                                  f"{step_key!r} reads {{{{{path}}}}}, but no input declares "
                                  f"{head!r} and no earlier step produces it — the engine will "
                                  f"find nothing there. Declare {head!r} as an input (so the "
                                  f"control that runs this workflow supplies it) or set it from "
                                  f"a step."})
    return out


def _on_the_wire(d: Dispatch, inp: Mapping[str, Any]) -> bool:
    name = str(inp.get("name") or "")
    if name in d.keys:
        return True
    # A record travels as its id: the row dispatch's `id`, or the input's own
    # name carrying the id (`args: {record: "{{rec.id}}"}`) — both of which
    # the engine resolves `{{record.id}}` from.
    return inp.get("kind") == "record" and "id" in d.keys


def dispatch_findings(doc: Mapping[str, Any]) -> list[dict]:
    """A control whose payload lacks an input its workflow declares — where
    the page-scope check already passed, because "the record is on this page"
    is not the same as "the record is in the POST body". A Delete button on
    the record's page with no `args` sends `{}`; the page knew the record,
    the wire did not."""
    out: list[dict] = []
    layouts = {str(l.get("page")): l for l in _live(doc.get("pageLayouts"))}
    pages = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    for d in control_dispatches(doc):
        wf = _workflow_by_id(dict(doc), d.workflow_id)
        if wf is None:
            continue                          # workflow-not-defined's
        missing = [i for i in (wf.get("inputs") or [])
                   if isinstance(i, dict) and i.get("required", True) and not _on_the_wire(d, i)]
        if not missing:
            continue
        page, layout = pages.get(d.page_id) or {}, layouts.get(d.page_id) or {}
        layout = projected_layout(doc, page, layout) if layout else {}
        control = _control_node(layout, d)
        if control is not None and unsatisfied_inputs(dict(doc), dict(page), dict(layout), control, d.workflow_id):
            continue                          # already refused for its inputs — one finding, not two
        names = ", ".join(str(i.get("name")) for i in missing)
        args = ", ".join(
            f"{i.get('name')}: \"{{{{<the {i.get('name')} in scope>.id}}}}\"" if i.get("kind") == "record"
            else f"{i.get('name')}: \"{{{{<its value>}}}}\"" for i in missing)
        out.append({"rule": "dispatch-payload-incomplete", "page": d.page_id,
                    "detail": f"{d.route}: {d.control} {d.label!r} runs {wf.get('name') or d.workflow_id} "
                              f"({d.workflow_id}), which reads {names}, but the control sends "
                              f"{{{', '.join(sorted(d.keys)) or ''}}} — the page has it, the wire "
                              f"does not. Pass it in `args` ({{{args}}})."})
    return out


def _is_list(type_name: Any) -> bool:
    t = str(type_name or "").strip().lower()
    return t.endswith("[]") or t in ("array", "list")


def _list_inputs(doc: Mapping[str, Any], page: Mapping[str, Any], form: Mapping[str, Any],
                 wf: Mapping[str, Any]) -> set[str]:
    """The names a Form collects that hold SEVERAL values — by the workflow
    input's type, or the entity column's."""
    names: set[str] = set()
    for i in wf.get("inputs") or []:
        if isinstance(i, dict) and i.get("name") and _is_list(i.get("type")):
            names.add(str(i["name"]))
    wanted = {str((form.get("props") or {}).get("entity") or ""),
              str((page.get("data") or {}).get("primaryEntity") or "")}
    for e in _live((doc.get("data") or {}).get("entities")):
        if str(e.get("id")) in wanted or str(e.get("name")) in wanted:
            for f in e.get("fields") or []:
                if isinstance(f, dict) and f.get("name") and _is_list(f.get("type")):
                    names.add(str(f["name"]))
    return names


def field_kind_findings(doc: Mapping[str, Any]) -> list[dict]:
    """A Form field that collects a list with a control that submits a string.

    The edit form for a nurse held `specialities` — `string[]` on the entity
    and on the workflow input — in a textarea with a "comma-separated" hint.
    It rendered the record's array as its JSON text and would have written a
    comma string back. The shape of the value is contract: a list is
    collected by a `tags` field, which submits an array."""
    out: list[dict] = []
    layouts = {str(l.get("page")): l for l in _live(doc.get("pageLayouts"))}
    pages = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    for d in control_dispatches(doc):
        if d.control != "Form":
            continue
        wf = _workflow_by_id(dict(doc), d.workflow_id)
        page, layout = pages.get(d.page_id) or {}, layouts.get(d.page_id) or {}
        layout = projected_layout(doc, page, layout) if layout else {}
        form = _control_node(layout, d)
        if wf is None or form is None:
            continue
        lists = _list_inputs(doc, page, form, wf)
        if not lists:
            continue
        for f in (form.get("props") or {}).get("fields") or []:
            if not isinstance(f, dict) or str(f.get("name") or "") not in lists:
                continue
            kind = str(f.get("kind") or "")
            if kind == "tags":
                continue
            out.append({"rule": "form-field-kind-mismatch", "page": d.page_id,
                        "detail": f"{d.route}: the form's `{f.get('name')}` field is kind "
                                  f"{kind or 'text'!r}, but {f.get('name')} holds a list "
                                  f"(string[]) — a list is collected by a field of kind "
                                  f"\"tags\", which submits it as an array. A text control "
                                  f"shows the array as JSON and writes a string back."})
    return out


def _control_node(layout: Mapping[str, Any], d: Dispatch) -> dict | None:
    """The layout node a Dispatch came from (a row action's Table, else the
    control itself), for the input check that reasons about page scope."""
    for node in _walk(layout.get("root")):
        kind = str(node.get("type") or "")
        props = node.get("props") or {}
        if d.control.startswith("Table") and kind == "Table":
            acts = [a for a in (props.get("rowActions") or []) if isinstance(a, dict)]
            if any(str(a.get("workflow")) == d.workflow_id for a in acts) \
                    or str((props.get("emptyAction") or {}).get("workflow")) == d.workflow_id:
                return node
        elif kind == d.control and str(props.get("workflow")) == d.workflow_id \
                and _label(props, kind) == d.label:
            return node
    return None


def _sample(name: str, kind: str, typ: str, bound: bool) -> Any:
    if name == "id" or kind == "record" or bound or name.lower().endswith("id"):
        return _SAMPLE_ID
    t = (typ or "").lower()
    if t in ("integer", "int", "number", "decimal", "float", "numeric"):
        return 1
    if t in ("boolean", "bool"):
        return True
    if t in ("date",):
        return "2026-01-01"
    if t in ("timestamp", "datetime"):
        return "2026-01-01T00:00:00.000Z"
    return f"sample {name}"


def dispatches(doc: Mapping[str, Any]) -> list[dict]:
    """The manifest the projection writes for the build-time dry run: each
    control→workflow wire with the payload it sends, sampled per key from the
    workflow's declared input types."""
    out: list[dict] = []
    for d in control_dispatches(doc):
        wf = _workflow_by_id(dict(doc), d.workflow_id) or {}
        by_name = {str(i.get("name")): i for i in (wf.get("inputs") or []) if isinstance(i, dict)}
        payload = {}
        for k in sorted(d.keys):
            inp = by_name.get(k) or {}
            payload[k] = _sample(k, str(inp.get("kind") or ""), str(inp.get("type") or ""), k in d.bound)
        out.append({"workflow": d.workflow_id, "page": d.page_id, "route": d.route,
                    "control": d.control, "label": d.label, "input": payload})
    return out


__all__ = ["field_kind_findings", "Dispatch", "control_dispatches", "projected_layout", "step_refs", "workflow_ref_findings",
           "dispatch_findings", "dispatches", "RUNTIME_HEADS"]

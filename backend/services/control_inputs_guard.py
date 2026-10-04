"""Post-generate guard: a control must be able to supply what its process needs.

Symptom (UAT F&B, fxa532bj). The admin's "Mark all read (7)" button answered
HTTP 422. The workflow it runs was added mid-chat and declares a REQUIRED
input (the acting user / one notification) that a "mark all" button has no way
to send; the runtime refuses a run whose required input arrives empty
(``missingRequiredInputs``) and says nothing at build time. The Blueprint's
page checks (``dispatch_contract``) only see the Blueprint document; a
workflow edited afterwards, or a page the Blueprint never described, reaches
the shipped app unchecked. This guard reads the SHIPPED files.

For every control that starts a workflow — a Button/IconButton/Link, a Form,
a Table row/empty action — it lists each required input of that workflow and
asks whether anything the control has can supply it:

  * ``args`` the control itself carries;
  * a field of the Form it submits or sits inside;
  * the row it sits on (``id``, or a declared record input) / the record a
    ``[param]`` page shows;
  * the input's own declared ``source`` (auth / static / computed, a route
    param the page has, a form field the form has).

An input nothing supplies is a finding (page, control, workflow, input). It is
then REPAIRED only where that is safe, never by guessing data:

  * the input is the ACTING USER (``userId``/``actorId``/… or ``source.kind:
    auth``) — the engine already has the signed-in user, so the workflow stops
    demanding it and its steps read ``{{user.id}}``;
  * no step reads the input at all — it was decorative, so it stops being
    required.

Anything else stays a blocking warning naming the control and the input, which
``capture_guard_logs`` turns into a failure Smith must answer.

Idempotent (a repaired workflow no longer lists the input) and never raises.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
from typing import Any

from services.component_nodes import DATA_COMPONENTS, DATA_KEYS, is_component
from services.guard_io import dump_like, read_raw, write_atomic
from services.binding_validator import _BUTTON_TYPES, _ROW_CONTAINER_TYPES, _canon

logger = logging.getLogger(__name__)

_CLICK_TYPES = _BUTTON_TYPES | {"link", "confirmdialog", "navlink"}

# Names that UNAMBIGUOUSLY mean "whoever is signed in". `source.kind: auth` says
# the same. A bare `user`/`userId` does not: it is as often the person acted ON.
_ACTING_USER = {
    "actor", "actorid", "currentuser", "currentuserid",
    "actinguser", "actinguserid", "signedinuser", "signedinuserid",
    "loggedinuser", "loggedinuserid", "me", "myid", "requesterid", "requestedbyid",
    "createdbyid", "createdby", "performedbyid", "submittedbyid", "authorid",
}
_BARE_USER = {"user", "userid"}
# Words that say the workflow acts ON somebody else.
_OTHER_PERSON = re.compile(r"assign|reassign|transfer|delegat|hand\s?over|invite|grant|"
                           r"approve for|on behalf|owner|assignee|promote|demote|remove user|add user", re.I)
_USERISH_FIELD = re.compile(r"user|assignee|member|employee|person|staff|owner|agent|recipient", re.I)

_WF_DIRS = (("workflows",), ("src", "lib", "workflows", "definitions"))


def _load_workflows(root: str) -> list[dict]:
    """[{path, doc, keys, required, meta}] for every workflow file."""
    out: list[dict] = []
    for parts in _WF_DIRS:
        for fp in sorted(glob.glob(os.path.join(root, *parts, "*.json"))):
            try:
                raw = read_raw(fp)
                doc = json.loads(raw)
            except (OSError, ValueError) as exc:
                logger.warning("control_inputs_guard: cannot read %s: %s", os.path.relpath(fp, root), exc)
                continue
            if not isinstance(doc, dict):
                continue
            meta = {str(i["name"]): i for i in (doc.get("inputs") or [])
                    if isinstance(i, dict) and i.get("name")}
            if isinstance(doc.get("requiredInputs"), list):
                required = [str(n) for n in doc["requiredInputs"] if n]
            else:
                required = [n for n, i in meta.items() if i.get("required")]
            if not required:
                continue
            keys = {_canon(k) for k in (doc.get("id"), doc.get("name"),
                                        os.path.basename(fp)[:-5]) if k}
            out.append({"path": fp, "doc": doc, "raw": raw, "keys": keys,
                        "required": required, "meta": meta})
    return out


def _form_fields(node: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        for f in props.get("fields") or []:
            if isinstance(f, dict) and f.get("name"):
                names.add(str(f["name"]))
        if isinstance(props.get("name"), str):
            names.add(props["name"])
        for v in node.values():
            names |= _form_fields(v)
    elif isinstance(node, list):
        for v in node:
            names |= _form_fields(v)
    return names


def _args_of(holder: dict) -> set[str]:
    for h in (holder.get("props"), holder.get("action"), holder.get("onClick"), holder):
        if isinstance(h, dict) and isinstance(h.get("args"), dict):
            return {str(k) for k in h["args"]}
    return set()


def _wf_ref(holder: dict) -> str | None:
    for h in (holder, holder.get("props"), holder.get("action"), holder.get("onClick")):
        if isinstance(h, dict) and isinstance(h.get("workflow"), str) and h["workflow"].strip():
            return h["workflow"].strip()
    return None


def _label(holder: dict, fallback: str) -> str:
    p = holder.get("props") if isinstance(holder.get("props"), dict) else {}
    return str(p.get("label") or holder.get("label") or p.get("submitLabel")
               or p.get("title") or p.get("aria-label") or fallback)


def _controls(page: dict):
    """Yield (control_kind, label, workflow_ref, supplied_names, row_ctx)."""
    route = str(page.get("route") or "")
    route_params = {a or b for a, b in re.findall(r"\[(\w+)\]|:(\w+)", route)}
    has_record = bool(route_params) and any(
        isinstance(s, dict) and s.get("op") == "get" for s in page.get("dataSources") or [])

    def walk(node, forms, row_ctx):
        if isinstance(node, list):
            for n in node:
                yield from walk(n, forms, row_ctx)
            return
        if not isinstance(node, dict):
            return
        # A record with a `type` column is data, not a control.
        is_comp = is_component(node) or (isinstance(node.get("component"), str) and not isinstance(node.get("type"), str))
        ntype = _canon(node.get("type") or node.get("component")) if is_comp else ""
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        inner_forms = forms + [node] if ntype == "form" else forms
        if props.get("rowActions") or props.get("emptyAction"):
            for i, a in enumerate(props.get("rowActions") or []):
                if isinstance(a, dict) and isinstance(a.get("workflow"), str) and a["workflow"]:
                    yield ("row action", _label(a, f"row action {i}"), a["workflow"],
                           _args_of(a) | {"id"}, True)
            ea = props.get("emptyAction")
            if isinstance(ea, dict) and isinstance(ea.get("workflow"), str) and ea["workflow"]:
                yield ("empty action", _label(ea, "empty action"), ea["workflow"], _args_of(ea), row_ctx)
        ref = _wf_ref(node)
        if ref and (ntype == "form" or ntype in _CLICK_TYPES):
            fields: set[str] = set()
            for f in inner_forms:
                fields |= _form_fields(f)
            kind = "form" if ntype == "form" else (node.get("type") or "button")
            yield (str(kind), _label(node, str(kind)), ref, _args_of(node) | fields, row_ctx)
        child_row = row_ctx or ntype in _ROW_CONTAINER_TYPES
        data_comp = ntype in DATA_COMPONENTS
        for k, v in node.items():
            if k in DATA_KEYS or (data_comp and k == "props"):
                continue                      # records, not controls
            if isinstance(v, (dict, list)):
                yield from walk(v, inner_forms, child_row)

    for kind, label, ref, supplied, row_ctx in walk(page.get("root"), [], False):
        yield kind, label, ref, supplied, row_ctx, route_params, has_record


def _supplies(inp: str, meta: dict, supplied: set[str], row_ctx: bool,
              route_params: set[str], has_record: bool, record_names: set[str]) -> bool:
    if inp in supplied:
        return True
    if (row_ctx or has_record) and (inp == "id" or inp in record_names):
        return True
    src = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    kind = src.get("kind")
    if kind in ("auth", "static", "computed"):
        return True
    if kind == "route" and src.get("param") in route_params:
        return True
    if kind == "form_field" and src.get("field") in supplied:
        return True
    return False


def _value_tokens(doc: dict, name: str) -> tuple[int, int]:
    """(every mention of ``name`` in a step's string values, mentions that are
    exactly ``{{name}}``). The inputs' own declarations are not mentions."""
    tok = re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(name) + r"(?![A-Za-z0-9_])")
    # The engine resolves a workflow input under several heads; every one is a read.
    heads = re.compile(r"(?<![A-Za-z0-9_.])(?:inputs?|trigger|variables|vars)\." + r"(?=" + re.escape(name) + r"(?![A-Za-z0-9_]))")
    exact = re.compile(r"\{\{\s*" + re.escape(name) + r"\s*\}\}")
    total = ex = 0

    def walk(o: Any) -> None:
        nonlocal total, ex
        if isinstance(o, dict):
            for k, v in o.items():
                if k not in ("requiredInputs", "inputs", "recordInputs"):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            total += len(tok.findall(heads.sub("", o)))
            ex += len(exact.findall(o))
    walk(doc)
    return total, ex


def _acting_user_verdict(name: str, meta: dict, w: dict, label: str, supplied: set[str],
                         row_ctx: bool) -> str:
    """"acting" (bind to the signed-in user), "ambiguous" (could be the person
    acted on: a finding, never a guess) or "no" (not a user input)."""
    src = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    if src.get("kind") == "auth" or _canon(name) in _ACTING_USER:
        return "acting"
    if _canon(name) not in _BARE_USER:
        return "no"
    doc = w["doc"]
    steps = " ".join(str((n.get("data") or {}).get("label") or n.get("label") or "")
                     for n in ((doc.get("definition") or {}).get("nodes") or []) if isinstance(n, dict))
    story = f"{doc.get('name') or ''} {doc.get('purpose') or ''} {label} {steps}"
    other_user_value = any(_USERISH_FIELD.search(x) and _canon(x) != _canon(name) for x in supplied)
    if _OTHER_PERSON.search(story) or other_user_value or row_ctx:
        return "ambiguous"
    return "acting"


def _bind_to_user(doc: dict, name: str) -> None:
    """Steps read the signed-in user instead of an input nobody can send."""
    pat = re.compile(r"\{\{\s*" + re.escape(name) + r"\s*\}\}")

    def walk(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str):
            return pat.sub("{{user.id}}", o)
        return o

    for key in [k for k in doc if k not in ("requiredInputs", "inputs")]:
        doc[key] = walk(doc[key])


def ensure_controls_supply_inputs(output_dir: str) -> dict:
    """Detect (and where safe repair) controls that cannot supply a required
    input of the workflow they run. Never raises.

    Returns ``{"findings": [...], "repaired": [...], "workflows_touched": [...]}``;
    ``findings`` are the UNRESOLVED ones, each ``{page, control, label, workflow,
    input, detail}``.
    """
    report: dict = {"findings": [], "repaired": [], "workflows_touched": []}
    try:
        root = str(output_dir)
        wfs = _load_workflows(root)
        sdir = os.path.join(root, "src", "schemas")
        if not wfs or not os.path.isdir(sdir):
            return report
        by_key: dict[str, dict] = {}
        for w in wfs:
            for k in w["keys"]:
                by_key.setdefault(k, w)

        gaps: list[tuple] = []   # (page, kind, label, wf, input, supplied, row_ctx)
        for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
            if os.path.basename(fp) in ("shell.json", "nav-flow.json"):
                continue
            rel = os.path.relpath(fp, sdir).replace(os.sep, "/")
            try:
                with open(fp, encoding="utf-8") as fh:
                    page = json.load(fh)
            except (OSError, ValueError) as exc:
                logger.warning("control_inputs_guard: cannot read %s: %s", rel, exc)
                continue
            if not isinstance(page, dict):
                continue
            for kind, label, ref, supplied, row_ctx, rparams, has_rec in _controls(page):
                w = by_key.get(_canon(ref))
                if w is None:
                    continue
                recs = {str(r.get("name")) for r in w["doc"].get("recordInputs") or []
                        if isinstance(r, dict) and r.get("name")}
                recs |= {n for n, i in w["meta"].items() if i.get("kind") == "record"}
                for inp in w["required"]:
                    if not _supplies(inp, w["meta"].get(inp, {}), supplied, row_ctx,
                                     rparams, has_rec, recs):
                        gaps.append((rel, kind, label, w, inp, supplied, row_ctx))

        touched: set[str] = set()
        for rel, kind, label, w, inp, supplied, row_ctx in gaps:
            if inp not in w["required"]:
                continue  # already repaired for an earlier control
            meta = w["meta"].get(inp, {})
            name = str(w["doc"].get("name") or w["doc"].get("id"))
            total, exact = _value_tokens(w["doc"], inp)
            fix = None
            verdict = _acting_user_verdict(inp, meta, w, label, supplied, row_ctx)
            if verdict == "acting" and total == exact:
                _bind_to_user(w["doc"], inp)
                fix = "now read from the signed-in user ({{user.id}})"
            elif verdict == "no" and total == 0:
                fix = "no step reads it, so it is no longer required"
            if fix:
                w["required"].remove(inp)
                if "requiredInputs" in w["doc"]:
                    w["doc"]["requiredInputs"] = list(w["required"])
                for i in w["doc"].get("inputs") or []:
                    if isinstance(i, dict) and i.get("name") == inp:
                        i["required"] = False
                touched.add(w["path"])
                report["repaired"].append({"page": rel, "control": kind, "label": label,
                                           "workflow": name, "input": inp, "fix": fix})
        seen: set[tuple] = set()
        for rel, kind, label, w, inp, supplied, row_ctx in gaps:
            if inp not in w["required"] or (rel, kind, label, w["path"], inp) in seen:
                continue
            seen.add((rel, kind, label, w["path"], inp))
            name = str(w["doc"].get("name") or w["doc"].get("id"))
            near = next((f for f in supplied if f != inp and f.lower() == inp.lower()), None)
            hint = (f" (the control has a field {near!r}; the runtime matches names exactly, "
                    f"so it differs from {inp!r} by case)") if near else ""
            who = ""
            if _canon(inp) in _BARE_USER:
                who = (f" {inp!r} may be the person acted on rather than the signed-in user, so it was "
                       f"not bound to the signed-in user.")
            detail = (f"{rel}: {kind} {label!r} runs {name}, which needs {inp!r}, but nothing "
                      f"the control has can supply it (no args, form field, row/record, or "
                      f"declared source){hint} — the run is refused with HTTP 422. Pass {inp!r} in "
                      f"`args`, put the control in a Form that collects it, or make {inp!r} "
                      f"optional on the workflow.{who}")
            report["findings"].append({"page": rel, "control": kind, "label": label,
                                       "workflow": name, "input": inp, "detail": detail})
            logger.warning("control_inputs_guard: %s", detail)

        for fp in sorted(touched):
            w = next(x for x in wfs if x["path"] == fp)
            new = dump_like(w["raw"], w["doc"])
            if new != w["raw"]:
                write_atomic(fp, new)
        report["workflows_touched"] = sorted(os.path.basename(p)[:-5] for p in touched)
        for r in report["repaired"]:
            logger.info("control_inputs_guard: %s %r on %s runs %s: %r %s",
                        r["control"], r["label"], r["page"], r["workflow"], r["input"], r["fix"])
    except Exception:  # noqa: BLE001 — the guard must never crash the pipeline
        logger.exception("control_inputs_guard: internal error after repairing %s (written files stay "
                         "written)", [r["input"] for r in report["repaired"]])
    return report

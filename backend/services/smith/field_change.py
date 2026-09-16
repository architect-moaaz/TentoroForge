"""A field is renamed or removed across the whole Blueprint, not just its entity.

"Rename yearsOfExperience to experienceYears", "drop the location field":
the field lives on the entity, but the Blueprint names it in a dozen more
places — a Table's columns, a Form's fields, a `{{nurse.location}}`
binding, a workflow's `values` and its `{{location}}` reads, a rule's
`when`, a relationship's `fromField`, the entity's `labelField`. The
legacy seam edited the drizzle column and the registry and left every one
of those pointing at a name that no longer existed.

Deterministic, no model: the references are found by walking the document
and rewritten (rename) or taken out (remove), each one reported. What
cannot be rewritten safely — a text binding whose node would be left
meaningless — is left and named, and the action-integrity checks carry it
to Verify & Fix. The column reaches the database as a migration on the
next install; a rename may be applied there as drop-and-add, so say so.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import SectionChangeError, find_named, names

logger = logging.getLogger(__name__)

_MANAGED = frozenset({"id", "createdat", "updatedat", "deletedat", "created_at", "updated_at", "deleted_at"})


def _entities(doc: dict) -> list[dict]:
    return [e for e in ((doc.get("data") or {}).get("entities") or []) if isinstance(e, dict)]


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") not in ("DEPRECATED", "SUPERSEDED")]


def find_field(doc: dict, entity_ref: str, field_ref: str) -> tuple[dict, dict]:
    ent = find_named(_entities(doc), entity_ref)
    if ent is None:
        raise SectionChangeError(f"I cannot tell which entity {entity_ref!r} means. The entities are: {names(_entities(doc))}.")
    want = (field_ref or "").strip().lower()
    fields = [f for f in (ent.get("fields") or []) if isinstance(f, dict)]
    fld = next((f for f in fields if str(f.get("name") or "").lower() == want), None)
    if fld is None:
        hits = [f for f in fields if want and want in str(f.get("name") or "").lower()]
        fld = hits[0] if len(hits) == 1 else None
    if fld is None:
        raise SectionChangeError(f"{ent.get('name')} has no field {field_ref!r}. Its fields are: "
                                 f"{', '.join(str(f.get('name')) for f in fields) or '(none)'}.")
    if str(fld.get("name") or "").lower() in _MANAGED or fld.get("primaryKey"):
        raise SectionChangeError(f"{fld.get('name')} is a managed column (the key, or a timestamp the application sets); "
                                 "it is contract and cannot be renamed or removed.")
    return ent, fld


def _binding_re(name: str) -> re.Pattern:
    # `{{name}}`, `{{record.name}}`, `{{nurses.0.name}}`, `{{ name }}` — the field as a segment
    # after any number of head segments (an index like `0` is a segment too).
    return re.compile(r"(\{\{\s*(?:[\w]+\.)*)" + re.escape(name) + r"(\s*(?:\.[\w]+)*\s*\}\})")


def _word_re(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w.])" + re.escape(name) + r"(?![\w])")


def _rewrite_strings(node: Any, pattern: re.Pattern, repl: str, hits: list[str], where: str) -> Any:
    if isinstance(node, str):
        if pattern.search(node):
            hits.append(f"{where}: {node[:60]}")
            return pattern.sub(repl, node)
        return node
    if isinstance(node, list):
        return [_rewrite_strings(c, pattern, repl, hits, where) for c in node]
    if isinstance(node, dict):
        return {k: _rewrite_strings(v, pattern, repl, hits, where) for k, v in node.items()}
    return node


def _touches_entity(doc: dict, layout: dict, eid: str, ename: str) -> bool:
    page = next((p for p in doc.get("pages") or [] if str(p.get("id")) == str(layout.get("page"))), {})
    if str((page.get("data") or {}).get("primaryEntity") or "") == eid:
        return True
    return any(str(s.get("entity") or "") in (eid, ename) for s in (layout.get("dataSources") or []) if isinstance(s, dict))


def rename_field(svc: Any, entity_ref: str, field_ref: str, new_name: str, *, app_root: str | None = None,
                 reasoning: Any = None) -> dict:
    from services.blueprint.functional_completeness import _workflow_targets_entity
    new_name = (new_name or "").strip()
    if not re.fullmatch(r"[A-Za-z_][\w]*", new_name):
        raise SectionChangeError(f"{new_name!r} is not a field name — letters, digits and underscores, starting with a letter.")
    ent, fld = find_field(svc.doc, entity_ref, field_ref)
    old = str(fld["name"])
    if old == new_name:
        raise SectionChangeError(f"{ent.get('name')}.{old} already has that name.")
    if any(str(f.get("name") or "").lower() == new_name.lower() for f in ent.get("fields") or [] if f is not fld):
        raise SectionChangeError(f"{ent.get('name')} already has a field named {new_name!r}.")
    eid, ename = str(ent["id"]), str(ent.get("name") or "")
    before = svc.snapshot()
    hits: list[str] = []
    fld["name"] = new_name
    hits.append(f"{ename}.{old}")
    if str(ent.get("labelField") or "") == old:
        ent["labelField"] = new_name
        hits.append(f"{ename}.labelField")
    for r in (svc.doc.get("data") or {}).get("relationships") or []:
        for k, side in (("fromField", "from"), ("toField", "to")):
            if isinstance(r, dict) and str(r.get(side)) == eid and str(r.get(k) or "") == old:
                r[k] = new_name
                hits.append(f"relationship {r.get('from')}→{r.get('to')} {k}")
    bind = _binding_re(old)
    bind_repl = r"\g<1>" + new_name + r"\g<2>"
    for layout in _live(svc.doc.get("pageLayouts")):
        if not _touches_entity(svc.doc, layout, eid, ename):
            continue
        page_id = str(layout.get("page"))
        for node in _walk(layout.get("root")):
            props = node.get("props") or {}
            for col in props.get("columns") or []:
                if isinstance(col, dict) and str(col.get("key") or "") == old:
                    col["key"] = new_name
                    hits.append(f"{page_id}: Table column")
            for f in props.get("fields") or []:
                if isinstance(f, dict) and str(f.get("name") or "") == old:
                    f["name"] = new_name
                    hits.append(f"{page_id}: Form field")
        layout["root"] = _rewrite_strings(layout.get("root"), bind, bind_repl, hits, f"{page_id}: binding")
        layout["dataSources"] = _rewrite_strings(layout.get("dataSources") or [], bind, bind_repl, hits, f"{page_id}: data source")
    for wf in _live(svc.doc.get("workflows")):
        if not _workflow_targets_entity(svc.doc, wf, eid):
            continue
        wid = str(wf.get("id"))
        for inp in wf.get("inputs") or []:
            if isinstance(inp, dict) and inp.get("kind") == "field" and str(inp.get("name") or "") == old:
                inp["name"] = new_name
                hits.append(f"{wid}: input")
        for st in wf.get("steps") or []:
            cfg = st.get("config") if isinstance(st, dict) else None
            if not isinstance(cfg, dict):
                continue
            for key in ("values", "where"):
                m = cfg.get(key)
                if isinstance(m, dict) and old in m:
                    m[new_name] = m.pop(old)
                    hits.append(f"{wid}: step {st.get('key')} {key}")
            # A condition step's FEEL expression names the field bare —
            # `yearsOfExperience > 60` — with no braces to find it by.
            for key in ("expression", "condition"):
                if isinstance(cfg.get(key), str) and _word_re(old).search(cfg[key]):
                    cfg[key] = _word_re(old).sub(new_name, cfg[key])
                    hits.append(f"{wid}: step {st.get('key')} {key}")
            st["config"] = _rewrite_strings(cfg, bind, bind_repl, hits, f"{wid}: step {st.get('key')} binding")
    for w in _live(svc.doc.get("widgets")):
        src = w.get("dataSource") if isinstance(w.get("dataSource"), dict) else None
        if src and str(src.get("entity") or "") in (eid, ename):
            fields = src.get("fields")
            if isinstance(fields, list) and old in fields:
                src["fields"] = [new_name if f == old else f for f in fields]
                hits.append(f"{w.get('id')}: widget field")
            for key in ("groupBy", "sortBy", "valueField", "labelField", "field"):
                if str(src.get(key) or "") == old:
                    src[key] = new_name
                    hits.append(f"{w.get('id')}: widget {key}")
    word = _word_re(old)
    for rule in _live(svc.doc.get("businessRules")):
        if str(rule.get("entity") or "") != eid:
            continue
        rid = str(rule.get("id"))
        for key in ("when", "expression"):
            if isinstance(rule.get(key), str) and word.search(rule[key]):
                rule[key] = word.sub(new_name, rule[key])
                hits.append(f"{rid}: {key}")
        for act in list(rule.get("then") or []) + list(rule.get("otherwise") or []):
            if isinstance(act, dict) and str(act.get("field") or "") == old:
                act["field"] = new_name
                hits.append(f"{rid}: action field")
    svc.validate()
    svc.commit(user_request=f"rename {ename}.{old} to {new_name}",
               smith_interpretation=f"rename the field across {len(hits)} reference(s)",
               before=before, affected=sorted({eid, *[h.split(':')[0] for h in hits if ':' in h]}))
    tell(reasoning, f"Renamed {ename}.{old} to {new_name} in {len(hits)} place(s).", "step")
    return {"applied": True, "entity": eid, "name": ename, "old": old, "new": new_name, "hits": hits,
            "edited_paths": _project(svc, app_root)}


_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Where a field lands on a screen, in the words the reply uses.
FORM_FIELD = "form field"
TABLE_COLUMN = "table column"


def label_of(name: str, label: str = "") -> str:
    """The words a person sees for a field: theirs if they said them
    ("Father's Name"), else the name spelled out by the same helper the
    templates use, so a field added in conversation is labelled exactly as
    one the build wrote."""
    from services.blueprint.template_page import _humanise
    return str(label).strip() if str(label or "").strip() else _humanise(str(name or ""))


def _control_for(field: dict, label: str = "") -> dict:
    """The Form field a Blueprint field becomes, from the ONE place that
    decides it.

    A private map here read `string -> text, integer -> number` and stopped:
    a list column (`string[]`) became a plain text box rather than the `tags`
    control the contract requires — the raw-JSON-in-a-textbox defect, re-made
    one module over — and an enum column lost its options. `template_page`
    already answers this for every page the build writes, including the
    `required` and `options` keys; a second answer is one that drifts.
    """
    from services.blueprint.template_page import _field_kind
    spec = _field_kind(field)
    # A NEW FIELD IS NEVER REQUIRED: the rows that already exist have no value
    # for it, so the form must accept one without it.
    spec["required"] = False
    if str(label or "").strip():
        spec["label"] = str(label).strip()
    return spec


def _column_for(field: dict, label: str = "") -> dict:
    """The Table column a Blueprint field becomes — same rule, same module,
    so a date is formatted as a date rather than printed raw."""
    from services.blueprint.template_page import _column
    col = _column(field)
    if str(label or "").strip():
        col["label"] = str(label).strip()
    return col


def _names_of(ent: dict) -> set[str]:
    return {str(f.get("name") or "") for f in (ent.get("fields") or []) if isinstance(f, dict)}


def _surface(svc: Any, ent: dict, field: dict, label: str, known: set[str],
             only_page: str | None = None) -> list[dict]:
    """Put field `name` on every live layout that edits or lists `ent`.

    A Form that already carries some of the entity's fields is a form for
    this entity and gets the control; a Table whose columns are the entity's
    fields gets the column. A form or table for another entity on the same
    page does not. `only_page` narrows it to one page id.
    """
    eid, ename = str(ent["id"]), str(ent.get("name") or "")
    name = str(field.get("name") or "")
    surfaced: list[dict] = []
    pages = {str(p.get("id")): p for p in (svc.doc.get("pages") or []) if isinstance(p, dict)}
    for layout in _live(svc.doc.get("pageLayouts")):
        if only_page is not None and str(layout.get("page")) != str(only_page):
            continue
        if not _touches_entity(svc.doc, layout, eid, ename):
            continue
        page = pages.get(str(layout.get("page"))) or {}
        route = str(page.get("route") or layout.get("page") or "")
        pname = str(page.get("name") or route)
        for node in _walk(layout.get("root")):
            props = node.get("props") or {}
            flds = props.get("fields")
            if node.get("type") == "Form" and isinstance(flds, list) and any(
                    isinstance(f, dict) and str(f.get("name") or "") in known for f in flds):
                if not any(isinstance(f, dict) and str(f.get("name") or "") == name for f in flds):
                    flds.append(_control_for(field, label))
                    surfaced.append({"page": pname, "route": route, "where": FORM_FIELD})
            cols = props.get("columns")
            if node.get("type") == "Table" and isinstance(cols, list) and any(
                    isinstance(c, dict) and str(c.get("key") or "") in known for c in cols):
                if not any(isinstance(c, dict) and str(c.get("key") or "") == name for c in cols):
                    cols.append(_column_for(field, label))
                    surfaced.append({"page": pname, "route": route, "where": TABLE_COLUMN})
    return surfaced


def _present(svc: Any, ent: dict, name: str, only_page: str | None = None) -> list[dict]:
    """Where field `name` already is on the live layouts of `ent`'s screens."""
    eid, ename = str(ent["id"]), str(ent.get("name") or "")
    pages = {str(p.get("id")): p for p in (svc.doc.get("pages") or []) if isinstance(p, dict)}
    out: list[dict] = []
    for layout in _live(svc.doc.get("pageLayouts")):
        if only_page is not None and str(layout.get("page")) != str(only_page):
            continue
        if not _touches_entity(svc.doc, layout, eid, ename):
            continue
        page = pages.get(str(layout.get("page"))) or {}
        route = str(page.get("route") or layout.get("page") or "")
        pname = str(page.get("name") or route)
        for node in _walk(layout.get("root")):
            props = node.get("props") or {}
            if node.get("type") == "Form" and any(isinstance(f, dict) and str(f.get("name") or "") == name
                                                  for f in (props.get("fields") or [])):
                out.append({"page": pname, "route": route, "where": FORM_FIELD})
            if node.get("type") == "Table" and any(isinstance(c, dict) and str(c.get("key") or "") == name
                                                   for c in (props.get("columns") or [])):
                out.append({"page": pname, "route": route, "where": TABLE_COLUMN})
    return out


def show_field(svc: Any, entity_ref: str, field_ref: str, *, page_id: str | None = None,
               label: str = "", app_root: str | None = None, reasoning: Any = None) -> dict:
    """Put an EXISTING field on the screens that edit or list its entity.

    "I cannot see it on the Nurse Registration page" after a field was added
    went to the AI composer, which re-laid the page out and left the field
    off. A field the entity already has needs no composition: it goes onto
    the form and the table the same way a new one does.
    """
    ent, fld = find_field(svc.doc, entity_ref, field_ref)
    name = str(fld["name"])
    before = svc.snapshot()
    known = _names_of(ent) - _MANAGED
    surfaced = _surface(svc, ent, fld, label_of(name, label), known, only_page=page_id)
    if not surfaced:
        # ALREADY THERE. The Blueprint has the control; if the person cannot
        # see it, the running app is behind the Blueprint, so the screens
        # are projected again and the reply says where the field already is.
        already = _present(svc, ent, name, only_page=page_id)
        return {"applied": bool(already), "entity": str(ent["id"]), "name": str(ent.get("name") or ""),
                "field": name, "surfaced": [], "already": already,
                "edited_paths": _project(svc, app_root) if already else []}
    svc.validate()
    svc.commit(user_request=f"show {ent.get('name')}.{name}",
               smith_interpretation=f"put the field on {len(surfaced)} screen element(s)",
               before=before, affected=sorted({str(ent["id"])}))
    tell(reasoning, f"Put {ent.get('name')}.{name} on {len(surfaced)} screen element(s).", "step")
    return {"applied": True, "entity": str(ent["id"]), "name": str(ent.get("name") or ""), "field": name,
            "surfaced": surfaced, "edited_paths": _project(svc, app_root)}


def add_field(svc: Any, entity_ref: str, field: dict, *, app_root: str | None = None,
              reasoning: Any = None) -> dict:
    """Add a field to an entity AND put it where that entity is edited or listed.

    "Add father's name in the Nurse Registration" is one ask: a column, and the
    control that lets someone fill it in. The first cut added the column and
    told the person to ask again for the screen — and the second ask went to
    the AI composer, which re-laid the page out and left the field off it.
    The screens that show this entity are known from the Blueprint — every
    live layout whose Form edits its fields or whose Table lists them — so the
    field goes onto each of them here, deterministically, and the reply names
    every place it went. A new field is never required: existing rows have
    no value for it, and the column must be nullable for the migration to apply.
    """
    ent = find_named(_entities(svc.doc), entity_ref)
    if ent is None:
        raise SectionChangeError(f"I cannot tell which entity {entity_ref!r} means. The entities are: {names(_entities(svc.doc))}.")
    name = str((field or {}).get("name") or "").strip()
    if not _FIELD_NAME.fullmatch(name):
        raise SectionChangeError(
            f"{name!r} is not a field name: letters, digits and underscores, "
            "starting with a letter, in the app's own style.")
    clash = next((f for f in _names_of(ent) if f.lower() == name.lower()), None)
    if clash:
        raise SectionChangeError(f"{ent.get('name')} already has a field named {clash}, so I changed nothing.")
    ftype = str((field or {}).get("type") or "string").strip() or "string"
    eid, ename = str(ent["id"]), str(ent.get("name") or "")
    known = _names_of(ent) - _MANAGED
    before = svc.snapshot()
    declared = {"name": name, "type": ftype, "required": False}
    ent.setdefault("fields", []).append(declared)
    label = label_of(name, str((field or {}).get("label") or ""))

    surfaced = _surface(svc, ent, declared, label, known)
    svc.validate()
    svc.commit(user_request=f"add {ename}.{name}",
               smith_interpretation=f"add the field and show it in {len(surfaced)} place(s)",
               before=before,
               affected=sorted({eid, *[str(layout_page) for layout_page in
                                       {l.get("page") for l in _live(svc.doc.get("pageLayouts"))
                                        if _touches_entity(svc.doc, l, eid, ename)}]}))
    tell(reasoning, f"Added {ename}.{name} and put it on {len(surfaced)} screen element(s).", "step")
    return {"applied": True, "entity": eid, "name": ename, "field": name, "type": ftype, "label": label,
            "surfaced": surfaced, "edited_paths": _project(svc, app_root)}


def consequences(doc: dict, entity_ref: str, field_ref: str) -> dict:
    """Where a field is used, WITHOUT removing any of it — so the question
    can name what goes before it goes. The column's data goes with it, and
    that is the part no undo of the Blueprint brings back."""
    try:
        ent, fld = find_field(doc, entity_ref, field_ref)
    except SectionChangeError as exc:
        return {"found": False, "reason": str(exc)}
    name = str(fld.get("name"))
    eid, ename = str(ent["id"]), str(ent.get("name") or "")
    pages = {str(p.get("id")): p for p in (doc.get("pages") or []) if isinstance(p, dict)}
    used: list[str] = []
    for layout in _live(doc.get("pageLayouts")):
        if not _touches_entity(doc, layout, eid, ename):
            continue
        page = pages.get(str(layout.get("page"))) or {}
        where = str(page.get("name") or page.get("route") or "")
        for node in _walk(layout.get("root")):
            props = node.get("props") or {}
            # `columns` is a count on some components and a list on others,
            # so the shape is checked rather than assumed.
            fields = props.get("fields") if isinstance(props.get("fields"), list) else []
            columns = props.get("columns") if isinstance(props.get("columns"), list) else []
            if any(isinstance(f, dict) and str(f.get("name") or "") == name for f in fields):
                used.append(f"the form on {where}")
            if any(isinstance(c, dict) and str(c.get("key") or "") == name for c in columns):
                used.append(f"the table on {where}")
    word = _word_re(name)
    rules = [str(r.get("name")) for r in _live(doc.get("businessRules"))
             if str(r.get("entity") or "") == eid
             and (any(isinstance(r.get(k), str) and word.search(r[k]) for k in ("when", "expression"))
                  or any(isinstance(a, dict) and str(a.get("field") or "") == name
                         for a in list(r.get("then") or []) + list(r.get("otherwise") or [])))]
    flows = [str(w.get("name")) for w in _live(doc.get("workflows"))
             if word.search(json.dumps(w.get("inputs") or [])) or word.search(json.dumps(w.get("steps") or []))]
    return {"found": True, "entity": ename, "field": name,
            "used": sorted(set(used)), "rules": rules, "workflows": sorted(set(flows))}


def remove_field(svc: Any, entity_ref: str, field_ref: str, *, app_root: str | None = None,
                 reasoning: Any = None) -> dict:
    from services.blueprint.functional_completeness import _workflow_targets_entity
    ent, fld = find_field(svc.doc, entity_ref, field_ref)
    old = str(fld["name"])
    eid, ename = str(ent["id"]), str(ent.get("name") or "")
    before = svc.snapshot()
    removed: list[str] = []
    left: list[str] = []
    ent["fields"] = [f for f in ent.get("fields") or [] if f is not fld]
    removed.append(f"{ename}.{old}")
    if str(ent.get("labelField") or "") == old:
        ent.pop("labelField", None)
        removed.append(f"{ename}.labelField")
    data = svc.doc.get("data") or {}
    rels = data.get("relationships") or []
    kept = [r for r in rels if not (isinstance(r, dict) and (
        (str(r.get("from")) == eid and str(r.get("fromField") or "") == old) or
        (str(r.get("to")) == eid and str(r.get("toField") or "") == old)))]
    if len(kept) != len(rels):
        removed.append(f"{len(rels) - len(kept)} relationship(s)")
        data["relationships"] = kept
    bind = _binding_re(old)
    for layout in _live(svc.doc.get("pageLayouts")):
        if not _touches_entity(svc.doc, layout, eid, ename):
            continue
        page_id = str(layout.get("page"))
        for node in _walk(layout.get("root")):
            props = node.get("props") or {}
            cols = props.get("columns")
            if isinstance(cols, list) and any(isinstance(c, dict) and str(c.get("key") or "") == old for c in cols):
                props["columns"] = [c for c in cols if not (isinstance(c, dict) and str(c.get("key") or "") == old)]
                removed.append(f"{page_id}: Table column")
            flds = props.get("fields")
            if isinstance(flds, list) and any(isinstance(f, dict) and str(f.get("name") or "") == old for f in flds):
                props["fields"] = [f for f in flds if not (isinstance(f, dict) and str(f.get("name") or "") == old)]
                removed.append(f"{page_id}: Form field")
            items = props.get("items")
            if isinstance(items, list):
                keep_items = [i for i in items if not (isinstance(i, dict) and any(
                    isinstance(v, str) and bind.search(v) for v in i.values()))]
                if len(keep_items) != len(items):
                    props["items"] = keep_items
                    removed.append(f"{page_id}: DescriptionList item")
        for node in _walk(layout.get("root")):
            for k, v in (node.get("props") or {}).items():
                if isinstance(v, str) and bind.search(v):
                    left.append(f"{page_id}: {node.get('type')}.{k} still reads {{{{…{old}}}}}")
    for wf in _live(svc.doc.get("workflows")):
        if not _workflow_targets_entity(svc.doc, wf, eid):
            continue
        wid = str(wf.get("id"))
        inputs = wf.get("inputs") or []
        kept_in = [i for i in inputs if not (isinstance(i, dict) and i.get("kind") == "field" and str(i.get("name") or "") == old)]
        if len(kept_in) != len(inputs):
            wf["inputs"] = kept_in
            removed.append(f"{wid}: input")
        for st in wf.get("steps") or []:
            cfg = st.get("config") if isinstance(st, dict) else None
            if not isinstance(cfg, dict):
                continue
            for key in ("values", "where"):
                m = cfg.get(key)
                if isinstance(m, dict) and old in m:
                    m.pop(old)
                    removed.append(f"{wid}: step {st.get('key')} {key}")
            if bind.search(json.dumps(cfg)):
                left.append(f"{wid}: step {st.get('key')} still reads {{{{…{old}}}}}")
            for key in ("expression", "condition"):
                if isinstance(cfg.get(key), str) and _word_re(old).search(cfg[key]):
                    left.append(f"{wid}: step {st.get('key')} {key} still names {old}")
    for w in _live(svc.doc.get("widgets")):
        src = w.get("dataSource") if isinstance(w.get("dataSource"), dict) else None
        if src and str(src.get("entity") or "") in (eid, ename):
            fields = src.get("fields")
            if isinstance(fields, list) and old in fields:
                src["fields"] = [f for f in fields if f != old]
                removed.append(f"{w.get('id')}: widget field")
            for key in ("groupBy", "sortBy", "valueField", "labelField", "field"):
                if str(src.get(key) or "") == old:
                    left.append(f"{w.get('id')}: widget {key} still names {old}")
    word = _word_re(old)
    for rule in _live(svc.doc.get("businessRules")):
        if str(rule.get("entity") or "") != eid:
            continue
        mentions = any(isinstance(rule.get(k), str) and word.search(rule[k]) for k in ("when", "expression")) or \
            any(isinstance(a, dict) and str(a.get("field") or "") == old for a in list(rule.get("then") or []) + list(rule.get("otherwise") or []))
        if mentions:
            rule["status"] = "DEPRECATED"
            removed.append(f"rule {rule.get('name')} retired")
    svc.validate()
    svc.commit(user_request=f"remove {ename}.{old}", smith_interpretation=f"remove the field and {len(removed) - 1} reference(s)",
               before=before, affected=sorted({eid, *[h.split(':')[0] for h in removed if ':' in h]}))
    tell(reasoning, f"Removed {ename}.{old} and {len(removed) - 1} reference(s).", "step")
    return {"applied": True, "entity": eid, "name": ename, "field": old, "removed": removed, "left": left,
            "edited_paths": _project(svc, app_root)}


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for c in node.get("children") or []:
            yield from _walk(c)
    elif isinstance(node, list):
        for c in node:
            yield from _walk(c)


def _project(svc: Any, app_root: str | None) -> list[str]:
    if not app_root:
        return []
    from services.blueprint.orchestrator import _project_integration
    from services.blueprint.projection import apply_frontend_projection, project_business_rules, project_data_layer
    files = list(project_data_layer(svc.doc, app_root).get("files") or [])
    _project_integration(svc, app_root)
    files += ["src/lib/workflows/definitions"]
    files += [str(f) for f in (apply_frontend_projection(svc, app_root) or {}).get("files", [])]
    try:
        files += list(project_business_rules(svc.doc, app_root).get("files") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[field] rules projection failed: %s", exc)
    return sorted(set(files))


def summary_of(verb: str, out: dict) -> str:
    if verb == "show_field":
        places = out.get("surfaced") or []
        if places:
            return (f"Put **{out['field']}** on:\n" + "\n".join(
                f"- **{p['page']}** `{p['route']}` \u2014 {p['where']}" for p in places))
        already = out.get("already") or []
        return (f"**{out['field']}** is already on:\n" + "\n".join(
            f"- **{p['page']}** `{p['route']}` \u2014 {p['where']}" for p in already)
            + "\n\nI projected the screens again so the running app matches the Blueprint; "
              "reload the page.")
    if verb == "add_field":
        lead = f"Added **{out['field']}** ({out['type']}, optional) to **{out['name']}**"
        places = out.get("surfaced") or []
        if places:
            lead += " and put it on:\n" + "\n".join(
                f"- **{p['page']}** `{p['route']}` \u2014 {p['where']}" for p in places)
        else:
            lead += (f". No screen edits or lists {out['name']} records through a form or a table "
                     "yet, so it is not on a page \u2014 say which screen should show it.")
        return lead + "\n\nThe column is added as a migration; existing rows keep their data."
    if verb == "rename_field":
        s = (f"Renamed {out['name']}.{out['old']} to {out['new']} in {len(out['hits'])} place(s): "
             f"{'; '.join(out['hits'][:8])}{'…' if len(out['hits']) > 8 else ''}. The column is renamed on the next "
             "install; the migration may drop and re-add it, so back up the column's data first if it matters.")
        return s
    s = f"Removed {out['name']}.{out['field']} and took it out of {len(out['removed']) - 1} place(s): {'; '.join(out['removed'][1:8])}."
    if out.get("left"):
        s += " Still reading it, for Verify & Fix to repair: " + "; ".join(out["left"][:6]) + "."
    s += " The column is dropped on the next install."
    return s


def run(output_dir: str, verb: str, *, entity: str = "", field: Any = "", new_value: str = "",
        reasoning: Any = None) -> dict:
    """One field change from an `output_dir` — the shape a tool handler needs.

    `field` is the field's name for a rename or a removal, and for `add_field`
    the `{name, type, label}` object (a bare name is a string field).
    """
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet, so there is no field to change."}
    app_root = str(Path(output_dir) / "app")
    try:
        if verb == "add_field":
            spec = dict(field) if isinstance(field, dict) else {"name": str(field or "")}
            out = add_field(svc, entity, spec, app_root=app_root, reasoning=reasoning)
        elif verb == "rename_field":
            out = rename_field(svc, entity, str(field or ""), new_value, app_root=app_root, reasoning=reasoning)
        elif verb == "remove_field":
            out = remove_field(svc, entity, str(field or ""), app_root=app_root, reasoning=reasoning)
        else:
            return {"applied": False, "edited_paths": [], "reason": f"unknown field verb {verb!r}"}
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] %s failed", verb)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [], "diff_summary": summary_of(verb, out),
            "reason": "", **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["add_field", "show_field", "rename_field", "remove_field", "find_field", "label_of", "run", "summary_of"]

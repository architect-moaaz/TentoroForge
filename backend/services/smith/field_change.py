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


def run(output_dir: str, verb: str, *, entity: str = "", field: str = "", new_value: str = "",
        reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet, so there is no field to change."}
    app_root = str(Path(output_dir) / "app")
    try:
        if verb == "rename_field":
            out = rename_field(svc, entity, field, new_value, app_root=app_root, reasoning=reasoning)
        elif verb == "remove_field":
            out = remove_field(svc, entity, field, app_root=app_root, reasoning=reasoning)
        else:
            return {"applied": False, "edited_paths": [], "reason": f"unknown field verb {verb!r}"}
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] %s failed", verb)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [], "diff_summary": summary_of(verb, out),
            "reason": "", **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["rename_field", "remove_field", "find_field", "run", "summary_of"]

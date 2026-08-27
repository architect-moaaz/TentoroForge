"""Resolve every cross-reference in the generated schemas against REALITY.

The context engine makes the registry the *input* to the LLM. This is its mirror:
the single authority over the *output*. It walks every reference-bearing node in
`src/schemas/*.json` and resolves each identifier against the extracted registry
(the entities/workflows/routes that were actually generated — not the early,
LLM-declared contracts), in strict order:

    1. exact       — already matches reality → keep
    2. derived     — the registry can produce the canonical value (FK column →
                     relation target, entity → its real /api/data slug, label →
                     a real field) → OVERWRITE the LLM's guess with the truth
    3. fuzzy       — near-miss (Levenshtein) → repair
    4. unresolved  — resolves to nothing → FLAG (never ship a silent lie)

Every decision is recorded in `contracts/references-report.json`, so a build
never has an invisibly-broken reference again. Idempotent: correct references
are left untouched. Best-effort — never raises.
"""
from __future__ import annotations

import glob
import json
import os
import re

from services.registry_validator import fuzzy_match
from services.form_scaffold import (
    _ent_key, _label_field, _plural, _iter_nodes, _fk_target, _load_registry,
    _role_fk_target,
)
from services.semantic_field_types import _norm


_OPTION_NODES = {"Select", "Combobox", "MultiSelect"}

# The identifier immediately after a `{{` — the dataSource a binding reads from.
# `{{applicantsRecent}}`, `{{applicantsRecent.count}}`, `{{applicantsRecent[0].x}}`.
# The head of a `{{name...}}` binding. The character class must include the
# HYPHEN because kebab-case dataSource names ("assessment-days") come from the
# list-page builder's route-slug convention; without it, the regex captures only
# "{{assessment" and step (1b) can't repoint the binding after step (1) renames
# the dataSource — the table then renders empty against a dangling ref.
_BIND_HEAD = re.compile(r"(\{\{\s*)([A-Za-z_$][\w$\-]*)")


def _repoint_bindings(obj, name_remap: dict[str, str]) -> bool:
    """Rewrite every `{{oldName...}}` binding to `{{newName...}}` for old→new in
    `name_remap`, in place, anywhere in the subtree. Returns True if anything changed.
    optionsFrom.source (a bare string, no `{{`) is untouched here — step (2) owns it."""
    if not name_remap:
        return False

    def _sub(s: str) -> str:
        return _BIND_HEAD.sub(
            lambda m: m.group(1) + name_remap[m.group(2)] if m.group(2) in name_remap else m.group(0),
            s,
        )

    changed = False
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if "{{" in v:
                    nv = _sub(v)
                    if nv != v:
                        obj[k] = nv
                        changed = True
            elif _repoint_bindings(v, name_remap):
                changed = True
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                if "{{" in v:
                    nv = _sub(v)
                    if nv != v:
                        obj[i] = nv
                        changed = True
            elif _repoint_bindings(v, name_remap):
                changed = True
    return changed


class RegistryIndex:
    """Reality, indexed for resolution — entities, their slugs/fields, relations."""

    def __init__(self, output_dir: str):
        reg = _load_registry(output_dir)
        self.entities: dict = reg.get("entities") or {}
        self.relations: list = reg.get("relations") or []
        self._by_key = {_ent_key(n): n for n in self.entities}

    def resolve_entity(self, name) -> tuple[str | None, str]:
        if not name:
            return None, "none"
        k = _ent_key(name)
        if k in self._by_key:
            canon = self._by_key[k]
            return canon, ("exact" if canon == name else "derived")
        # Substring bridge: a short guess ("plan") deterministically resolves to a
        # longer real entity ("MembershipPlan") — fuzzy/Levenshtein can't span that.
        subs = [self._by_key[ek] for ek in self._by_key if k and (k in ek or ek in k)]
        if len(subs) == 1:
            return subs[0], "derived"
        cands = subs or list(self.entities.keys())
        fm = fuzzy_match(str(name), cands, threshold=0.5)
        if fm:
            return fm, "fuzzy"
        # A person-role entity name (Requester, Assignee, Recipient) that maps to no
        # real entity → the app's user/person entity, so its list dataSource points at
        # the real `/api/data/users` instead of a 404ing phantom slug.
        role = _role_fk_target(k, self.entities)
        if role:
            return role, "derived"
        return None, "unresolved"

    def slug(self, canon: str) -> str:
        return _plural(canon)

    def label_field(self, canon: str) -> str:
        return _label_field(canon, self.entities)

    def real_fields(self, canon: str) -> set[str]:
        f = (self.entities.get(canon) or {}).get("fields") or {}
        return {_norm(c) for c in f} if isinstance(f, dict) else set()


def resolve_schema_references(output_dir: str) -> dict:
    """Resolve all schema references against the extracted registry. Returns
    {resolved, derived, fuzzy, unresolved, files, report_path}."""
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"resolved": 0, "derived": 0, "fuzzy": 0, "unresolved": 0, "files": 0}
    idx = RegistryIndex(output_dir)
    if not idx.entities:
        return {"resolved": 0, "derived": 0, "fuzzy": 0, "unresolved": 0, "files": 0}

    # Workflow indexes — so every Button/Form workflow ref resolves to a real
    # workflow the /api/workflows/{name}/execute route can actually dispatch.
    try:
        from services.crud_actions import build_workflow_index
        from services.workflow_action_mapper import index_status_workflows
        wf_index = build_workflow_index(output_dir)
        status_index = index_status_workflows(output_dir)
    except Exception:
        wf_index, status_index = {}, {}

    counts = {"exact": 0, "derived": 0, "fuzzy": 0, "unresolved": 0}
    report: list[dict] = []
    touched = 0

    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        base = os.path.basename(fp)
        if base in ("nav-flow.json",):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        rel = os.path.relpath(fp, sdir)
        page_ent = _page_entity(fp, idx)
        changed = _resolve_one(schema, idx, page_ent, rel, counts, report)

        # Workflow refs → real workflows (canonicalize casing/drift, map status
        # actions, strip phantoms) so no button dispatches a dead workflow.
        if wf_index.get("exact") or wf_index.get("norm"):
            try:
                from services.schema_binding import canonicalize_and_guard_workflow_buttons
                schema, winfo = canonicalize_and_guard_workflow_buttons(
                    schema, wf_index, status_index=status_index, entity=page_ent)
                canon = winfo.get("workflows_canonicalized", 0) + winfo.get("workflows_mapped", 0)
                neut = winfo.get("workflows_neutralized", 0)
                if canon:
                    counts["derived"] += canon
                    report.append({"file": rel, "kind": "workflow", "ref": None,
                                   "resolved": "canonicalized", "method": "derived"})
                if neut:
                    counts["neutralized"] = counts.get("neutralized", 0) + neut
                    report.append({"file": rel, "kind": "workflow", "ref": None,
                                   "resolved": None, "method": "neutralized"})
                if canon or neut:
                    changed = True
            except Exception:
                pass

        if changed:
            touched += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)

    # Persist the report so unresolved references are visible, not silent.
    try:
        cdir = os.path.join(output_dir, "contracts")
        os.makedirs(cdir, exist_ok=True)
        report_path = os.path.join(cdir, "references-report.json")
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump({"summary": counts, "references": report}, fh, indent=2)
    except Exception:
        report_path = ""

    return {
        "resolved": counts["derived"] + counts["fuzzy"] + counts.get("neutralized", 0),
        "derived": counts["derived"],
        "fuzzy": counts["fuzzy"],
        "neutralized": counts.get("neutralized", 0),
        "unresolved": counts["unresolved"],
        "files": touched,
        "report_path": report_path,
    }


def _page_entity(fp: str, idx: RegistryIndex) -> str | None:
    import re
    stem = os.path.basename(fp)[:-5]
    stem = re.sub(r"[-_/](new|edit|create|detail|details|list|form|view|show)$", "", stem)
    k = _ent_key(stem.rsplit("-", 1)[0] if "-" in stem else stem)
    return idx._by_key.get(k) or idx._by_key.get(_ent_key(stem))


def _rec(report, counts, file, kind, ref, resolved, method):
    counts[method] = counts.get(method, 0) + 1
    report.append({"file": file, "kind": kind, "ref": ref, "resolved": resolved, "method": method})


def _resolve_one(schema: dict, idx: RegistryIndex, page_ent, rel, counts, report) -> bool:
    changed = False
    name_remap: dict[str, str] = {}     # old dataSource name → new (entity slug)
    ds_entity: dict[str, str] = {}      # dataSource name → canonical entity
    drop_ds: set[str] = set()           # dataSource names to prune (entity resolves nowhere)

    # (1) dataSource.entity → canonical; list/options name → the entity slug so
    #     /api/data/<name> resolves at runtime.
    list_renames: list[tuple[dict, str, str]] = []  # (ds, desired slug, canon entity)
    for d in (schema.get("dataSources") or []):
        if not isinstance(d, dict) or not d.get("entity"):
            continue
        canon, method = idx.resolve_entity(d["entity"])
        if canon and method in ("derived", "fuzzy") and canon != d["entity"]:
            _rec(report, counts, rel, "dataSource.entity", d["entity"], canon, method)
            d["entity"] = canon
            changed = True
        elif canon:
            counts["exact"] += 1
        else:
            _rec(report, counts, rel, "dataSource.entity", d["entity"], None, "unresolved")
            if d.get("name"):
                drop_ds.add(d["name"])
        if canon:
            ds_entity[d.get("name")] = canon
            if str(d.get("op")) in ("list", "options") and d.get("name"):
                list_renames.append((d, idx.slug(canon), canon))

    # Rename list/options sources to the entity slug. When several sources canonicalize
    # to the SAME slug (e.g. a "Recent" list `applicantsRecent` and a plain `applicants`
    # list both → `applicants`), keep ONE survivor and drop the duplicates — repointing
    # every dropped source's `{{binding}}` to the survivor so no Table/list rows dangle.
    # A source already named the slug is the natural survivor.
    by_slug: dict[str, list[tuple[dict, str]]] = {}
    for d, want, canon in list_renames:
        by_slug.setdefault(want, []).append((d, canon))
    for want, group in by_slug.items():
        survivor = next((d for d, _ in group if d.get("name") == want), group[0][0])
        ds_entity[want] = next((c for d, c in group if d is survivor), group[0][1])
        for d, _canon in group:
            old = d.get("name")
            if d is survivor:
                if old != want:
                    name_remap[old] = want
                    d["name"] = want
                    changed = True
            else:
                # duplicate slug → drop this source, repoint its bindings to the survivor
                name_remap[old] = want
                drop_ds.add(old)
                changed = True

    # A page-level list/options dataSource whose entity resolves to no real entity
    # would still be fetched by the renderer on load → GET /api/data/<phantom> 404.
    # Drop it (the FK dropdown consuming it, if any, is neutralized in step 2). A
    # source that 404s is strictly worse than one that is absent.
    if drop_ds:
        kept = [d for d in (schema.get("dataSources") or [])
                if not (isinstance(d, dict) and d.get("name") in drop_ds)]
        if len(kept) != len(schema.get("dataSources") or []):
            schema["dataSources"] = kept
            changed = True

    # (1b) Repoint every `{{oldName...}}` binding (Table rows/items, list data, ...)
    #      whose dataSource step (1) renamed or folded into a survivor. Without this the
    #      rows binding dangles against the freshly-canonicalized slug and the table
    #      renders EMPTY (the dashboard "Recent <Entity>" bug). optionsFrom.source is a
    #      bare string handled structurally in step (2), so this pass leaves it alone.
    if _repoint_bindings(schema.get("root"), name_remap):
        changed = True

    # (2) optionsFrom on FK dropdowns: fix source (remap), derive the target entity
    #     from the FK column when the current source is unknown, real label field.
    for node in _iter_nodes(schema):
        if node.get("type") not in _OPTION_NODES:
            continue
        p = node.get("props")
        of = p.get("optionsFrom") if isinstance(p, dict) else None
        if not (isinstance(of, dict)):
            continue
        # remap source if its dataSource was renamed
        if of.get("source") in name_remap:
            of["source"] = name_remap[of["source"]]
            changed = True
        target = ds_entity.get(of.get("source"))
        # derive from FK column when the source doesn't resolve to a real entity
        if not target and isinstance(p.get("name"), str) and _norm(p["name"]).endswith("id"):
            t = _fk_target(page_ent and _ent_key(page_ent) or "", _norm(p["name"]),
                           idx.relations, idx.entities)
            if t:
                slug = idx.slug(t)
                # ensure a dataSource exists for it
                dss = schema.setdefault("dataSources", [])
                if not any(isinstance(x, dict) and x.get("name") == slug for x in dss):
                    dss.append({"name": slug, "entity": t, "op": "list"})
                _rec(report, counts, rel, "optionsFrom.source", of.get("source"), slug, "derived")
                of["source"] = slug
                target = t
                changed = True
        if target:
            real = idx.label_field(target)
            if of.get("label") and _norm(of["label"]) not in idx.real_fields(target):
                _rec(report, counts, rel, "optionsFrom.label", of.get("label"), real, "derived")
                of["label"] = real
                changed = True
            of.setdefault("value", "id")
        else:
            # Truly unresolvable — the referenced entity exists nowhere and the FK
            # column resolves to nothing. Don't ship a dead empty dropdown: strip
            # the dynamic source, and degrade to a plain Input when there are no
            # real static options to fall back on. Flagged as neutralized.
            p.pop("optionsFrom", None)
            opts = p.get("options")
            has_static = isinstance(opts, list) and any(
                isinstance(o, dict) and o.get("value") not in (None, "", "__none") for o in opts)
            if not has_static:
                node["type"] = "Input"
            _rec(report, counts, rel, "optionsFrom", of.get("source"), None, "neutralized")
            changed = True

    return changed

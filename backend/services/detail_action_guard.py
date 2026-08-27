"""Wire Edit / Delete buttons on a record page to the RIGHT entity and id.

The list-page guards (button_audit, create/edit-route guarantee) handle New→/new
and row actions, but a *record detail* page's page-level actions are routinely
left broken:

  - Edit points at ANOTHER entity's edit route with `{{item.id}}`
    (e.g. a Member detail page whose Edit navigates to `/bookings/{{item.id}}/edit`),
  - Delete has NO action at all — even though `Delete<Entity>` exists.

This deterministic pass resolves each detail page's OWN entity from its `get`
dataSource and wires, using that source's id (`{{member.id}}`, not `{{item.id}}`):

  - Edit   → navigate `/<entity>/{{<src>.id}}/edit`  (when that edit route exists)
  - Delete → workflow `Delete<Entity>`, args `{ id: "{{<src>.id}}" }` (when it exists)

Row-action Edit/Delete inside a list Repeat keep `{{item.id}}`. Idempotent — only
acts when the target (edit route / Delete workflow) actually exists, and never
touches a button that's already correctly wired.
"""
from __future__ import annotations

import glob

from services.artifact_authority import should_assert_only_any
import json
import os
import re

from services.form_scaffold import _ent_key, _iter_nodes, _load_registry

_EDIT_WORDS = {"edit", "update"}
_DELETE_WORDS = {"delete", "remove", "archive"}
_BTN_TYPES = ("Button", "IconButton", "NavLink")


def _words(label) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", str(label or "").lower()) if w}


def _delete_workflows(output_dir: str) -> dict[str, str]:
    """{entity_key -> 'Delete<Entity>'} for every Delete workflow on disk."""
    out: dict[str, str] = {}
    for d in (os.path.join(output_dir, "workflows"), os.path.join(output_dir, "src", "workflows")):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            m = re.match(r"^Delete([A-Z]\w+)\.json$", fn)
            if m:
                out[_ent_key(m.group(1))] = f"Delete{m.group(1)}"
    return out


def _edit_routes(sdir: str) -> dict[str, str]:
    """{entity_key -> '/<seg>/:id/edit'} from each edit schema's Update<Entity>."""
    out: dict[str, str] = {}
    for fp in glob.glob(os.path.join(sdir, "**", "[[]id[]]", "edit.json"), recursive=True):
        try:
            sc = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        ent = None
        for n in _iter_nodes(sc):
            if n.get("type") == "Form":
                m = re.match(r"^Update([A-Z]\w+)$", str((n.get("props") or {}).get("workflow") or ""))
                if m:
                    ent = m.group(1)
                    break
        route = str(sc.get("route") or "")
        if ent and route:
            out[_ent_key(ent)] = route
    return out


def _detail_context(schema: dict, stem: str, entities: dict):
    """(entity_name, source_name) for a record page — the `get` dataSource whose
    entity best matches the route segment — or None if this isn't a detail page."""
    gets = [d for d in (schema.get("dataSources") or [])
            if isinstance(d, dict) and d.get("op") == "get" and d.get("entity") and d.get("name")]
    if not gets:
        return None
    seg_key = _ent_key(re.sub(r"s$", "", stem))
    # Prefer the get source whose entity matches the route segment; else the first.
    primary = next((d for d in gets if _ent_key(d["entity"]) in (seg_key, _ent_key(stem))), gets[0])
    ent = next((n for n in entities if _ent_key(n) == _ent_key(primary["entity"])), primary["entity"])
    return ent, primary["name"]


def wire_detail_actions(output_dir: str) -> dict:
    """Wire Edit/Delete on record pages to the page's own entity + id. Returns
    {edits, deletes, files}."""
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"edits": 0, "deletes": 0, "files": 0, "asserts_logged": 0}
    entities = (_load_registry(output_dir).get("entities")) or {}
    if not entities:
        return {"edits": 0, "deletes": 0, "files": 0, "asserts_logged": 0}

    del_wf = _delete_workflows(output_dir)
    edit_routes = _edit_routes(sdir)
    # Slice-3 ledger contract: append-only entities are immutable. Detail
    # pages for them must NOT get an Edit or Delete button wired — even if
    # the LLM authored one and even if a Delete workflow was somehow
    # emitted, the Data Engine catch-all rejects PUT/DELETE with 405. A
    # future planner-authored Reversal action lives on the record page as
    # its own button (kind:"workflow" naming a Reversal workflow); this
    # guard just refuses to wire the standard Edit/Delete verbs.
    from services.ensure_edit_routes import _append_only_names
    append_only = _append_only_names(output_dir)

    edits = deletes = touched = asserts_logged = 0
    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        base = os.path.basename(fp)
        if base in ("shell.json", "nav-flow.json") or base.startswith(("login", "signup", "register")):
            continue
        try:
            schema = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue

        # Composer-authored pages are ASSERT-only: the composer's decision is the
        # authority, so log drift instead of rewriting it.
        if isinstance(schema, dict) and should_assert_only_any(schema):
            asserts_logged += 1
            continue

        # The route segment this page belongs to: for foo/[id].json the parent 'foo';
        # for foo.json it's 'foo'. Dropping the [id] segment leaves it as the last part.
        rel = os.path.relpath(fp, sdir).replace(os.sep, "/")
        parts = [p for p in rel[:-5].split("/") if p and p != "[id]"]
        if not parts:
            continue
        stem = parts[-1]
        # A detail page has a `get` source; resolve its own entity + record id ref.
        ctx = _detail_context(schema, stem, entities)
        if not ctx:
            continue
        entity, src = ctx
        ekey = _ent_key(entity)
        id_ref = f"{{{{{src}.id}}}}"
        # Ledger detail pages: skip Edit/Delete wiring entirely.
        if append_only and (entity in append_only or entity.lower() in append_only):
            continue

        changed = False
        for node in _iter_nodes(schema):
            if node.get("type") not in _BTN_TYPES:
                continue
            p = node.get("props")
            if not isinstance(p, dict):
                continue
            w = _words(p.get("label") or p.get("text") or p.get("aria-label"))

            if w & _EDIT_WORDS and ekey in edit_routes:
                want = edit_routes[ekey].replace(":id", id_ref)
                if p.get("navigate") != want or p.get("workflow"):
                    p["navigate"] = want
                    p.pop("workflow", None)
                    p.pop("args", None)
                    p.pop("action", None)
                    edits += 1
                    changed = True
            elif w & _DELETE_WORDS and ekey in del_wf:
                want_wf = del_wf[ekey]
                if p.get("workflow") != want_wf or p.get("args", {}).get("id") != id_ref:
                    p["workflow"] = want_wf
                    p["args"] = {"id": id_ref}
                    p.pop("navigate", None)
                    p.pop("action", None)
                    deletes += 1
                    changed = True

        if changed:
            touched += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)

    return {"edits": edits, "deletes": deletes, "files": touched,
            "asserts_logged": asserts_logged}

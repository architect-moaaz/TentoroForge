"""Synthesize the missing `/[entity]/[id]/edit` route so the Edit button works.

The pipeline reliably emits `/[entity]/new` (create) and `/[entity]/[id]` (detail)
schemas, but never `/[entity]/[id]/edit` — so an Edit button navigates to a route
that doesn't exist, `AppNavigator.overlayFor` can't find it, and nothing opens.

For every entity that has a `new` form, this pass writes an edit form by cloning
`new.json`, adding a `get` dataSource for the record, prefilling each field from it
(`defaultValue: {{record.field}}`), and pointing the Form's submit at
`Update<Entity>`. It then re-registers the route registry (so the new schema is
importable) and rewrites Edit buttons/actions to navigate to the edit route.
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re


def _append_only_names(output_dir: str) -> set[str]:
    """Slice-3 ledger contract: entity name-set that must NOT get an edit
    form. Sources, in order:
      1. ``src/contracts/registry.json`` — every entity carrying
         ``lifecycle: "append_only"``. This is the canonical source since
         resource_registry propagates the plan flag.
      2. ``src/lib/append-only-entities.ts`` — the runtime manifest
         schema_builder writes. Used as a backstop when the registry is
         missing (e.g. registry rebuilt after schema).
    Returns a normalised set (both cased and lowercase entity/table forms).
    Empty set = no append-only entities OR neither source found. Never
    raises — a bad file just returns whatever the other source gave."""
    out: set[str] = set()
    reg_path = os.path.join(output_dir, "src", "contracts", "registry.json")
    if os.path.isfile(reg_path):
        try:
            with open(reg_path, encoding="utf-8") as fh:
                reg = json.load(fh)
            for nm, rec in ((reg.get("entities") or {}) if isinstance(reg, dict) else {}).items():
                if isinstance(rec, dict) and str(rec.get("lifecycle") or "").strip() == "append_only":
                    out.add(str(nm))
                    out.add(str(nm).lower())
                    for k in ("table", "slug", "id"):
                        v = rec.get(k)
                        if isinstance(v, str) and v:
                            out.add(v)
                            out.add(v.lower())
        except Exception:  # noqa: BLE001
            pass
    manifest_path = os.path.join(output_dir, "src", "lib", "append-only-entities.ts")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                text = fh.read()
            # The manifest lists names as `  "value",`. Extract them all.
            for m in re.finditer(r'"([^"]+)"', text):
                v = m.group(1)
                if v and v not in ("APPEND_ONLY_ENTITIES", "string"):
                    out.add(v)
                    out.add(v.lower())
        except Exception:  # noqa: BLE001
            pass
    return out

_FIELD_TYPES = {"Input", "Textarea", "Select", "NumberInput", "DatePicker",
                "Switch", "Combobox", "MultiSelect", "RadioGroup", "MaskedInput", "KeyValueInput"}


def _camel(entity: str) -> str:
    e = str(entity or "")
    return e[:1].lower() + e[1:]


_NEW_LABEL = re.compile(r"^\s*(new|add|create|book)\b", re.I)


def _list_page_entity(schema: dict, stem: str, entities: dict) -> str | None:
    """Resolve which entity a list page is for — from its list dataSource, its
    `entity`, else a name match on the route segment."""
    from services.form_scaffold import _ent_key
    for d in (schema.get("dataSources") or []):
        if isinstance(d, dict) and d.get("op") in ("list", None) and d.get("entity"):
            k = _ent_key(d["entity"])
            for n in entities:
                if _ent_key(n) == k:
                    return n
    for cand in (schema.get("entity"), stem):
        if not cand:
            continue
        ck = _ent_key(cand)
        for n in entities:
            nk = _ent_key(n)
            if nk == ck or (ck and (ck in nk or nk in ck)):
                return n
    return None


def _existing_create_routes(sdir: str) -> set[str]:
    from services.route_slug import route_from_slug
    out: set[str] = set()
    for fp in glob.glob(os.path.join(sdir, "**", "new.json"), recursive=True):
        rel = os.path.relpath(fp, sdir)[:-5].replace(os.sep, "/")
        out.add(route_from_slug(rel))
    return out


def _repoint_new_buttons(output_dir: str, sdir: str, create_routes: set[str]) -> int:
    """A New/Add button that navigates to a LIST route (/plans) when the create
    route (/plans/new) exists is pointing at the wrong page — repoint it. Leaves
    already-correct `/x/new` navigations alone."""
    fixed = 0
    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        changed = False
        for node in _iter_nodes(schema):
            if node.get("type") != "Button":
                continue
            p = node.get("props") if isinstance(node.get("props"), dict) else None
            if not p or not _NEW_LABEL.match(str(p.get("label") or "")):
                continue
            nav = p.get("navigate")
            if not isinstance(nav, str) or nav.endswith("/new"):
                continue
            candidate = nav.rstrip("/") + "/new"
            if candidate in create_routes:
                p["navigate"] = candidate
                p.pop("workflow", None)
                p.pop("args", None)
                fixed += 1
                changed = True
        if changed:
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
    return fixed


# Route stems that are pages ABOUT the app, not collections of an entity —
# they never get a create form no matter what their content binds to.
_NON_ENTITY_STEMS = frozenset({
    "home", "index", "dashboard", "overview", "reports", "report",
    "analytics", "settings", "profile", "search", "tasks", "inbox",
    "activity", "notifications", "help", "calendar", "schedule",
})


def remove_junk_create_pages(output_dir: str) -> dict:
    """Delete create pages that never should have existed: ``<stem>/new.json``
    where the stem is a non-entity page (``/home/new`` — a create form for
    the dashboard). Cleans the schema file, the nav-flow entry, and regenerates
    the route registry. Idempotent; returns ``{removed: [routes]}``.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    removed: list[str] = []
    for fp in glob.glob(os.path.join(sdir, "*", "new.json")):
        stem = os.path.basename(os.path.dirname(fp))
        if stem.lower() not in _NON_ENTITY_STEMS:
            continue
        try:
            os.remove(fp)
            removed.append(f"/{stem}/new")
        except OSError:
            continue
        try:  # drop the now-empty dir so it doesn't read as a route group
            os.rmdir(os.path.dirname(fp))
        except OSError:
            pass

    if removed:
        nf_path = os.path.join(output_dir, "src", "contracts", "nav-flow.json")
        try:
            with open(nf_path, encoding="utf-8") as fh:
                nav = json.load(fh)
            pages = nav.get("pages")
            if isinstance(pages, list):
                nav["pages"] = [
                    p for p in pages
                    if not (isinstance(p, dict) and p.get("route") in removed)
                ]
                with open(nf_path, "w", encoding="utf-8") as fh:
                    json.dump(nav, fh, indent=2)
        except Exception:  # noqa: BLE001 — nav-flow cleanup is best-effort
            pass
        try:
            from services.schema_pipeline import _regenerate_route_registry
            _regenerate_route_registry(output_dir)
        except Exception:  # noqa: BLE001
            pass
    return {"removed": removed}


def ensure_create_routes(output_dir: str) -> dict:
    """Guarantee every entity list page has a `/[segment]/new` create form, and
    repoint New buttons that point at the list route. Returns {created, buttons}."""
    from services.form_scaffold import _load_registry, _ent_key
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"created": 0, "buttons": 0}
    entities = (_load_registry(output_dir).get("entities")) or {}
    if not entities:
        return {"created": 0, "buttons": 0}

    created = 0
    for fp in glob.glob(os.path.join(sdir, "*.json")):     # list pages are top-level
        base = os.path.basename(fp)
        if base in ("shell.json", "nav-flow.json", "registry.ts") or \
                base.startswith(("login", "signup", "register")):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        route = str(schema.get("route") or "")
        if not route or re.search(r"/(new|edit)$|/:?\[?id", route):
            continue
        stem = base[:-5]
        if stem.lower() in _NON_ENTITY_STEMS:
            continue
        ent = _list_page_entity(schema, stem, entities)
        if not ent:
            continue
        # Only real registered entities get a create form — never a dashboard/report
        # route (home/analytics/overdue/schedule) that resolved by loose matching.
        if _ent_key(ent) not in {_ent_key(n) for n in entities}:
            continue
        # The STEM itself must name the entity. A dashboard whose Table binds
        # to an entity's dataSource resolves via _list_page_entity, but its
        # route slug doesn't match — that produced /home/new ("create form
        # for the dashboard", workflow CreateEvent) on qeqorfii. Content
        # binding says what the page SHOWS; the slug says what it IS.
        sk, ek = _ent_key(stem), _ent_key(ent)
        if not (sk and ek and (sk == ek or sk in ek or ek in sk)):
            continue
        create_fp = os.path.join(sdir, stem, "new.json")
        if os.path.exists(create_fp):
            continue
        # Minimal create form; form_scaffold + semantic_field_types (which run
        # after) populate the fields from the entity, resolver fixes references.
        create_schema = {
            "route": f"/{stem}/new",
            "root": {"type": "Form", "props": {
                "workflow": f"Create{ent}", "submitLabel": f"Create {ent}"}, "children": [
                {"type": "Heading", "props": {"content": f"New {ent}", "level": 1}},
                {"type": "Stack", "props": {"direction": "vertical"}, "children": []},
            ]},
        }
        os.makedirs(os.path.join(sdir, stem), exist_ok=True)
        with open(create_fp, "w", encoding="utf-8") as fh:
            json.dump(create_schema, fh, indent=2)
        created += 1

    if created:
        try:
            from services.schema_pipeline import _regenerate_route_registry
            _regenerate_route_registry(output_dir)
        except Exception:
            pass

    buttons = _repoint_new_buttons(output_dir, sdir, _existing_create_routes(sdir))
    return {"created": created, "buttons": buttons}


def _iter_nodes(schema: dict):
    stack = [schema.get("root") or schema]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)


def _list_route(route: str) -> str:
    """The entity list route for an edit/new route — its first path segment."""
    seg = str(route or "").strip("/").split("/")[0]
    return f"/{seg}" if seg else "/"


def _save_cancel_row(list_route: str) -> dict:
    """A Save/Cancel button Row, mirroring the exact node shape create pages use
    (deterministic_pages): a ghost Cancel that navigates back to the list + a
    primary submit Button. Kept in sync by replication (not import) so this pass
    stays independent of deterministic_pages."""
    return {"type": "Row", "props": {"gap": "tokens.spacing.2", "justify": "end"}, "children": [
        {"type": "Button", "props": {"label": "Cancel", "variant": "ghost", "navigate": list_route}},
        {"type": "Button", "props": {"label": "Save changes", "variant": "primary", "submit": True}},
    ]}


def _submit_button(schema: dict) -> dict | None:
    for n in _iter_nodes(schema):
        if n.get("type") == "Button" and isinstance(n.get("props"), dict) and n["props"].get("submit"):
            return n
    return None


def _guarantee_save_cancel(schema: dict, *, relabel: bool) -> bool:
    """Guarantee the edit form can be saved. If a submit Button exists and
    ``relabel`` is set, rename it (and any ``text``) to "Save changes" — the
    cloned create submit is still labeled "Create <Entity>". If NO submit Button
    exists, synthesize a Cancel+Save Row into the Form. Returns True if changed."""
    btn = _submit_button(schema)
    if btn is not None:
        if not relabel:
            return False
        p = btn["props"]
        changed = p.get("label") != "Save changes" or ("text" in p and p.get("text") != "Save changes")
        p["label"] = "Save changes"
        if "text" in p:
            p["text"] = "Save changes"
        return changed
    form = next((n for n in _iter_nodes(schema) if n.get("type") == "Form"), None)
    if form is None:
        return False
    children = form.get("children")
    if not isinstance(children, list):
        form["children"] = children = []
    children.append(_save_cancel_row(_list_route(schema.get("route"))))
    return True


def _real_entity_keys(output_dir: str) -> set[str] | None:
    """The set of registered-entity comparison keys (``_ent_key``). Returns None
    when the registry is missing/empty so callers don't prune blindly."""
    from services.form_scaffold import _load_registry
    from services.workflow_action_mapper import _ent_key
    ents = (_load_registry(output_dir).get("entities")) or {}
    if not ents:
        return None
    return {_ent_key(n) for n in ents}


def _entity_of_new(new_schema: dict) -> str | None:
    """The entity a create form creates — from its Form workflow (CreateFoo) or a
    get/list dataSource."""
    for n in _iter_nodes(new_schema):
        if n.get("type") == "Form":
            wf = (n.get("props") or {}).get("workflow")
            m = re.match(r"^Create([A-Z]\w+)$", str(wf or ""))
            if m:
                return m.group(1)
    return None


def build_edit_schema(new_schema: dict, entity: str) -> dict:
    """Return an edit-form schema derived from a create-form schema."""
    schema = copy.deepcopy(new_schema)
    record = _camel(entity)

    # Route: /foo/new → /foo/:id/edit
    route = str(schema.get("route") or "")
    schema["route"] = re.sub(r"/new$", "/:id/edit", route) or f"/{record}/:id/edit"

    # Add the record's get dataSource (mirrors the detail page) if absent.
    ds = schema.get("dataSources")
    if not isinstance(ds, list):
        ds = []
    if not any(isinstance(d, dict) and d.get("name") == record for d in ds):
        ds.append({"name": record, "entity": entity, "op": "get"})
    schema["dataSources"] = ds

    has_id_field = False
    for node in _iter_nodes(schema):
        if node.get("type") == "Form":
            props = node.setdefault("props", {})
            props["workflow"] = f"Update{entity}"
            props["submitLabel"] = "Save changes"
            # DV-BIND-3: bind the RHF form's defaultValues to the whole
            # fetched record so controlled inputs prefill on mount.
            if "defaultValues" not in props:
                props["defaultValues"] = f"{{{{{record}}}}}"
        if node.get("type") in _FIELD_TYPES:
            p = node.get("props")
            if isinstance(p, dict) and p.get("name"):
                # Prefill from the fetched record.
                p.setdefault("defaultValue", f"{{{{{record}.{p['name']}}}}}")
                if p["name"] == "id":
                    has_id_field = True

    # Ensure the record id is submitted (Update<Entity> needs it). Add a hidden field.
    if not has_id_field:
        container = _form_container(schema)
        if container is not None:
            container.insert(0, {"type": "Input", "props": {
                "name": "id", "label": "id", "type": "hidden",
                "defaultValue": f"{{{{{record}.id}}}}",
            }})

    # Guarantee a Save/Cancel Row: relabel the cloned "Create <Entity>" submit to
    # "Save changes", or synthesize a Row when the create form had no buttons.
    _guarantee_save_cancel(schema, relabel=True)
    return schema


def backfill_edit_defaults(edit_schema: dict, entity: str, cols=None) -> dict:
    """Additively wire record-prefill into an EXISTING edit schema, in place.

    For an edit form that shipped without prefill bindings (e.g. LLM-authored),
    ensure a `get`/record dataSource exists and set
    ``defaultValue: {{<record>.<field>}}`` on every editable field that lacks
    one — using the SAME binding root ``build_edit_schema`` emits (the camelCase
    entity name, e.g. ``application``), and the SAME dataSource shape
    ``{name, entity, op:"get"}``.

    Never changes a field's control/type and never adds or removes fields.
    Skips hidden/system fields (the id already binds). Idempotent. ``cols`` is
    accepted for signature symmetry with the deterministic builders but the pass
    is node-driven — it prefills whatever editable fields the form carries.
    """
    record = _camel(entity)

    # Ensure the record's get dataSource (same name/shape as build_edit_schema).
    ds = edit_schema.get("dataSources")
    if not isinstance(ds, list):
        ds = []
    if not any(isinstance(d, dict) and d.get("name") == record for d in ds):
        ds.append({"name": record, "entity": entity, "op": "get"})
    edit_schema["dataSources"] = ds

    # DV-BIND-3: Bind the Form's whole ``defaultValues`` prop to the fetched
    # record. React Hook Form's ``useForm({defaultValues})`` reads THIS prop —
    # not individual Input ``defaultValue`` attrs, which get ignored on
    # RHF-controlled inputs. Without this the edit form ships with the correct
    # per-field bindings but nothing prefills because RHF's controller wins.
    for node in _iter_nodes(edit_schema):
        if node.get("type") == "Form":
            props = node.setdefault("props", {})
            if "defaultValues" not in props:
                props["defaultValues"] = f"{{{{{record}}}}}"
            break

    for node in _iter_nodes(edit_schema):
        if node.get("type") not in _FIELD_TYPES:
            continue
        p = node.get("props")
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not name:
            continue
        # Hidden/system fields already bind id — leave them untouched.
        if p.get("type") == "hidden" or name == "id":
            continue
        if "defaultValue" in p:
            continue
        p["defaultValue"] = f"{{{{{record}.{name}}}}}"
    return edit_schema


def _form_container(schema: dict) -> list | None:
    form = next((n for n in _iter_nodes(schema) if n.get("type") == "Form"), None)
    if not isinstance(form, dict):
        return None
    children = form.get("children")
    if not isinstance(children, list):
        form["children"] = children = []
    for c in children:
        if isinstance(c, dict) and c.get("type") in ("Stack", "Grid") and isinstance(c.get("children"), list):
            return c["children"]
    return children


def _detail_dataSource_name(schema: dict) -> str | None:
    """Return the name of the first single-record dataSource on ``schema``,
    or None when the page's dataSources are all lists.

    A ``op: "get"`` / ``"detail"`` / ``"find"`` / ``"one"`` source names a
    single record which the Engine binds as ``{{<name>.field}}``. Buttons
    on a detail page must use that name (not ``{{item.id}}``) because
    ``item`` is only defined inside a Table/List row iterator."""
    sources = schema.get("dataSources") if isinstance(schema, dict) else None
    if not isinstance(sources, list):
        return None
    for s in sources:
        if not isinstance(s, dict):
            continue
        op = s.get("op")
        name = s.get("name")
        if isinstance(name, str) and op in ("get", "detail", "find", "one"):
            return name
    return None


def _rewrite_edit_buttons(output_dir: str, entity_routes: dict[str, str]) -> int:
    """Point Edit buttons/row-actions at the edit route instead of a phantom
    workflow or a dead navigate. entity_routes: {entity_key -> "/foo/:id/edit"}."""
    fixed = 0
    for fp in glob.glob(os.path.join(output_dir, "src", "schemas", "**", "*.json"), recursive=True):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        changed = False
        for node in _iter_nodes(schema):
            label = (node.get("props") or {}).get("label") or ""
            if node.get("type") != "Button" or str(label).strip().lower() != "edit":
                continue
            p = node["props"]
            # Prefer the route matching this file's entity. Try, in order:
            #  1. The BASENAME of the file (`foo.json` → "foo") — the list page case.
            #  2. The immediate PARENT DIRECTORY of the file — the detail page case
            #     where basename is "[id]" (`drives/[id].json` → dir "drives").
            # Only fall back to the first-available edit route as a last resort so
            # a detail page in "drives" never gets an Edit button pointing at
            # "interviewers" just because interviewers came first in dict order.
            #
            # DV-BIND-4: added the parent-dir fallback. Without it a detail
            # schema's Edit button always hit the interviewers route (first
            # entry in dict iteration order) — the bug that landed on
            # /interviewers/edit when clicking Edit inside a Recruitment Drive.
            base = os.path.basename(fp)[:-5]
            candidates: list[str] = [re.sub(r"[^a-z0-9]", "", base.lower())]
            parent_dir = os.path.basename(os.path.dirname(fp))
            if parent_dir and parent_dir != "schemas":
                candidates.append(re.sub(r"[^a-z0-9]", "", parent_dir.lower()))
            route = next(
                (entity_routes[c] for c in candidates if c and c in entity_routes),
                None,
            )
            if route is None:
                # Only fall back when we can't match the file's own entity.
                route = next(iter(entity_routes.values()), None)
            if not route:
                continue
            # DV-BIND-4: id-binding token depends on context. When the schema
            # has a single detail dataSource (op=get on the focal entity),
            # the record binds as ``{{<dsName>.id}}`` — ``{{item.id}}`` won't
            # resolve because ``item`` is only defined inside a Table/List's
            # row iterator. For pages WITHOUT a detail dataSource, ``item``
            # is still the right choice (row action inside a list).
            detail_ds_name = _detail_dataSource_name(schema)
            id_token = (
                f"{{{{{detail_ds_name}.id}}}}" if detail_ds_name else "{{item.id}}"
            )
            target = route.replace(":id", id_token)
            if p.get("navigate") == target and not p.get("workflow"):
                continue
            p.pop("workflow", None)
            p.pop("args", None)
            p.pop("action", None)
            p["navigate"] = target
            changed = True
            fixed += 1
        if changed:
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
    return fixed


def ensure_edit_routes(output_dir: str) -> dict:
    """Create missing edit schemas + re-register + wire Edit buttons.
    Returns {created, buttons}."""
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"created": 0, "buttons": 0}

    from services.workflow_action_mapper import _ent_key
    real = _real_entity_keys(output_dir)
    # Slice-3 ledger contract: append-only entities MUST NOT get an edit
    # form or an Edit button. The set is loaded once per call — it names
    # both the entity Pascal name and its table/slug/lowercase forms so a
    # match never depends on which representation the caller happened to
    # use. Empty set (no ledgers in this app) = zero behavior change.
    append_only = _append_only_names(output_dir)

    created = 0
    backfilled = 0
    entity_routes: dict[str, str] = {}
    for new_fp in glob.glob(os.path.join(sdir, "**", "new.json"), recursive=True):
        try:
            with open(new_fp, encoding="utf-8") as fh:
                new_schema = json.load(fh)
        except Exception:
            continue
        entity = _entity_of_new(new_schema)
        if not entity:
            continue
        # Prune non-entity stubs (home/analytics/overdue/schedule): only synthesize
        # an edit route for a route whose entity is really registered.
        if real is not None and _ent_key(entity) not in real:
            continue
        # Slice-3: append-only entities never get an edit form. The Data
        # Engine rejects PUT at runtime; leaving an edit route around
        # would just produce a form that always 405s on save.
        if append_only and (entity in append_only or entity.lower() in append_only):
            continue
        entity_dir = os.path.dirname(new_fp)                 # .../schemas/appointments
        edit_dir = os.path.join(entity_dir, "[id]")
        edit_fp = os.path.join(edit_dir, "edit.json")
        route = f"/{os.path.relpath(entity_dir, sdir).replace(os.sep, '/')}/:id/edit"
        entity_routes[re.sub(r'[^a-z0-9]', '', os.path.basename(entity_dir).lower())] = route
        if os.path.exists(edit_fp):
            # An edit schema already shipped (LLM-authored). Don't clobber it —
            # additively backfill record-prefill bindings so edit prefills.
            try:
                with open(edit_fp, encoding="utf-8") as fh:
                    existing = json.load(fh)
            except Exception:
                continue
            before = json.dumps(existing, sort_keys=True)
            backfill_edit_defaults(existing, entity)
            # An LLM-authored edit page may ship without any submit control —
            # inject a Save/Cancel Row so it becomes savable (don't relabel an
            # existing submit the author may have deliberately named).
            _guarantee_save_cancel(existing, relabel=False)
            if json.dumps(existing, sort_keys=True) != before:
                with open(edit_fp, "w", encoding="utf-8") as fh:
                    json.dump(existing, fh, indent=2)
                backfilled += 1
            continue
        edit_schema = build_edit_schema(new_schema, entity)
        os.makedirs(edit_dir, exist_ok=True)
        with open(edit_fp, "w", encoding="utf-8") as fh:
            json.dump(edit_schema, fh, indent=2)
        created += 1

    buttons = _rewrite_edit_buttons(output_dir, entity_routes) if entity_routes else 0

    if created:
        try:
            from services.schema_pipeline import _regenerate_route_registry
            _regenerate_route_registry(output_dir)
        except Exception:
            pass

    return {"created": created, "buttons": buttons, "backfilled": backfilled}

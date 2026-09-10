"""Build-time binding validator (Slice 1 of the resource-binding contract).

Every generated app wires its UI to backend resources: a Form dispatches a
workflow, a Button dispatches a workflow, a list/Select loads options from a
data-engine entity slug, a Table binds its rows to a page dataSource. When the
LLM page agent authors any of those references from inference, it can name a
resource the backend doesn't have — a mis-cased slug, a phantom workflow, a
free-text Input feeding a uuid FK column. The repair guards
(`list_data_source_guard`, `workflow_table_guard`, `workflow_trigger_button_guard`,
`schema_references`) heal what they can; this validator runs AFTER them and
reports what is STILL broken, as a hard gate.

`validate_bindings(output_dir) -> {"ok": bool, "errors": [...], "warnings": [...]}`.

It reads the registries ONCE:
  * registered entity slugs = the `export const <NAME> = pgTable("<arg>", …)`
    const names across `src/db/schema/*.ts` (the `/api/data/<slug>` set — the
    data-engine registers `registerEntity(name, …, {slug:name})`, so the CONST
    name is authoritative, per `list_data_source_guard`).
  * per-entity columns + drizzle types (uuid/integer/varchar/boolean/…).
  * workflows = `workflows/*.json` → canonical id/name/stem, trigger type, and
    the set of columns each `db_insert`/`db_update` writes (its input columns)
    plus the table it writes to.

Then it walks every `src/schemas/**/*.json` and checks each binding:
  1. Button `workflow` ref must exist; an event-only workflow on a button with
     no record context is dead (should have been neutralized — flag if not).
  2. Form submit → workflow: the referenced workflow must exist.
  3. dataSource / optionsFrom `source`/`table`/`entity` must resolve (canonical,
     plural-tolerant) to a registered entity slug.
  4. A Table `rows` / list `items` `{{name}}` binding must match a dataSource
     `name` declared on that page.
  5. A form field that maps to a uuid/integer workflow-input column but is a
     plain free-text Input (no optionsFrom, not a Select/DatePicker/NumberInput)
     → type-incompatible (the `uuid:"M"` class).

Genuinely-static widgets (ActivityFeed/ApprovalStepper with literal data and no
binding) are WARNINGS, not errors. Best-effort — never raises; a validator bug
degrades to a warning, never a crash.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re

from services.entity_names import pluralize, singularize

logger = logging.getLogger(__name__)

# `export const recruitmentDrives = pgTable("recruitmentDrives", ...` — the const
# name is the data-engine registration slug (registerEntity(name, ..., {slug:name})).
_EXPORT_TABLE_RE = re.compile(
    r"export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*pgTable\(\s*[\"']([^\"']+)[\"']"
)
# A column declaration inside a pgTable block: `firstName: varchar("first_name",`.
_COLUMN_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*:\s*([A-Za-z_$][\w$]*)\s*\(")
# A pure single-token rows binding: "{{ candidates }}" -> "candidates".
_SINGLE_TOKEN_RE = re.compile(r"^\{\{\s*([A-Za-z_][\w]*)\s*\}\}$")
# A stat binding, possibly dotted, root identifier captured: "{{open.count}}" -> "open".
_ROOT_TOKEN_RE = re.compile(r"^\{\{\s*([A-Za-z_][\w]*)\s*(?:\.[\w.]+)?\s*\}\}$")

# Drizzle column-type families we reason about for the type-compatibility check.
_UUID_TYPES = {"uuid"}
_INT_TYPES = {"integer", "serial", "bigserial", "smallint", "bigint"}

# Node types that behave like a clickable control carrying a workflow dispatch.
_BUTTON_TYPES = {
    "button", "iconbutton", "actionbutton", "fab", "linkbutton", "menubutton",
    "splitbutton", "togglebutton", "menuitem", "dropdownitem",
}
# Containers whose child rows each supply their own record.
_ROW_CONTAINER_TYPES = {
    "table", "datatable", "datagrid", "repeat", "list", "datalist", "cardlist",
    "listview", "itemlist", "recordlist", "resourcetimeline",
}
# Object keys that hold per-row actions (a record context comes with each row).
_ROW_CTX_KEYS = {
    "rowactions", "rowaction", "itemactions", "cardactions", "rowtemplate",
    "itemtemplate", "columns", "cell", "cells",
}
# Free-text controls: cannot produce a uuid FK or (untyped) an integer value.
_TEXT_INPUT_TYPES = {
    "input", "textinput", "textfield", "textarea", "emailinput", "passwordinput",
}
# Props carrying a whole-string single-token collection binding ("{{name}}").
# rows/items (Table/List) plus Chart data, ResourceTimeline resources, Calendar
# events, Timeline entries — each must name a page dataSource.
_LIST_BINDING_KEYS = ("rows", "items", "data", "resources", "events", "entries")
# Stat-like nodes bind a scalar metric via a (possibly dotted) "{{name.metric}}";
# the ROOT identifier must name a page dataSource.
_STAT_NODE_TYPES = {
    "stat", "statcard", "metric", "metrictile", "metriccard", "kpi", "kpicard",
    "gauge", "progress", "counter", "scorecard",
}
_STAT_BINDING_KEYS = ("value", "current", "count", "score")
# The ROOT identifier of any `{{root}}` / `{{root.path}}` occurring anywhere in
# a prop value (including nested objects and arrays).
_ANY_ROOT_RE = re.compile(r"\{\{\s*([A-Za-z_][\w]*)")
# Binding roots the renderer supplies without a page fetch: the signed-in
# actor, the route, the form under edit, the current repeat item. These must
# never be reported as dangling — mirrors page_planner.SCOPE_ROOTS, which is
# the generation-time half of the same rule.
_SCOPE_ROOTS = frozenset({
    "user", "actor", "session", "route", "params", "param", "query",
    "search", "form", "state", "theme", "now", "today",
    "item", "row", "index", "i",
})
# Keys a Repeat names its per-row alias with.
_ALIAS_KEYS = ("as", "alias", "itemname", "var")
# Widgets that legitimately ship with literal, unbacked data.
_STATIC_WIDGET_TYPES = {"activityfeed", "approvalstepper"}
# ops we treat as a collection/options load (used for `entity` resolution).
_LIST_OPS = ("list", "table", "grid", "index", "options")


def _canon(s) -> str:
    """Case- and separator-insensitive key for matching slugs/names."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _singularish(c: str) -> str:
    """Fold an already-canonicalised name to singular so `candidate` ↔
    `candidates` match.

    Delegates to :func:`services.entity_names.singularize` — the single
    naming authority — which unwinds the same rules the generators use to
    pluralize. Dropping one trailing 's' broke every irregular:
    `categories` folded to `categorie` and never met `category`, so the
    binding silently failed to resolve. Same shape as register findings
    STATUS-3 / BA-5. Input is expected to be `_canon`-ed already."""
    return singularize(c)


# ── registry readers ────────────────────────────────────────────────────────

def _read_schema_tables(output_dir: str) -> list[dict]:
    """Every pgTable: {const, arg, columns:{field->drizzle_type}} across schema."""
    sdir = os.path.join(output_dir, "src", "db", "schema")
    tables: list[dict] = []
    if not os.path.isdir(sdir):
        return tables
    for fp in sorted(glob.glob(os.path.join(sdir, "*.ts"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in _EXPORT_TABLE_RE.finditer(text):
            const_name, arg = m.group(1), m.group(2)
            # Capture the { ... } block body of this pgTable via brace matching.
            body = _pgtable_body(text, m.end())
            columns: dict[str, str] = {}
            for cm in _COLUMN_RE.finditer(body):
                field, dtype = cm.group(1), cm.group(2).lower()
                # Skip drizzle helpers that aren't column-type constructors.
                if dtype in ("references", "default", "notnull", "primarykey"):
                    continue
                columns.setdefault(field, dtype)
            tables.append({"const": const_name, "arg": arg, "columns": columns})
    return tables


def _pgtable_body(text: str, start: int) -> str:
    """Return the `{ ... }` object body of a pgTable call starting at `start`."""
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth = 0
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1:i]
    return text[brace + 1:]


def _extract_trigger_type(wf: dict) -> str:
    """Pull the trigger type from a workflow doc, tolerating shape variants."""
    defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else wf
    trig = defn.get("trigger") if isinstance(defn.get("trigger"), dict) else None
    if isinstance(trig, dict) and trig.get("type"):
        return str(trig["type"]).strip().lower()
    for key in ("triggerType", "trigger_type"):
        if defn.get(key):
            return str(defn[key]).strip().lower()
        if wf.get(key):
            return str(wf[key]).strip().lower()
    if isinstance(trig, str):
        return trig.strip().lower()
    return ""


_EVENT_TRIGGERS = {
    "dbchange", "apievent", "schedule", "scheduled", "cron", "webhook", "event",
}
_MANUAL_TRIGGERS = {"manual", "button", "user", ""}


def _is_event_only(trigger_type: str) -> bool:
    t = _canon(trigger_type)
    if not t or t in _MANUAL_TRIGGERS:
        return False
    return t in _EVENT_TRIGGERS


def _collect_db_writes(wf: dict) -> tuple[set[str], str | None]:
    """Union of columns written by every db_insert/db_update + its table."""
    cols: set[str] = set()
    table: str | None = None

    def walk(obj):
        nonlocal table
        if isinstance(obj, dict):
            cfg = obj.get("config") if isinstance(obj.get("config"), dict) else obj
            atype = str(cfg.get("actionType", "")).strip().lower()
            if atype in ("db_insert", "db_update"):
                vals = cfg.get("values")
                if isinstance(vals, dict):
                    cols.update(str(k) for k in vals.keys())
                if isinstance(cfg.get("table"), str) and table is None:
                    table = cfg["table"]
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(wf)
    return cols, table


def _read_workflows(output_dir: str) -> dict[str, dict]:
    """canon(id|name|stem) -> {id, trigger, input_columns:set, table}."""
    wdir = os.path.join(output_dir, "workflows")
    idx: dict[str, dict] = {}
    if not os.path.isdir(wdir):
        return idx
    for fn in sorted(os.listdir(wdir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(wdir, fn), encoding="utf-8") as fh:
                wf = json.load(fh)
        except Exception:  # noqa: BLE001 — a bad file must not break the gate
            continue
        if not isinstance(wf, dict):
            continue
        cols, table = _collect_db_writes(wf)
        rec = {
            "id": wf.get("id") or wf.get("name") or fn[:-5],
            "trigger": _extract_trigger_type(wf),
            "input_columns": cols,
            "table": table,
        }
        for key in (wf.get("id"), wf.get("name"), fn[:-5]):
            if key and isinstance(key, str):
                idx.setdefault(_canon(key), rec)
    return idx


# ── resolution helpers ──────────────────────────────────────────────────────

class _SlugResolver:
    """Resolve a reference to a registered entity slug (plural-tolerant)."""

    def __init__(self, tables: list[dict]):
        self.slugs = [t["const"] for t in tables]
        # both const-name and pgTable-arg canon → const slug (the runtime slug)
        self._canon_to_slug: dict[str, str] = {}
        self._sing_to_slug: dict[str, str] = {}
        for t in tables:
            for token in (t["const"], t["arg"]):
                c = _canon(token)
                self._canon_to_slug.setdefault(c, t["const"])
                self._sing_to_slug.setdefault(_singularish(c), t["const"])
        # columns keyed by const slug
        self._cols: dict[str, dict] = {t["const"]: t["columns"] for t in tables}

    def resolve(self, ref) -> str | None:
        if not ref or not isinstance(ref, str):
            return None
        c = _canon(ref)
        if c in self._canon_to_slug:
            return self._canon_to_slug[c]
        s = _singularish(c)
        if s in self._sing_to_slug:
            return self._sing_to_slug[s]
        # Plural direction. Folding to singular alone cannot match an
        # acronym entity to its table: `SKU` canons to 'sku' with no
        # trailing 's' to strip, while the table `skus` folds to 'skus'
        # because '-us' reads as already-singular — which it must, so
        # that 'status' and 'bus' survive. The two never meet. Asking
        # instead "what would this entity's table be called?" does meet,
        # and only ever matches a table that actually exists.
        p = _canon(pluralize(c))
        if p in self._canon_to_slug:
            return self._canon_to_slug[p]
        return None

    def columns_for(self, ref) -> dict:
        slug = self.resolve(ref)
        return self._cols.get(slug, {}) if slug else {}


# ── node walking ────────────────────────────────────────────────────────────

def _node_type(node: dict) -> str:
    return _canon(node.get("type"))


def _node_workflow_ref(node: dict) -> str | None:
    """The workflow ref a Form/Button node dispatches, from any carrier."""
    v = node.get("workflow")
    if isinstance(v, str) and v.strip():
        return v.strip()
    for holder in ("props", "action", "onClick"):
        sub = node.get(holder)
        if isinstance(sub, dict) and isinstance(sub.get("workflow"), str) and sub["workflow"].strip():
            return sub["workflow"].strip()
    return None


def _props(node: dict) -> dict:
    p = node.get("props")
    return p if isinstance(p, dict) else {}


def _iter_nodes_ctx(node, record_ctx: bool):
    """Yield (dict-node, record_ctx) for every component node, threading whether
    the subtree already has a per-record context (detail route / row container).
    """
    if isinstance(node, dict):
        yield node, record_ctx
        node_is_container = _node_type(node) in _ROW_CONTAINER_TYPES
        for key, val in node.items():
            child_ctx = record_ctx or (_canon(key) in _ROW_CTX_KEYS)
            if isinstance(val, list):
                list_ctx = child_ctx or node_is_container
                for item in val:
                    yield from _iter_nodes_ctx(item, list_ctx)
            elif isinstance(val, dict):
                yield from _iter_nodes_ctx(val, child_ctx)


def _form_field_nodes(node):
    """Every descendant node carrying a props.name (a form field)."""
    for n, _ in _iter_nodes_ctx(node, False):
        if isinstance(_props(n).get("name"), str):
            yield n


# ── the checks ──────────────────────────────────────────────────────────────

def _check_page(rel: str, page: dict, resolver: _SlugResolver,
                workflows: dict, errors: list, warnings: list) -> None:
    data_sources = page.get("dataSources")
    data_sources = data_sources if isinstance(data_sources, list) else []
    ds_names = {
        ds["name"] for ds in data_sources
        if isinstance(ds, dict) and isinstance(ds.get("name"), str)
    }

    # (3) page-level dataSources resolve to a registered slug. A dataSource
    # routes via its explicit source/table/from/entity if present, else its name.
    for ds in data_sources:
        if not isinstance(ds, dict):
            continue
        ref = None
        for key in ("source", "table", "from", "entity", "name"):
            if isinstance(ds.get(key), str) and ds[key]:
                ref = ds[key]
                break
        if ref is None:
            continue
        if resolver.resolve(ref) is None:
            errors.append({
                "file": rel, "kind": "datasource_unresolved", "ref": ref,
                "detail": f"dataSource '{ds.get('name')}' references '{ref}', "
                          f"which resolves to no registered entity slug.",
            })

    record_ctx = "[" in rel
    for node, node_ctx in _iter_nodes_ctx(page.get("root") if isinstance(page.get("root"), dict) else page,
                                          record_ctx):
        ntype = _node_type(node)
        props = _props(node)

        # (3) optionsFrom.source on any node.
        of = props.get("optionsFrom")
        if isinstance(of, dict):
            src = of.get("source") or of.get("table") or of.get("entity")
            if isinstance(src, str) and src:
                if resolver.resolve(src) is None and src not in ds_names:
                    errors.append({
                        "file": rel, "kind": "options_source_unresolved", "ref": src,
                        "detail": f"{node.get('type')} optionsFrom.source '{src}' "
                                  f"resolves to no registered entity slug or page dataSource.",
                    })

        # (4) collection binding (rows/items/data/resources/events/entries) must
        # match a page dataSource name — a whole-string single-token "{{name}}".
        for key in _LIST_BINDING_KEYS:
            val = props.get(key)
            if isinstance(val, str):
                m = _SINGLE_TOKEN_RE.match(val)
                if m and m.group(1) not in ds_names:
                    errors.append({
                        "file": rel, "kind": "binding_unresolved", "ref": m.group(1),
                        "detail": f"{node.get('type')} {key} binds '{{{{{m.group(1)}}}}}' "
                                  f"but no dataSource named '{m.group(1)}' is declared on this page.",
                    })

        # (4b) Stat-like scalar binding: value/current/count/score, possibly
        # dotted ("{{name.metric}}"); the ROOT identifier must be a dataSource.
        if ntype in _STAT_NODE_TYPES:
            for key in _STAT_BINDING_KEYS:
                val = props.get(key)
                if isinstance(val, str):
                    m = _ROOT_TOKEN_RE.match(val)
                    if m and m.group(1) not in ds_names:
                        errors.append({
                            "file": rel, "kind": "binding_unresolved", "ref": m.group(1),
                            "detail": f"{node.get('type')} {key} binds '{val}' but no "
                                      f"dataSource named '{m.group(1)}' is declared on this page.",
                        })

        # Workflow refs (Form submit + Button dispatch).
        wf_ref = _node_workflow_ref(node)
        if wf_ref is not None:
            wf = workflows.get(_canon(wf_ref))
            is_button = ntype in _BUTTON_TYPES
            is_form = ntype == "form"
            if wf is None and (is_button or is_form):
                errors.append({
                    "file": rel, "kind": "workflow_ref", "ref": wf_ref,
                    "detail": f"{node.get('type')} references workflow '{wf_ref}', "
                              f"which does not exist.",
                })
            elif wf is not None and is_button and not node_ctx and _is_event_only(wf["trigger"]):
                # (1) an event-only workflow on a bare button — should have been
                # neutralized by workflow_trigger_button_guard; flag if it slipped.
                errors.append({
                    "file": rel, "kind": "event_only_button", "ref": wf_ref,
                    "detail": f"Button dispatches event-only workflow '{wf_ref}' "
                              f"(trigger '{wf['trigger']}') with no record context.",
                })

            # (5) workflow input ↔ column type, for a Form dispatching a workflow.
            if wf is not None and is_form:
                cols = resolver.columns_for(wf.get("table"))
                _check_form_field_types(rel, node, wf, cols, errors)

        # (6) Repeat must name its collection. Canonical is node-level `bind`
        # or props.source; the renderer also tolerates props.bind and
        # props.dataSource because producers emit them (55 and 18 nodes in the
        # corpus respectively). Tolerated is not the same as correct, so an
        # alias is reported as a WARNING — it renders, but it drifts.
        #
        # This rule used to read `bind` off the NODE only, then report
        # "declares no bind/source prop" for a node whose props DID set bind.
        # Its own synonym list omitted `bind`, so it offered no hint either:
        # the reader saw a bind prop and a message denying one existed. Every
        # message below names the prop actually found.
        if ntype == "repeat":
            def _named(v: object) -> str | None:
                return v.strip() if isinstance(v, str) and v.strip() else None

            canonical = _named(node.get("bind")) or _named(props.get("source"))
            alias_key = next(
                (k for k in ("bind", "dataSource")
                 if not canonical and _named(props.get(k))), None)
            src = canonical or (_named(props.get(alias_key)) if alias_key else None)

            if src is None:
                dead = [k for k in ("items", "data", "rows", "records",
                                    "list", "entries")
                        if _named(props.get(k))]
                hint = (f" It sets props.{dead[0]}, which no renderer reads — "
                        f"move the name to node-level `bind`." if dead else "")
                errors.append({
                    "file": rel, "kind": "repeat_missing_source",
                    "ref": dead[0] if dead else None,
                    "detail": "Repeat names no collection in `bind`, "
                              "props.source, props.bind or props.dataSource, "
                              "so the renderer iterates nothing." + hint,
                })
            else:
                if alias_key:
                    warnings.append({
                        "file": rel, "kind": "repeat_alias_source",
                        "ref": alias_key,
                        "detail": f"Repeat names its collection via "
                                  f"props.{alias_key}. The renderer accepts it, "
                                  f"but node-level `bind` is canonical.",
                    })
                # A mustache-wrapped name is resolved by the renderer's
                # interpolation pass; compare the bare name against the registry.
                bare = src.strip().strip("{}").strip()
                if bare not in ds_names and resolver.resolve(bare) is None:
                    errors.append({
                        "file": rel, "kind": "binding_unresolved", "ref": src,
                        "detail": f"Repeat source '{bare}' matches no page "
                                  f"dataSource or registered entity slug.",
                    })

        # Static-widget advisory.
        if ntype in _STATIC_WIDGET_TYPES:
            has_binding = _has_any_binding(props)
            if not has_binding:
                warnings.append({
                    "file": rel, "kind": "static_widget", "ref": node.get("type"),
                    "detail": f"{node.get('type')} renders literal data with no dataSource "
                              f"binding (static widget — advisory).",
                })

    # Any REMAINING binding, in any prop, whose root resolves to nothing. The
    # checks above only inspect the props they know the names of; this one is
    # the backstop, and reports each root once per page so a repeated binding
    # does not bury the rest of the gate's output.
    already = {e.get("ref") for e in errors
               if e.get("file") == rel and e.get("kind") == "binding_unresolved"}
    tail: list = []
    _check_dangling_roots(rel, page, ds_names, tail)
    errors.extend(e for e in tail if e.get("ref") not in already)


#: Props/keys a Repeat names its collection with (`bind` is canonical).
_REPEAT_SOURCE_KEYS = ("bind", "source", "datasource", "items", "data", "rows",
                       "records", "list", "entries")


def _repeat_aliases(page: dict) -> set[str]:
    """Canon per-row aliases every Repeat on the page introduces.

    Both the explicit alias (`as`/`alias`) and the IMPLICIT one: a Repeat over
    `orders` whose children bind `{{order.ref}}` has named nothing, but `order`
    is a row scope, not a missing dataSource. Reporting it would fail pages
    that render correctly, so the singular of each collection a Repeat names
    counts as a scope too.
    """
    out: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            if _node_type(node) == "repeat" or node.get("repeat"):
                for holder in (node, _props(node)):
                    for k, v in holder.items():
                        if not isinstance(v, str) or not v.strip():
                            continue
                        ck = _canon(k)
                        if ck in _ALIAS_KEYS:
                            out.add(_canon(v.lstrip("$")))
                        elif ck in _REPEAT_SOURCE_KEYS:
                            out.add(_singularish(_canon(v.strip("{} "))))
                if isinstance(node.get("repeat"), str):
                    out.add(_singularish(_canon(node["repeat"])))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(page.get("root") if isinstance(page.get("root"), dict) else page)
    return {a for a in out if a}


def _binding_roots(value) -> set[str]:
    """Root identifiers of every `{{…}}` inside a prop value, however nested."""
    out: set[str] = set()
    if isinstance(value, str):
        out.update(_ANY_ROOT_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            out |= _binding_roots(v)
    elif isinstance(value, list):
        for v in value:
            out |= _binding_roots(v)
    return out


def _check_dangling_roots(rel: str, page: dict, ds_names: set[str],
                          errors: list) -> None:
    """Report any binding whose ROOT names neither a dataSource nor a scope.

    The stat/list checks above only look at the props they know about, so a
    binding in any other prop went unexamined. `/items` shipped three Stat
    tiles bound to `{{metrics.list_total_inventory_value}}` on a page whose
    dataSources were named `items`, `totalInventoryValue` and `lowStockCount`:
    the root named nothing, the renderer (correctly) refuses to leak a raw
    template, and the tiles rendered BLANK in production. A binding that
    resolves to nothing is a build error, not a rendering detail.
    """
    scopes = _SCOPE_ROOTS | _repeat_aliases(page)
    declared = {_canon(n) for n in ds_names}
    seen: set[str] = set()
    root = page.get("root") if isinstance(page.get("root"), dict) else page
    for node, _ in _iter_nodes_ctx(root, False):
        props = _props(node)
        if not props:
            continue
        for key, value in props.items():
            for name in _binding_roots(value):
                c = _canon(name)
                if c in declared or c in scopes or name in seen:
                    continue
                seen.add(name)
                errors.append({
                    "file": rel, "kind": "binding_unresolved", "ref": name,
                    "detail": f"{node.get('type')} {key} binds "
                              f"'{{{{{name}…}}}}' but no dataSource named "
                              f"'{name}' is declared on this page and it is "
                              f"not a known scope — it resolves to nothing, "
                              f"so the widget renders blank.",
                })


def _has_any_binding(props: dict) -> bool:
    """True if any prop value contains a `{{...}}` binding expression."""
    def scan(v) -> bool:
        if isinstance(v, str):
            return "{{" in v
        if isinstance(v, dict):
            return any(scan(x) for x in v.values())
        if isinstance(v, list):
            return any(scan(x) for x in v)
        return False
    return scan(props)


def _check_form_field_types(rel: str, form_node: dict, wf: dict, cols: dict,
                            errors: list) -> None:
    """Flag a free-text Input mapped to a uuid/integer workflow-input column."""
    input_columns = wf.get("input_columns") or set()
    # canon map of column name -> drizzle type (for tolerant field matching)
    col_types = {_canon(name): dtype for name, dtype in cols.items()}
    for field in _form_field_nodes(form_node):
        fprops = _props(field)
        fname = fprops.get("name")
        if not isinstance(fname, str) or not fname:
            continue
        # Only fields that actually feed the workflow's input columns.
        if fname not in input_columns and _canon(fname) not in {_canon(c) for c in input_columns}:
            continue
        dtype = col_types.get(_canon(fname))
        if dtype not in _UUID_TYPES and dtype not in _INT_TYPES:
            continue
        # A hidden field is machine-filled — the record key carried down from
        # the route, typically `{{entity.id}}`. There is no way to type into
        # it, so it is not the free-text hazard this rule exists to catch.
        # Reading the NODE type alone (Input) flagged 8 correct edit forms
        # across the six-app corpus; in a blocking gate that fails builds on
        # apps that are right.
        if str(fprops.get("type", "")).strip().lower() == "hidden":
            continue
        ftype = _node_type(field)
        has_options = isinstance(fprops.get("optionsFrom"), dict)
        if has_options or ftype not in _TEXT_INPUT_TYPES:
            continue  # Select/DatePicker/NumberInput or an optionsFrom control — OK
        # A plain text Input. For integer, a numeric-typed input is acceptable.
        if dtype in _INT_TYPES and str(fprops.get("type", "")).lower() == "number":
            continue
        errors.append({
            "file": rel, "kind": "type_incompatible", "ref": fname,
            "detail": f"Form field '{fname}' is a free-text {field.get('type')} but "
                      f"feeds workflow '{wf.get('id')}' {dtype} column "
                      f"'{fname}' (uuid/int column fed by free-text input).",
        })


# ── entry point ─────────────────────────────────────────────────────────────

def validate_bindings(output_dir: str) -> dict:
    """Validate every UI binding in the generated app against the registries.

    Returns {"ok": bool, "errors": [ {file, kind, ref, detail} ], "warnings": [...]}.
    Runs AFTER the repair guards, so its errors are what is STILL broken. Never
    raises — a validator failure degrades to a single warning.
    """
    errors: list = []
    warnings: list = []
    try:
        tables = _read_schema_tables(output_dir)
        resolver = _SlugResolver(tables)
        workflows = _read_workflows(output_dir)

        sdir = os.path.join(output_dir, "src", "schemas")
        if os.path.isdir(sdir):
            for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
                rel = os.path.relpath(fp, sdir)
                if os.path.basename(fp) in ("nav-flow.json",):
                    continue
                try:
                    with open(fp, encoding="utf-8") as fh:
                        page = json.load(fh)
                except (OSError, ValueError) as e:
                    warnings.append({"file": rel, "kind": "parse_error", "ref": None,
                                     "detail": f"could not parse: {e}"})
                    continue
                if not isinstance(page, dict):
                    continue
                _check_page(rel, page, resolver, workflows, errors, warnings)
    except Exception as e:  # noqa: BLE001 — the gate must never crash the pipeline
        logger.exception("binding_validator: internal error (degrading to warning)")
        warnings.append({"file": None, "kind": "validator_error", "ref": None,
                         "detail": f"binding_validator internal error: {e}"})
        return {"ok": True, "errors": errors, "warnings": warnings}

    return {"ok": not errors, "errors": errors, "warnings": warnings}

"""The app SDK a coded page is written against, projected from the Blueprint.

A page the UI engineer writes as React (`pageCode`) may only say what the
application has: its entities' fields, its workflows' inputs, its pages'
routes. Those facts live in the Blueprint, so they are projected here as
TypeScript — and the compiler, not a heuristic validator, is what refuses a
page that names a field the entity lacks, a form that leaves a workflow input
out, or a link to a route that does not exist.

Three generated modules under ``src/sdk/``:

* ``schema.ts``    one interface per entity, with the columns exactly as the
                   data projection writes them (same reconciliation, same
                   builders), and which of them are numeric;
* ``workflows.ts`` one typed handle per workflow — its id, and its inputs as
                   an object type;
* ``pages.ts``     one typed handle per page and ``href`` to build a link.

``server.ts``, ``client.tsx`` and ``frame.tsx`` are the SDK's fixed half; they
ship with the scaffold (``templates/app-foundation/src/sdk``).

Deterministic and idempotent: the same Blueprint writes the same bytes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from services.blueprint.projection import (
    _TYPES, _DEFAULT_TYPE, _is_credential_field, _live, is_list_type,
    reconcile_platform_table,
)

SDK_DIR = "src/sdk"
HEADER = ("// Generated from the Living Blueprint — the app SDK a coded page is written\n"
          "// against. Edit the Blueprint, not this file.\n")

_RESERVED = frozenset({
    "break", "case", "catch", "class", "const", "continue", "debugger", "default", "delete",
    "do", "else", "enum", "export", "extends", "false", "finally", "for", "function", "if",
    "import", "in", "instanceof", "new", "null", "return", "super", "switch", "this", "throw",
    "true", "try", "typeof", "var", "void", "while", "with", "yield", "let", "static",
    "implements", "interface", "package", "private", "protected", "public", "await",
})


# Type names an entity's interface may not take. A global it would shadow breaks
# the SDK's own code (an entity `Record` turns every `Record<string, …>` in
# schema.ts into "Type 'Record' is not generic"); a name the SDK itself exports
# makes index.ts's `export *` ambiguous.
_TAKEN_TYPES = frozenset({
    # TypeScript / ECMAScript
    "Record", "Partial", "Required", "Readonly", "Pick", "Omit", "Exclude", "Extract",
    "NonNullable", "ReturnType", "Parameters", "InstanceType", "Awaited", "Uppercase",
    "Lowercase", "Capitalize", "Uncapitalize", "ReadonlyArray", "PropertyKey",
    "Map", "Set", "WeakMap", "WeakSet", "WeakRef", "Date", "Error", "TypeError",
    "RangeError", "SyntaxError", "Promise", "Array", "Object", "Function", "String",
    "Number", "Boolean", "Symbol", "BigInt", "RegExp", "Math", "JSON", "Intl",
    "Proxy", "Reflect", "Iterator", "Iterable", "Generator", "ArrayBuffer",
    "DataView", "Infinity", "NaN",
    # DOM / web platform
    "Event", "Node", "Element", "Document", "Window", "Request", "Response", "File",
    "Blob", "URL", "Image", "Text", "Location", "Storage", "Headers", "Comment",
    "Attr", "Range", "Selection", "History", "Navigator", "Screen", "Notification",
    "Option", "Audio", "Worker", "Crypto", "Performance", "Animation", "FormData",
    "Credential", "Report", "Plugin", "Touch", "Clipboard", "Cache", "Lock",
    "Permissions", "Position", "Geolocation", "MessageEvent", "WebSocket", "Console",
    # React / Next.js (JSX namespace and common ambient names)
    "React", "JSX", "Component", "Fragment",
    # The SDK's own exports (schema.ts, workflows.ts, pages.ts)
    "Entities", "EntityName", "NumericField", "Workflow", "WorkflowKey", "InputOf",
    "PageRef", "PageContext",
})


def _words(text: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))
    return [w for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def pascal(text: str) -> str:
    out = "".join(w[:1].upper() + w[1:] for w in _words(text)) or "Item"
    return out if out[0].isalpha() else "T" + out


def camel(text: str) -> str:
    p = pascal(text)
    out = p[:1].lower() + p[1:]
    return out + "_" if out in _RESERVED else out


def _unique(names: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}{seen[n]}")
        else:
            seen[n] = 1
            out.append(n)
    return out


def _prop(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name) else json.dumps(name)


def _literal_union(values: list[Any]) -> str:
    return " | ".join(json.dumps(str(v.get("value") if isinstance(v, dict) else v)) for v in values)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

def entity_columns(entity: dict, doc: dict) -> list[dict]:
    """The columns a page may read — the table's own, by the data projection's
    rules (platform reconciliation, the implicit uuid key, relationship FK
    columns), less any credential. A password hash is a column of `users`;
    it is never something a screen shows, and the SDK returns only what is
    typed here, so leaving it out keeps it off the wire as well."""
    fields, _ = reconcile_platform_table(entity)
    fields = [dict(f) for f in fields if f.get("name") and not _is_credential_field(str(f["name"]))]
    if not any(f.get("primaryKey") for f in fields):
        fields.insert(0, {"name": "id", "type": "uuid", "primaryKey": True})
    names = {f["name"] for f in fields}
    for rel in (doc.get("data") or {}).get("relationships") or []:
        col = rel.get("fromField")
        if rel.get("from") == entity.get("id") and col and col not in names:
            fields.append({"name": col, "type": "uuid"})
            names.add(col)
    return fields


def ts_type(field: dict) -> str:
    """The value a row carries for this column, as the SDK hands it over:
    numbers as numbers (numeric columns are coerced), dates as ISO strings."""
    type_name = str(field.get("type") or "").lower()
    if is_list_type(type_name):
        return "string[]"
    enum = field.get("enumValues") or field.get("enum")
    if isinstance(enum, list) and enum:
        return _literal_union(enum)
    builder = _TYPES.get(type_name, _DEFAULT_TYPE)
    return {"integer": "number", "numeric": "number", "boolean": "boolean",
            "jsonb": "unknown"}.get(builder, "string")


def _numeric(field: dict) -> bool:
    type_name = str(field.get("type") or "").lower()
    return not is_list_type(type_name) and _TYPES.get(type_name, _DEFAULT_TYPE) in ("integer", "numeric")


def _type_name(text: str) -> str:
    name = pascal(text)
    return name + "Row" if name in _TAKEN_TYPES else name


def entity_type_names(doc: dict) -> dict[str, str]:
    """Entity id -> its TypeScript type name (also the SDK's entity key)."""
    ents = _live((doc.get("data") or {}).get("entities"))
    names = _unique(_type_name(e.get("name") or e.get("id")) for e in ents)
    return {str(e.get("id")): n for e, n in zip(ents, names)}


def emit_schema(doc: dict) -> str:
    ents = _live((doc.get("data") or {}).get("entities"))
    types = entity_type_names(doc)
    out = [HEADER]
    entries, numeric = [], []
    for e in ents:
        name = types[str(e.get("id"))]
        desc = str(e.get("description") or "").strip().replace("*/", "")
        out.append(f"/** {e.get('name')}{' — ' + desc if desc else ''} */")
        out.append(f"export interface {name} {{")
        cols = entity_columns(e, doc)
        for f in cols:
            required = bool(f.get("required") or f.get("primaryKey"))
            note = str(f.get("description") or "").strip().replace("*/", "")
            if note:
                out.append(f"  /** {note[:160]} */")
            out.append(f"  {_prop(f['name'])}: {ts_type(f)}{'' if required else ' | null'};")
        out.append("}")
        out.append("")
        # The key the data engine resolves: the entity's own name.
        entries.append(f"  {json.dumps(str(e.get('name')))}: {name};")
        numeric.append(f"  {json.dumps(str(e.get('name')))}: "
                       f"{json.dumps([f['name'] for f in cols if _numeric(f)])},")
    out.append("/** Every entity, by the name the SDK's reads take. */")
    out.append("export interface Entities {")
    out.extend(entries or ["  [name: string]: never;"])
    out.append("}")
    out.append("")
    out.append("export type EntityName = keyof Entities & string;")
    out.append("")
    out.append("/** The numeric fields of an entity — what `total` and `series` can add up. */")
    out.append("export type NumericField<E extends EntityName> = {")
    out.append("  [K in keyof Entities[E]]-?: NonNullable<Entities[E][K]> extends number ? K : never;")
    out.append("}[keyof Entities[E]] & string;")
    out.append("")
    out.append("/** The columns the SDK returns for each entity — exactly the typed ones. */")
    out.append("export const READABLE_FIELDS: Record<string, readonly string[]> = {")
    for e in ents:
        out.append(f"  {json.dumps(str(e.get('name')))}: "
                   f"{json.dumps([f['name'] for f in entity_columns(e, doc)])},")
    out.append("};")
    out.append("")
    out.append("/** Columns the driver returns as strings that the SDK hands over as numbers. */")
    out.append("export const NUMERIC_FIELDS: Record<string, readonly string[]> = {")
    out.extend(numeric)
    out.append("};")
    out.append("")
    out.append("/** The display label of each entity's records. */")
    out.append("export const LABEL_FIELD: Record<string, string> = {")
    for e in ents:
        cols = [f["name"] for f in entity_columns(e, doc)]
        label = e.get("labelField") or next((c for c in ("name", "title", "fullName", "label")
                                             if c in cols), None) \
            or next((c for c in cols if c != "id"), "id")
        out.append(f"  {json.dumps(str(e.get('name')))}: {json.dumps(label)},")
    out.append("};")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

def _step_entities(doc: dict, wf: dict) -> list[dict]:
    ents = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    by_name = {str(e.get("name")): e for e in ents.values()}
    out = []
    for step in wf.get("steps") or []:
        ref = str(step.get("entity") or "")
        e = ents.get(ref) or by_name.get(ref)
        if e and e not in out:
            out.append(e)
    return out


def input_type(doc: dict, wf: dict, inp: dict) -> str:
    """A field input takes the type of the column it writes when a step's
    entity has one of that name (so an enum keeps its values); a record input
    is the record's id."""
    if inp.get("kind") == "record":
        return "string"
    name = str(inp.get("name") or "")
    for e in _step_entities(doc, wf):
        col = next((f for f in e.get("fields") or [] if f.get("name") == name), None)
        if col:
            return ts_type(col)
    return ts_type({"type": inp.get("type") or "string", "enumValues": inp.get("enumValues")})


def workflow_keys(doc: dict) -> dict[str, str]:
    wfs = _live(doc.get("workflows"))
    keys = _unique(camel(w.get("name") or w.get("id")) for w in wfs)
    return {str(w.get("id")): k for w, k in zip(wfs, keys)}


def emit_workflows(doc: dict) -> str:
    keys = workflow_keys(doc)
    out = [HEADER,
           "/** A workflow a page can run. `I` is its input — what a form must collect",
           " *  or a button must pass. The phantom `__input` field only carries the type. */",
           "export interface Workflow<I> {",
           "  id: string;",
           "  name: string;",
           "  /** The inputs it cannot run without — what a form marks required. */",
           "  required?: readonly string[];",
           "  readonly __input?: I;",
           "}",
           "",
           "function wf<I>(id: string, name: string, required: readonly string[] = []): Workflow<I> {",
           "  return { id, name, required };",
           "}",
           ""]
    body = []
    for w in _live(doc.get("workflows")):
        wid = str(w.get("id"))
        props: list[str] = []
        for inp in w.get("inputs") or []:
            if not isinstance(inp, dict) or not inp.get("name"):
                continue
            opt = "" if inp.get("required", True) else "?"
            what = str(inp.get("description") or "").strip().replace("*/", "")
            if inp.get("kind") == "record":
                target = next((e for e in _live((doc.get("data") or {}).get("entities"))
                               if str(e.get("id")) == str(inp.get("entity"))
                               or str(e.get("name")) == str(inp.get("entity"))), None)
                what = (f"id of the {target.get('name')} record" if target else "a record id") \
                    + (f" — {what}" if what else "")
            if what:
                props.append(f"    /** {what[:160]} */")
            props.append(f"    {_prop(str(inp['name']))}{opt}: {input_type(doc, w, inp)};")
        purpose = str(w.get("purpose") or "").strip().replace("*/", "")
        typ = ("{\n" + "\n".join(props) + "\n  }") if props else "Record<string, never>"
        if purpose:
            body.append(f"  /** {w.get('name')} — {purpose[:200]} */")
        # The required names travel as a VALUE too: the type says which inputs
        # a form must have, and only a value can reach the rendered form — an
        # "asterisk marks required" card with no asterisk anywhere (h7gmi93x).
        required = [str(i["name"]) for i in w.get("inputs") or []
                    if isinstance(i, dict) and i.get("name") and i.get("required", True)]
        body.append(f"  {keys[wid]}: wf<{typ}>({json.dumps(wid)}, {json.dumps(str(w.get('name') or wid))}"
                    + (f", {json.dumps(required)}" if required else "") + "),")
    out.append("export const workflows = {")
    out.extend(body)
    out.append("} as const;")
    out.append("")
    out.append("export type WorkflowKey = keyof typeof workflows;")
    out.append("/** The input type of a workflow handle. */")
    out.append("export type InputOf<W> = W extends Workflow<infer I> ? I : never;")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_keys(doc: dict) -> dict[str, str]:
    pages = _live(doc.get("pages"))
    keys = _unique(camel(p.get("name") or p.get("route") or p.get("id")) for p in pages)
    return {str(p.get("id")): k for p, k in zip(pages, keys)}


def emit_pages(doc: dict) -> str:
    keys = page_keys(doc)
    out = [HEADER,
           "/** A page of this application. `R` is its route; `[param]` segments are",
           " *  what `href` must be given. */",
           "export interface PageRef<R extends string = string> {",
           "  id: string;",
           "  name: string;",
           "  route: R;",
           "}",
           "",
           "type Params<R extends string> = R extends `${string}[${infer P}]${infer Rest}`",
           "  ? { [K in P | keyof Params<Rest>]: string } : {};",
           "",
           "/** The URL of a page: `href(pages.caseDetail, { id: row.id })`. */",
           "export function href<R extends string>(",
           "  page: PageRef<R>,",
           "  ...args: keyof Params<R> extends never",
           "    ? [params?: Record<string, never>, query?: Record<string, string | undefined>]",
           "    : [params: Params<R>, query?: Record<string, string | undefined>]",
           "): string {",
           "  const [params, query] = args as [Record<string, string> | undefined, Record<string, string | undefined> | undefined];",
           "  const path = page.route.replace(/\\[([^\\]]+)\\]/g, (_, k: string) => encodeURIComponent(params?.[k] ?? \"\"));",
           "  const q = Object.entries(query ?? {}).filter(([, v]) => v !== undefined && v !== \"\");",
           "  return q.length ? `${path}?${new URLSearchParams(q as [string, string][]).toString()}` : path;",
           "}",
           "",
           "export const pages = {"]
    for p in _live(doc.get("pages")):
        purpose = str(p.get("purpose") or "").strip().replace("*/", "")
        if purpose:
            out.append(f"  /** {purpose[:160]} */")
        route = str(p.get("route") or "/")
        out.append(f"  {keys[str(p.get('id'))]}: {{ id: {json.dumps(str(p.get('id')))}, "
                   f"name: {json.dumps(str(p.get('name') or route))}, route: {json.dumps(route)} }} "
                   f"as PageRef<{json.dumps(route)}>,")
    out.append("} as const;")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Widgets — the analytics the Blueprint attaches to pages
# ---------------------------------------------------------------------------

def widget_keys(doc: dict) -> dict[str, str]:
    widgets = _live(doc.get("widgets"))
    keys = _unique(camel(w.get("label") or w.get("id")) for w in widgets)
    return {str(w.get("id")): k for w, k in zip(widgets, keys)}


def widget_query(doc: dict, widget: dict) -> dict | None:
    """A widget's data source as the Data Engine runs it: `query` (measures by
    dimensions) for every analytic, `list` for rows. The older `aggregate` and
    `series` shapes are the same query with one measure, so they are written
    as one here rather than carried as three code paths into every app."""
    ents = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    src = widget.get("dataSource") or {}
    entity = ents.get(str(src.get("entity")))
    if entity is None:
        return None
    name = str(entity.get("name"))
    filt = dict(src.get("filter") or {})
    op = src.get("op")

    def measure(agg: str | None, field: str | None, key: str = "value") -> dict:
        # `ratio` names what the column already holds; its average is the ratio.
        agg = "avg" if agg == "ratio" else (agg or "count")
        m = {"key": key, "label": widget.get("label") or key, "aggregation": agg}
        if field and agg != "count":
            m["field"] = field
        return m

    if op == "query":
        out = {"op": "query", "entity": name,
               "measures": [{k: v for k, v in m.items() if v is not None}
                            for m in src.get("measures") or []],
               "dimensions": [{k: v for k, v in d.items() if v is not None}
                              for d in src.get("dimensions") or []],
               "filter": filt}
        for k in ("timeField", "sort", "limit"):
            if src.get(k) is not None:
                out[k] = src[k]
        return out
    if op == "aggregate":
        return {"op": "query", "entity": name, "filter": filt, "dimensions": [],
                "measures": [measure(src.get("aggregation"), src.get("field"))]}
    if op == "series":
        return {"op": "query", "entity": name, "filter": filt,
                "dimensions": [{"field": src.get("groupBy")}],
                "measures": [measure(src.get("aggregation"), src.get("field"))]}
    if op in ("list", "single"):
        out = {"op": "list", "entity": name, "filter": filt,
               "fields": list(src.get("fields") or []),
               "limit": 1 if op == "single" else int(src.get("limit") or 10)}
        if src.get("sort"):
            out["sort"] = src["sort"]
        return out
    return None


def emit_widgets(doc: dict) -> str:
    keys = widget_keys(doc)
    out = [HEADER,
           'import type { EntityName } from "./schema";',
           "",
           "export type WidgetUnit = \"number\" | \"currency\" | \"percent\" | \"duration\" | \"date\" | \"text\";",
           "export type ChartMark = \"bar\" | \"line\" | \"area\" | \"pie\" | \"donut\" | \"funnel\" | \"radar\" | \"scatter\" | \"heatmap\" | \"treemap\";",
           "export type WidgetSource =",
           "  | { op: \"query\"; entity: EntityName;",
           "      measures: readonly { key: string; label?: string; aggregation: \"count\" | \"count_distinct\" | \"sum\" | \"avg\" | \"min\" | \"max\"; field?: string }[];",
           "      dimensions: readonly { field: string; bucket?: \"day\" | \"week\" | \"month\" | \"quarter\" | \"year\" }[];",
           "      filter: Readonly<Record<string, unknown>>; timeField?: string;",
           "      sort?: { by: string; order?: \"asc\" | \"desc\" }; limit?: number }",
           "  | { op: \"list\"; entity: EntityName; fields: readonly string[];",
           "      filter: Readonly<Record<string, unknown>>; sort?: string; limit: number };",
           "",
           "/** An analytic the Blueprint attaches to a page. Read it in `load.ts` with",
           " *  `runWidget(widgets.x)` and draw it in `view.tsx` with",
           " *  `<WidgetView widget={widgets.x} data={…} />`. */",
           "export interface WidgetRef {",
           "  id: string;",
           "  page: string;",
           "  label: string;",
           "  description?: string;",
           "  kind: \"metric\" | \"chart\" | \"list\" | \"table\" | \"feed\" | \"gauge\" | \"text\";",
           "  unit: WidgetUnit;",
           "  size?: \"sm\" | \"md\" | \"lg\" | \"full\";",
           "  chart?: { mark: ChartMark; stacked?: boolean; horizontal?: boolean };",
           "  source: WidgetSource;",
           "}",
           "",
           "export const widgets = {"]
    ordered = sorted(_live(doc.get("widgets")),
                     key=lambda w: (str(w.get("page") or ""), w.get("order") or 0))
    for w in ordered:
        source = widget_query(doc, w)
        if source is None:
            continue
        ref = {"id": str(w.get("id")), "page": str(w.get("page") or ""),
               "label": str(w.get("label") or ""), "kind": w.get("kind") or "metric",
               "unit": w.get("unit") or "number"}
        for k in ("description", "size", "chart"):
            if w.get(k):
                ref[k] = w[k]
        ref["source"] = source
        out.append(f"  {keys[str(w.get('id'))]}: {json.dumps(ref)} as const satisfies WidgetRef,")
    out.append("} as const;")
    return "\n".join(out) + "\n"


def emit_index() -> str:
    return (HEADER + "// What a view may import: the types and handles, never the server reads.\n"
            'export * from "./schema";\n'
            'export * from "./workflows";\n'
            'export * from "./pages";\n'
            'export * from "./widgets";\n')


def sdk_files(doc: dict) -> dict[str, str]:
    """``{relative path: content}`` of the generated SDK modules."""
    return {
        f"{SDK_DIR}/schema.ts": emit_schema(doc),
        f"{SDK_DIR}/workflows.ts": emit_workflows(doc),
        f"{SDK_DIR}/pages.ts": emit_pages(doc),
        f"{SDK_DIR}/widgets.ts": emit_widgets(doc),
        f"{SDK_DIR}/index.ts": emit_index(),
    }


def project_app_sdk(doc: dict, app_root: str | Path) -> list[str]:
    """Write the generated SDK modules; returns the paths written."""
    root = Path(app_root)
    written = []
    for rel, content in sdk_files(doc).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != content:
            path.write_text(content)
        written.append(rel)
    return written


def sdk_reference(doc: dict) -> str:
    """The generated modules as one block — what the UI engineer reads."""
    return "\n".join(f"// ---- @/sdk/{Path(rel).stem} ----\n{content}"
                     for rel, content in sdk_files(doc).items() if not rel.endswith("index.ts"))


# ---------------------------------------------------------------------------
# Coded pages
# ---------------------------------------------------------------------------

CODE_PAGE_MARKER = "// forge:code-page"

#: Where `/` lives when it has code. The optional catch-all `[[...slug]]`
#: answers `/`, and Next refuses a second answer, so the root page is a private
#: module (`_root`, never routed by Next) that the catch-all renders. The
#: scaffold ships a stub there; the stub is put back when `/` has no code.
ROOT_DIR = "src/app/_root"
_ROOT_STUB = Path(__file__).resolve().parents[2] / "templates/standalone-app/src/app/_root/page.tsx"


def code_page_dir(page: dict) -> str:
    """Where a coded page lives, relative to the app root — where the page's
    route file would live anyway. A public page sits outside `(dashboard)`,
    as `project_public_routes` puts it (that group's layout redirects anyone
    signed out); every other page inside it, in the application's shell and
    behind its session gate. A static segment outranks the scaffold's dynamic
    routes either way."""
    from services.blueprint.projection import public_route_segments

    route = str(page.get("route") or "/").strip("/")
    if not route:
        return ROOT_DIR
    public = public_route_segments(page)
    if public:
        return "src/app/" + "/".join(public)
    return "src/app/(dashboard)/" + route


def _entities_read(doc: dict, code: str) -> list[str]:
    names = [str(e.get("name")) for e in _live((doc.get("data") or {}).get("entities"))]
    return [n for n in names if re.search(r"[\"'`]" + re.escape(n) + r"[\"'`]", code)]


def page_module(doc: dict, page: dict, row: dict) -> str:
    """The route's `page.tsx`: fixed, so every coded page gets the same frame,
    the same context and the same 404 — and `View`'s props are, by
    construction, what `load` returned."""
    from services.blueprint.projection import public_route_segments

    entities = _entities_read(doc, str(row.get("load") or ""))
    # A public root has no segments of its own but is still a public page.
    public = (page.get("access") or "authenticated") == "public" and (
        public_route_segments(page) is not None or not str(page.get("route") or "/").strip("/"))
    # A public page renders as the public route file it replaces does — in
    # the public frame, with no rail into a product the visitor cannot reach.
    frame_open = "<PublicPageFrame><PageFrame" if public else "<PageFrame"
    frame_close = "</PageFrame></PublicPageFrame>" if public else "</PageFrame>"
    frame_import = ('import { PublicPageFrame } from "@/components/PublicPageFrame";\n'
                    if public else "")
    root = code_page_dir(page) == ROOT_DIR
    return (
        f"{CODE_PAGE_MARKER} {page.get('id')}\n"
        f"// {page.get('name')} — generated from the Living Blueprint (pageCode). Edit the\n"
        "// Blueprint, not this file.\n"
        'import { notFound } from "next/navigation";\n'
        'import { currentUser, type PageContext } from "@/sdk/server";\n'
        'import { PageFrame } from "@/sdk/frame";\n'
        + frame_import +
        'import { load } from "./load";\n'
        'import View from "./view";\n'
        "\n"
        'export const dynamic = "force-dynamic";\n'
        + ("// The catch-all renders this for `/` (see ROOT_DIR).\nexport const hasCodeRoot = true;\n"
           if root else "")
        + "\n"
        "type Search = Record<string, string | string[] | undefined>;\n"
        "\n"
        "export default async function Page(props: { params: Promise<Record<string, string>>; searchParams: Promise<Search> }) {\n"
        "  const params = await props.params;\n"
        "  const search = await props.searchParams;\n"
        "  const ctx: PageContext = {\n"
        "    params: params ?? {},\n"
        "    searchParams: Object.fromEntries(Object.entries(search ?? {}).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v])),\n"
        "    user: await currentUser(),\n"
        "  };\n"
        "  const data = await load(ctx);\n"
        "  if (data === null) notFound();\n"
        "  return (\n"
        f"    {frame_open} entities={{{json.dumps(entities)}}}>\n"
        "      <View {...data} />\n"
        f"    {frame_close}\n"
        "  );\n"
        "}\n"
    )


def code_page_files(doc: dict, row: dict) -> dict[str, str]:
    """``{relative path: content}`` for one `pageCode` row."""
    page = next((p for p in _live(doc.get("pages")) if str(p.get("id")) == str(row.get("page"))), None)
    if page is None:
        return {}
    base = code_page_dir(page)
    return {
        f"{base}/page.tsx": page_module(doc, page, row),
        f"{base}/load.ts": str(row.get("load") or ""),
        f"{base}/view.tsx": str(row.get("view") or ""),
    }


def project_code_pages(doc: dict, app_root: str | Path) -> list[str]:
    """Write every coded page, and remove the ones the Blueprint no longer has
    (found by their marker, so a hand-shipped route is never touched)."""
    root = Path(app_root)
    written: list[str] = []
    for row in _live(doc.get("pageCode")):
        for rel, content in code_page_files(doc, row).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.read_text() != content:
                path.write_text(content)
            written.append(rel)
    keep = {str(Path(r).parent) for r in written}
    app = root / "src/app"
    if app.is_dir():
        for page_file in sorted(app.rglob("page.tsx")):
            rel_dir = str(page_file.parent.relative_to(root))
            if rel_dir in keep:
                continue
            try:
                head = page_file.read_text()[:64]
            except OSError:
                continue
            if head.startswith(CODE_PAGE_MARKER):
                for name in ("page.tsx", "load.ts", "view.tsx"):
                    (page_file.parent / name).unlink(missing_ok=True)
                if page_file.parent == root / ROOT_DIR and _ROOT_STUB.exists():
                    # The catch-all imports it: `/` without code is the stub.
                    page_file.write_text(_ROOT_STUB.read_text())
                    continue
                parent = page_file.parent
                while parent != app and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
    return written


__all__ = ["project_app_sdk", "project_code_pages", "code_page_files", "code_page_dir",
           "sdk_files", "sdk_reference", "entity_type_names", "workflow_keys", "page_keys",
           "SDK_DIR", "CODE_PAGE_MARKER"]
